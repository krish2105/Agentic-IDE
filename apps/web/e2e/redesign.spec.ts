/**
 * The Glass Cockpit surfaces, end to end.
 *
 * `ide.spec.ts` proves the product's original promise: plan, gate, approve.
 * This proves the things the redesign added, and it holds them to the same
 * standard -- that each one is a claim about the agent that a person can check,
 * not decoration. So: the risk score has to show its reasoning, replay has to
 * land on the moments a human was asked, the cognition graph has to say what
 * was read before planning, and every one of them has to work with 3D and
 * motion switched off.
 *
 * Both servers must already be running. See e2e/README.md.
 */
import { expect, test, type Page } from "@playwright/test";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { CONNECTION, SERVER, authHeaders, preflight } from "./preflight";

function makeWorkspace(): string {
  const dir = mkdtempSync(join(tmpdir(), "sani-e2e-"));
  writeFileSync(join(dir, "README.md"), "# Demo project\n\nNothing here yet.\n");
  writeFileSync(join(dir, "scratch.tmp"), "left over from a previous run\n");
  return dir;
}

/** A session parked on the always-confirm delete -- the one deterministic
 *  mid-plan position, and the only place the risk dial is on screen. */
async function blockedSession(page: Page): Promise<string> {
  const response = await page.request.post(`${SERVER}/session`, {
    headers: authHeaders(),
    data: { task: "add a greeting module", workspace: makeWorkspace(), model_backend: "scripted" },
  });
  const { session_id } = await response.json();
  await page.goto(`/session/${session_id}`);
  await expect(page.getByTestId("approval-card")).toBeVisible();
  return session_id;
}

/** Drive a session to completion so it has a full event log to replay. */
async function completedSession(page: Page): Promise<string> {
  const id = await blockedSession(page);
  await page.getByTestId("approve-button").click();
  await expect(page.getByTestId("status-pill")).toHaveAttribute("data-status", "complete", {
    timeout: 30_000,
  });
  return id;
}

