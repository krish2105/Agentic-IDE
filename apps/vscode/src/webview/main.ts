/**
 * Sidebar renderer. No network, no business logic -- it draws StreamState and
 * posts intents back to the extension host.
 *
 * Plain DOM rather than a framework: this is a narrow panel with three tabs,
 * and shipping React into every webview instance would cost more than it saves.
 */

import type { Critique, FileDiff, RiskAssessment, StreamState } from "@sani/client";

declare function acquireVsCodeApi(): { postMessage(message: unknown): void };
const vscode = acquireVsCodeApi();

type Tab = "chat" | "plan" | "diffs";
let tab: Tab = "chat";
let state: StreamState | null = null;
let sessionId: string | null = null;
/** Hunks the user has unticked in the current approval, by hunk id. */
let excludedHunks = new Set<string>();
let lastActionId: string | null = null;

const root = document.getElementById("root") as HTMLDivElement;

function el(tag: string, className?: string, text?: string): HTMLElement {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function post(message: unknown): void {
  vscode.postMessage(message);
}

function renderEmpty(): void {
  root.replaceChildren();
  const body = el("div", "body");
  body.append(el("p", "muted", "No active session."));

  const input = document.createElement("input");
  input.type = "text";
  input.placeholder = "What should the agent do?";
  input.id = "task";

  const start = el("button", "action", "Start session") as HTMLButtonElement;
  start.style.marginTop = "8px";
  const submit = () => {
    const task = input.value.trim();
    if (task) post({ type: "newSession", task });
  };
  start.addEventListener("click", submit);
  input.addEventListener("keydown", (event) => {
    if ((event as KeyboardEvent).key === "Enter") submit();
  });

  body.append(input, start);
  root.append(body);
}

function renderTabs(): HTMLElement {
  const bar = el("div", "tabs");
  const counts: Record<Tab, number | undefined> = {
    chat: undefined,
    plan: state?.steps.length || undefined,
    diffs: state ? Object.keys(state.diffs).length || undefined : undefined,
  };

  for (const name of ["chat", "plan", "diffs"] as Tab[]) {
    const label = counts[name] ? `${name} ${counts[name]}` : name;
    const button = el("button", `tab${tab === name ? " active" : ""}`, label);
    button.addEventListener("click", () => {
      tab = name;
      render();
    });
    bar.append(button);
  }
  return bar;
}

function renderApproval(body: HTMLElement): void {
  const pending = state?.pending;
  if (!pending) return;

  if (pending.action.id !== lastActionId) {
    lastActionId = pending.action.id;
    excludedHunks = new Set();
  }

  const card = el("div", "approval");
  card.append(el("h4", undefined, "Approval required"));
  card.append(el("div", undefined, pending.action.summary));
  card.append(el("div", "muted mono", pending.decision.reason));

  renderRisk(card, pending.risk);
  renderCritique(card, pending.critique);

  const command = (pending.action.preview as any)?.command;
  if (command) {
    const pre = el("pre", undefined, `$ ${command}`);
    card.append(pre);
    const runsIn = (pending.action.preview as any)?.runs_in;
    if (runsIn) {
      card.append(
        el(
          "div",
          "muted mono",
          runsIn.isolated ? `runs in ${runsIn.sandbox} container` : "runs on this machine",
        ),
      );
    }
  }

  const hunks = pending.action.diff?.hunks ?? [];
  for (const hunk of hunks) {
    const row = el("div", "hunk");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = !excludedHunks.has(hunk.id);
    box.addEventListener("change", () => {
      if (box.checked) excludedHunks.delete(hunk.id);
      else excludedHunks.add(hunk.id);
      render();
    });
    row.append(box, el("span", "mono muted", hunk.header));
    card.append(row);
  }

  const actions = el("div", "row");
  actions.style.marginTop = "8px";

  const partial = hunks.length > 0 && excludedHunks.size > 0;
  const included = hunks.filter((hunk) => !excludedHunks.has(hunk.id)).map((hunk) => hunk.id);
  const approve = el(
    "button",
    "action",
    partial ? `Approve ${included.length}/${hunks.length}` : "Approve",
  );
  approve.addEventListener("click", () =>
    post({ type: "approve", hunkIds: partial ? included : null }),
  );

  const reject = el("button", "action secondary", "Reject");
  reject.addEventListener("click", () => post({ type: "reject" }));

  actions.append(approve, reject);
  card.append(actions);
  body.append(card);
}

/**
 * Blast radius, before the decision.
 *
 * The same server-computed assessment the web IDE shows -- it arrives through
 * the shared reducer, so the two surfaces cannot disagree about the stakes of
 * an action. The score is the summary; the factors are the feature.
 */
function renderRisk(card: HTMLElement, risk: RiskAssessment | undefined): void {
  if (!risk) return;

  const band = el("div", `risk risk-${risk.band}`);
  band.append(
    el("strong", undefined, `${risk.band.toUpperCase()} risk`),
    el("span", "muted mono", ` ${risk.score}/100`),
  );
  card.append(band);

  card.append(
    el(
      "div",
      "muted",
      risk.reversible
        ? "Reversible — the previous state can be recovered."
        : "Cannot be undone from inside Ṣāni'.",
    ),
  );

  // Collapsed by default: a wall of reasoning on every approval trains people
  // to skip all of it.
  const details = document.createElement("details");
  const summary = document.createElement("summary");
  summary.className = "muted mono";
  summary.textContent = `why — ${risk.factors.length} factor${risk.factors.length === 1 ? "" : "s"}`;
  details.append(summary);
  for (const factor of risk.factors) {
    details.append(el("div", "muted", `· ${factor}`));
  }
  card.append(details);
}

/** The second opinion, when a critic is configured. */
function renderCritique(card: HTMLElement, critique: Critique | undefined): void {
  if (!critique) return;

  if (critique.error) {
    card.append(el("div", "muted mono", "Second opinion unavailable — the critic errored."));
    return;
  }
  // Silent when it has nothing to say: a critic that says "looks fine" on every
  // screen is one nobody reads on the screen that mattered.
  if (critique.clean && !critique.concerns.length) return;

  const label =
    critique.verdict === "likely-wrong"
      ? "Likely wrong"
      : critique.verdict === "concerns"
        ? "Worth a look"
        : "No concerns";

  card.append(el("div", "critique", `${label} — second opinion (${critique.reviewed_by})`));
  for (const concern of critique.concerns) {
    card.append(el("div", "muted", `· ${concern}`));
  }
}

function renderChat(body: HTMLElement): void {
  if (!state) return;
  for (const item of state.chat) {
    if (item.kind === "message") {
      body.append(el("div", "item agent", item.text));
      continue;
    }
    if (item.kind === "proposal") {
      const row = el("div", "item row");
      row.append(el("span", "muted", "→"), el("span", "mono", item.text));
      if (item.runsIn === "container") row.append(el("span", "muted mono", "[sandboxed]"));
      body.append(row);
      continue;
    }
    const entry = el("div", "item");
    const head = el("div", "row");
    head.append(
      el("span", item.ok === false ? "bad" : "ok", item.ok === false ? "✕" : "✓"),
      el("span", undefined, item.text),
    );
    entry.append(head);
    if (item.detail) entry.append(el("pre", undefined, item.detail));
    body.append(entry);
  }

  if (state.streamingMessage) {
    body.append(el("div", "item agent", state.streamingMessage));
  }
  if (state.chat.length === 0 && !state.streamingMessage) {
    body.append(el("p", "muted", "Waiting for the agent…"));
  }
}

function renderPlan(body: HTMLElement): void {
  if (!state || state.steps.length === 0) {
    body.append(el("p", "muted", "No plan yet."));
    return;
  }
  const list = el("ol");
  for (const step of state.steps) {
    const item = el("li");
    item.append(el("div", undefined, step.description));
    item.append(el("div", "muted mono", `${step.tool} · ${step.status}`));
    list.append(item);
  }
  body.append(list);
}

function renderDiffs(body: HTMLElement): void {
  const diffs: FileDiff[] = state ? Object.values(state.diffs) : [];
  if (diffs.length === 0) {
    body.append(el("p", "muted", "No changes yet."));
    return;
  }
  body.append(
    el("p", "muted", "Opens in the editor's own diff view."),
  );
  for (const diff of diffs) {
    const link = el("div", "item diff-link mono", diff.path);
    link.addEventListener("click", () => post({ type: "openDiff", path: diff.path }));
    body.append(link);
  }
}

function render(): void {
  if (!state || !sessionId) {
    renderEmpty();
    return;
  }

  root.replaceChildren();
  root.append(renderTabs());

  const body = el("div", "body");
  const header = el("div", "row");
  header.append(el("span", "muted mono", state.status));
  if (state.context) {
    header.append(
      el("span", "muted mono", `· ${state.context.used_tokens.toLocaleString()} tok`),
    );
  }
  if (!state.connected && !state.ended) header.append(el("span", "bad mono", "· reconnecting"));
  body.append(header);

  renderApproval(body);

  if (tab === "chat") renderChat(body);
  else if (tab === "plan") renderPlan(body);
  else renderDiffs(body);

  root.append(body);
}

window.addEventListener("message", (event) => {
  const message = event.data;
  if (message?.type === "state") {
    state = message.state;
    sessionId = message.sessionId;
    // An approval must never be hidden behind a tab the user is not on.
    if (state?.pending) tab = "chat";
    render();
  }
});

post({ type: "ready" });
render();
