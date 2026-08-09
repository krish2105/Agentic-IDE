/**
 * Phase 1 end-to-end: the real browser, the real Next.js app, the real FastAPI
 * server, one real agent session.
 *
 * The Python suite proves the contract. This proves the product: that a person
 * can open the IDE, watch a plan arrive, be stopped by an irreversible action,
 * approve it, and see the result land in the editor and the terminal.
 *
 * Both servers must already be running. See e2e/README.md.
 */
import { expect, test } from "@playwright/test";
import { mkdtempSync, writeFileSync, existsSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { CONNECTION, SERVER, authHeaders, preflight } from "./preflight";

function makeWorkspace(): string {
  const dir = mkdtempSync(join(tmpdir(), "sani-e2e-"));
  writeFileSync(join(dir, "README.md"), "# Demo project\n\nNothing here yet.\n");
  writeFileSync(join(dir, "scratch.tmp"), "left over from a previous run\n");
  return dir;
}

test.describe("Ṣāni' Studio web IDE", () => {
  test.beforeAll(preflight);

  // Point the app at the server under test through its own runtime override
  // rather than a build-time env var. That is the mechanism a hosted deploy
  // actually uses, so the suite exercises the real path and does not depend on
  // how the dev server happened to be started.
  test.beforeEach(async ({ page }) => {
    await page.addInitScript((connection) => {
      window.localStorage.setItem("sani.serverUrl", connection.server);
      if (connection.token) window.localStorage.setItem("sani.authToken", connection.token);
      // 3D off: WebGL in headless Chromium is slow and flaky, and every
      // surface is required to be fully usable without it. If a test needs the
      // 3D path it can opt back in.
      window.localStorage.setItem("sani.quality", "off");
    }, CONNECTION);
  });

  test("plan, block on an irreversible action, approve, and see the result", async ({
    page,
  }) => {
    const workspace = makeWorkspace();

    await page.goto("/");
    // The redesign made the h1 the promise ("Watch it think.") and demoted the
    // product name to a wordmark, so assert on the landing page's own testid
    // rather than on copy that is free to change.
    await expect(page.getByTestId("landing-hero")).toBeVisible();

    // --- create a session from the UI -------------------------------------
    await page.getByTestId("task-input").fill("add a greeting module");
    await page.getByTestId("workspace-input").fill(workspace);
    await page.getByTestId("create-session").click();

    await page.waitForURL(/\/session\/ses_/);
    const sessionId = page.url().split("/session/")[1];

    // --- the plan is streamed and shown before anything runs --------------
    await page.getByTestId("dock-tab-plan").click();
    await expect(page.getByTestId("plan-list")).toBeVisible();
    await expect(page.getByTestId("plan-step-0")).toContainText("README");
    await expect(page.getByTestId("plan-step-2")).toContainText("scratch");

    // --- the always-confirm delete stops the run --------------------------
    const approval = page.getByTestId("approval-card");
    await expect(approval).toBeVisible();
    await expect(approval).toHaveAttribute("data-action-type", "file.delete");
    await expect(page.getByTestId("approval-summary")).toContainText("scratch.tmp");
    await expect(page.getByTestId("status-pill")).toHaveAttribute(
      "data-status",
      "blocked-on-approval",
    );

    // It is genuinely blocked: the file is still on disk.
    expect(existsSync(join(workspace, "scratch.tmp"))).toBe(true);
    // The auto-approved write already happened.
    expect(existsSync(join(workspace, "greeting.py"))).toBe(true);

    await page.screenshot({ path: "e2e/screenshots/01-blocked-on-approval.png" });

    // --- the earlier write is visible as an agent-authored diff -----------
    await page.getByTestId("dock-tab-diffs").click();
    await expect(page.getByTestId("diff-path-greeting.py")).toBeVisible();

    // --- the file tree marks what the agent touched -----------------------
    await expect(page.getByTestId("file-greeting.py")).toHaveAttribute(
      "data-agent-touched",
      "true",
    );

    // --- approve, and the session finishes --------------------------------
    await page.getByTestId("approve-button").click();
    await expect(page.getByTestId("status-pill")).toHaveAttribute("data-status", "complete", {
      timeout: 20_000,
    });
    await expect(approval).toBeHidden();
    expect(existsSync(join(workspace, "scratch.tmp"))).toBe(false);

    // --- every plan step is accounted for ---------------------------------
    await page.getByTestId("dock-tab-plan").click();
    for (const index of [0, 1, 2]) {
      await expect(page.getByTestId(`plan-step-${index}`)).toHaveAttribute(
        "data-step-status",
        "complete",
      );
    }

    // --- the editor opens what the agent wrote ----------------------------
    await page.getByTestId("file-greeting.py").click();
    await expect(page.getByTestId("tab-greeting.py")).toBeVisible();
    await expect(page.getByTestId("editor-pane")).toContainText("def greet", {
      timeout: 20_000,
    });

    await page.screenshot({ path: "e2e/screenshots/02-complete.png" });

    // --- the terminal is live in the same workspace -----------------------
    const terminal = page.getByTestId("terminal-host");
    await expect(page.getByTestId("terminal-status")).toHaveText("ready", { timeout: 20_000 });
    await terminal.click();
    await page.keyboard.type("ls\r");
    await expect(terminal).toContainText("greeting.py", { timeout: 20_000 });

    await page.screenshot({ path: "e2e/screenshots/03-terminal.png", fullPage: false });

    // --- the trust ladder is visible, and the locked tiers are shown ------
    await page.getByTestId("dock-tab-trust").click();
    await expect(page.getByTestId("trust-panel")).toBeVisible();
    // Locked tiers are shown rather than hidden: the guarantee has to be
    // legible, not implied.
    await expect(page.getByTestId("trust-file.delete")).toHaveAttribute(
      "data-locked",
      "true",
    );
    await expect(page.getByTestId("trust-browser.navigate_external")).toHaveAttribute(
      "data-locked",
      "true",
    );
    // file.write is auto-approved from session start.
    await expect(page.getByTestId("trust-file.write")).toHaveAttribute("data-auto", "true");

    await page.screenshot({ path: "e2e/screenshots/04-trust-ladder.png" });

    // --- the session shows up on the dashboard ----------------------------
    await page.goto("/");
    await expect(page.getByTestId(`session-row-${sessionId}`)).toContainText(
      "add a greeting module",
    );
    await expect(page.getByTestId("board-summary")).toContainText("total");
  });

  test("a trust tier can be earned, and a locked one cannot be switched on", async ({
    page,
  }) => {
    const workspace = makeWorkspace();

    const created = await fetch(`${SERVER}/session`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ task: "trust ladder check", workspace, script: [] }),
    });
    const { session_id: sessionId } = await created.json();

    await page.goto(`/session/${sessionId}`);
    await page.getByTestId("dock-tab-trust").click();

    const shellOther = page.getByTestId("trust-shell.other");
    await expect(shellOther).toHaveAttribute("data-auto", "false");
    await shellOther.getByRole("button").click();
    await expect(shellOther).toHaveAttribute("data-auto", "true");

    // The locked tiers have no toggle at all -- the server would refuse it,
    // and offering a switch that cannot work is worse than not offering one.
    const locked = page.getByTestId("trust-file.delete");
    await expect(locked).toHaveAttribute("data-locked", "true");
    await expect(locked.getByRole("button")).toHaveCount(0);
  });

  test("parallel sessions get a tab strip", async ({ page }) => {
    const workspace = makeWorkspace();
    const ids: string[] = [];
    for (const task of ["first parallel session", "second parallel session"]) {
      const created = await fetch(`${SERVER}/session`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ task, workspace, script: [] }),
      });
      ids.push((await created.json()).session_id);
    }

    await page.goto(`/session/${ids[0]}`);
    await expect(page.getByTestId("session-tabs")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId(`session-tab-${ids[0]}`)).toHaveAttribute(
      "data-active",
      "true",
    );

    await page.getByTestId(`session-tab-${ids[1]}`).click();
    await page.waitForURL(`**/session/${ids[1]}`);
    await expect(page.getByTestId(`session-tab-${ids[1]}`)).toHaveAttribute(
      "data-active",
      "true",
    );
  });

  test("rejecting an action leaves the file alone and still completes", async ({ page }) => {
    const workspace = makeWorkspace();

    await page.goto("/");
    await page.getByTestId("task-input").fill("clean up the scratch file");
    await page.getByTestId("workspace-input").fill(workspace);
    await page.getByTestId("create-session").click();
    await page.waitForURL(/\/session\/ses_/);

    await expect(page.getByTestId("approval-card")).toBeVisible();
    await page.getByTestId("reject-button").click();

    await expect(page.getByTestId("status-pill")).toHaveAttribute("data-status", "complete", {
      timeout: 20_000,
    });

    // Rejection is not failure: the run completes, minus that one step.
    await page.getByTestId("dock-tab-plan").click();
    await expect(page.getByTestId("plan-step-2")).toHaveAttribute(
      "data-step-status",
      "rejected",
    );
    expect(existsSync(join(workspace, "scratch.tmp"))).toBe(true);
  });

  test("the backend URL is changeable at runtime, without a rebuild", async ({ page }) => {
    // The failure a hosted deploy hits: the bundle was compiled against one
    // backend URL and there is no way to point it somewhere else. There is now.
    await page.goto("/");
    await expect(page.getByTestId("session-list").or(page.getByText("No sessions yet"))).toBeVisible();

    // Point it at a port with nothing on it.
    await page.getByTestId("connection-toggle").click();
    await page.getByTestId("connection-server").fill("http://127.0.0.1:9");
    await page.getByTestId("connection-save").click();

    const banner = page.getByTestId("offline-banner");
    await expect(banner).toBeVisible({ timeout: 15_000 });
    await expect(banner).toContainText("127.0.0.1:9");

    // Point it back, without reloading or rebuilding anything.
    await page.getByTestId("open-connection").click();
    await page.getByTestId("connection-server").fill(SERVER);
    await page.getByTestId("connection-save").click();

    await expect(banner).toBeHidden({ timeout: 15_000 });
    await expect(page.getByTestId("board-summary")).toContainText("total");
  });

  test("the configured backend survives a reload", async ({ page }) => {
    await page.goto("/");
    await page.getByTestId("connection-toggle").click();
    await page.getByTestId("connection-server").fill(SERVER);
    await page.getByTestId("connection-save").click();

    await page.reload();
    await expect(page.getByTestId("connection-toggle")).toContainText(
      SERVER.replace(/^https?:\/\//, ""),
    );
  });

  test("a human edit in Monaco saves back to the workspace", async ({ page }) => {
    const workspace = makeWorkspace();

    const created = await fetch(`${SERVER}/session`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ task: "editor save check", workspace, script: [] }),
    });
    const { session_id: sessionId } = await created.json();

    await page.goto(`/session/${sessionId}`);
    await page.getByTestId("file-README.md").click();
    await expect(page.getByTestId("editor-pane")).toContainText("Demo project", {
      timeout: 20_000,
    });

    // Click the rendered lines, not the hidden textarea -- Monaco's overlay
    // intercepts pointer events aimed at the textarea itself.
    await page.locator(".monaco-editor .view-lines").first().click();
    await page.keyboard.press("Control+End");
    // Monaco drops characters typed at full speed, so pace the input.
    await page.keyboard.type(" EDITED-BY-HUMAN", { delay: 40 });

    await expect(page.getByTestId("editor-pane")).toContainText("EDITED-BY-HUMAN");
    await page.keyboard.press("Control+s");

    await expect
      .poll(() => readFileSync(join(workspace, "README.md"), "utf8"), { timeout: 15_000 })
      .toContain("EDITED-BY-HUMAN");
  });
});