test.describe("Glass Cockpit", () => {
  test.beforeAll(preflight);

  test.beforeEach(async ({ page }) => {
    await page.addInitScript((connection) => {
      window.localStorage.setItem("sani.serverUrl", connection.server);
      if (connection.token) window.localStorage.setItem("sani.authToken", connection.token);
      // Every assertion below is written against the no-3D path on purpose:
      // `off` is a first-class design target, not a degraded mode, and it is
      // what reduced-motion users and weak GPUs actually get.
      window.localStorage.setItem("sani.quality", "off");
    }, CONNECTION);
  });

  // --- risk -------------------------------------------------------------

  test("the risk dial scores the delete and shows its reasoning", async ({ page }) => {
    await blockedSession(page);

    const dial = page.getByTestId("risk-dial");
    await expect(dial).toBeVisible();

    // An always-confirm action has a floor of 50, so a delete can never be
    // presented as low-risk however small the change is.
    const score = Number(await dial.getAttribute("data-score"));
    expect(score).toBeGreaterThanOrEqual(50);
    expect(["high", "critical"]).toContain(await dial.getAttribute("data-band"));
    await expect(dial).toHaveAttribute("data-reversible", "false");
    await expect(dial).toContainText("Cannot be undone");

    // The factors are the feature. A bare number is something to click past.
    await expect(page.getByTestId("risk-factors")).toBeHidden();
    await page.getByTestId("risk-why").click();
    await expect(page.getByTestId("risk-factors")).toBeVisible();
    await expect(page.getByTestId("risk-factors").getByRole("listitem").first()).not.toBeEmpty();

    await page.screenshot({ path: "e2e/screenshots/10-risk-reasoning.png" });
  });

  // --- cognition graph --------------------------------------------------

  test("the cognition panel names every step without WebGL", async ({ page }) => {
    await blockedSession(page);
    await page.getByTestId("dock-tab-graph").click();

    // With quality `off` this is the flat renderer, and it must carry the same
    // information the 3D graph does rather than being a placeholder.
    const flat = page.getByTestId("cognition-flat");
    await expect(flat).toBeVisible();
    await expect(flat).toContainText("README");
    await expect(flat).toContainText("scratch");
    // Status per step, not just a list of descriptions.
    await expect(flat).toContainText("file_editor");
  });

  // --- replay -----------------------------------------------------------

  test("replay scrubs a finished session and marks where a human was asked", async ({
    page,
  }) => {
    await completedSession(page);

    await page.getByTestId("replay-toggle").click();
    const scrubber = page.getByTestId("replay-scrubber");
    await expect(scrubber).toBeVisible();

    // The whole point of the scrubber is that the eye finds the moments that
    // stopped for a person before it reads anything -- so the approval this
    // session was blocked on has to be one of the marks, and auto-approvals
    // deliberately are not.
    expect(await page.getByTestId("replay-keyframe").count()).toBeGreaterThan(0);
    await expect(page.locator('[data-testid="replay-keyframe"][data-kind="approval"]')).toHaveCount(
      1,
    );
    expect(
      await page.locator('[data-testid="replay-keyframe"][data-kind="plan"]').count(),
    ).toBeGreaterThan(0);

    const track = page.getByTestId("replay-track");
    const before = Number(await track.getAttribute("aria-valuenow"));

    // Keyboard-drivable, because a scrubber that is mouse-only excludes exactly
    // the users replay is most useful for.
    await track.focus();
    await page.keyboard.press("ArrowRight");
    await expect
      .poll(async () => Number(await track.getAttribute("aria-valuenow")))
      .toBeGreaterThan(before);

    await page.screenshot({ path: "e2e/screenshots/11-replay.png" });

    // Leaving replay returns the session to live.
    await page.getByTestId("replay-exit").click();
    await expect(scrubber).toBeHidden();
  });

  test("replay is not offered for a session that has not finished", async ({ page }) => {
    await blockedSession(page);
    // Scrubbing a live run would mean the visible state and the real state
    // disagree while an approval is pending -- the one moment that must not be
    // ambiguous.
    await expect(page.getByTestId("replay-scrubber")).toBeHidden();
  });

  // --- command palette and themes ---------------------------------------

  test("the command palette changes theme, and the choice survives a reload", async ({
    page,
  }) => {
    await page.goto("/");
    await expect(page.getByTestId("landing-hero")).toBeVisible();

    const html = page.locator("html");
    await expect(html).toHaveAttribute("data-theme", "void");

    await page.keyboard.press("ControlOrMeta+k");
    await expect(page.getByTestId("command-palette")).toBeVisible();
    await expect(page.getByTestId("command-input")).toBeFocused();

    await page.getByTestId("command-input").fill("aurora");
    await page.getByTestId("command-theme:aurora").click();

    await expect(html).toHaveAttribute("data-theme", "aurora");
    await expect(page.getByTestId("command-palette")).toBeHidden();

    // Written before paint by the bootstrap script, so a reload must not flash
    // the default theme first.
    await page.reload();
    await expect(html).toHaveAttribute("data-theme", "aurora");
  });

  test("escape closes the palette without running anything", async ({ page }) => {
    await page.goto("/");
    await page.keyboard.press("ControlOrMeta+k");
    await expect(page.getByTestId("command-palette")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("command-palette")).toBeHidden();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "void");
  });

  // --- race -------------------------------------------------------------

  test("the race board reports every racer, and says where the work actually is", async ({
    page,
  }) => {
    // A race needs a git repo; without one the server refuses plainly rather
    // than degrading to something that looks isolated but is not.
    const workspace = makeWorkspace();
    const git = async (...args: string[]) => {
      const { execFileSync } = await import("node:child_process");
      execFileSync("git", args, { cwd: workspace });
    };
    await git("init", "-b", "main");
    await git("config", "user.email", "e2e@example.com");
    await git("config", "user.name", "E2E");
    await git("add", "-A");
    await git("commit", "-m", "initial");

    const response = await page.request.post(`${SERVER}/race`, {
      headers: authHeaders(),
      data: { task: "add a greeting module", workspace, count: 2, model_backend: "scripted" },
    });
    expect(response.status()).toBe(201);
    const { race_id, racers } = await response.json();

    await page.goto(`/race/${race_id}`);
    const board = page.getByTestId("race-board");
    await expect(board).toBeVisible();

    for (const racer of racers) {
      await expect(board).toContainText(racer.label);
    }

    await page.screenshot({ path: "e2e/screenshots/12-race-board.png" });

    // Keeping a racer is where the product could most easily lie. The agent
    // edits the working directory and never commits, so "merge the branch"
    // would send the user to an empty ref -- the UI has to name the worktree
    // and say the work is uncommitted.
    await page.getByRole("button", { name: "Keep" }).first().click();

    const outcome = page.getByTestId("race-outcome");
    await expect(outcome).toBeVisible();
    await expect(outcome).toContainText("uncommitted");
    await expect(outcome).toContainText(racers[0].worktree);

    await page.screenshot({ path: "e2e/screenshots/13-race-kept.png" });
    await page.request.post(`${SERVER}/race/${race_id}/discard`, {
      headers: authHeaders(),
      data: {},
    });
  });
});
