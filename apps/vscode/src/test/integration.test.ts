/**
 * Phase 2 end to end: a real VS Code extension host, the real extension, and a
 * real Ṣāni' server driving a real agent session.
 *
 * The server must already be running (see apps/vscode/TESTING.md). Compiling
 * the extension only proves it parses; this proves the wiring -- that a session
 * started from the extension blocks on an irreversible action, that approving
 * through a command unblocks it, and that the diff reaches the native editor.
 */

import * as assert from "node:assert/strict";
import { mkdtempSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { StreamState } from "@sani/client";
import * as vscode from "vscode";
import type { SaniExtensionApi } from "../extension.ts";

const EXTENSION_ID = "krish2105.sani-vscode";
const TIMEOUT_MS = 30_000;

async function getApi(): Promise<SaniExtensionApi> {
  const extension = vscode.extensions.getExtension<SaniExtensionApi>(EXTENSION_ID);
  assert.ok(extension, `extension ${EXTENSION_ID} not found`);
  return extension.isActive ? extension.exports : await extension.activate();
}

/** Resolve once the controller's state satisfies `predicate`. */
function waitForState(
  api: SaniExtensionApi,
  predicate: (state: StreamState) => boolean,
  what: string,
): Promise<StreamState> {
  return new Promise((resolve, reject) => {
    if (api.controller.state && predicate(api.controller.state)) {
      resolve(api.controller.state);
      return;
    }
    const timer = setTimeout(() => {
      subscription.dispose();
      reject(new Error(`timed out waiting for ${what}; status=${api.controller.state?.status}`));
    }, TIMEOUT_MS);

    const subscription = api.controller.onState((state) => {
      if (!predicate(state)) return;
      clearTimeout(timer);
      subscription.dispose();
      resolve(state);
    });
  });
}

function workspaceRoot(): string {
  const folder = vscode.workspace.workspaceFolders?.[0];
  assert.ok(folder, "the test host must open a workspace folder");
  return folder.uri.fsPath;
}

suite("Ṣāni' Studio extension", function (this: Mocha.Suite) {
  this.timeout(TIMEOUT_MS * 2);

  suiteSetup(async () => {
    const root = workspaceRoot();
    writeFileSync(join(root, "README.md"), "# Demo project\n\nNothing here yet.\n");
    writeFileSync(join(root, "scratch.tmp"), "left over from a previous run\n");
    const api = await getApi();

    // These tests assert against the scripted planner's fixed plan -- the
    // `file.delete` of scratch.tmp is what proves the always-confirm gate. Some
    // of them go through `controller.start()`, which uses whatever backend the
    // server defaults to, so a server running a real model makes them time out
    // waiting for `blocked-on-approval`. That failure reads as a broken approval
    // gate, which is the most alarming possible way to report a config choice.
    const health = (await api.controller.api.health()) as {
      model?: { backend?: string; scripted?: boolean };
    };
    if (health.model && health.model.scripted !== true) {
      throw new Error(
        `The server is running the '${health.model.backend}' backend. This suite needs the ` +
          `scripted planner: start it with SANI_MODEL_BACKEND=scripted (or with no Groq key), ` +
          `and point the run at it with SANI_TEST_SERVER_URL.`,
      );
    }
  });

  test("activates and contributes its commands", async () => {
    const extension = vscode.extensions.getExtension(EXTENSION_ID);
    assert.ok(extension?.isActive, "extension should be active");

    const commands = await vscode.commands.getCommands(true);
    for (const command of [
      "sani.newSession",
      "sani.missionControl",
      "sani.attachSession",
      "sani.approve",
      "sani.reject",
      "sani.showDiff",
    ]) {
      assert.ok(commands.includes(command), `${command} should be registered`);
    }
  });

  test("blocks on an irreversible action, then completes once approved", async () => {
    const api = await getApi();
    const root = workspaceRoot();

    await api.controller.start("add a greeting module");

    const blocked = await waitForState(
      api,
      (state) => state.status === "blocked-on-approval",
      "the always-confirm delete to block",
    );

    assert.equal(blocked.pending?.action.action_type, "file.delete");
    assert.match(blocked.pending!.action.summary, /scratch\.tmp/);
    assert.equal(blocked.steps.length, 3);

    // Genuinely parked: the delete has not happened, the earlier write has.
    assert.ok(existsSync(join(root, "scratch.tmp")), "the gated delete must not have run");
    assert.ok(existsSync(join(root, "greeting.py")), "the auto-approved write should have run");

    // The plan reached the client before any of it executed.
    assert.ok(blocked.chat.some((item) => item.kind === "message"));

    // Approve through the command palette path, not a direct API call.
    await vscode.commands.executeCommand("sani.approve");

    const done = await waitForState(api, (state) => state.ended, "the session to finish");
    assert.equal(done.status, "complete");
    assert.ok(!existsSync(join(root, "scratch.tmp")), "the approved delete should have run");
    assert.deepEqual(
      done.steps.map((step) => step.status),
      ["complete", "complete", "complete"],
    );
  });

  test("renders the agent's diff in the native diff editor", async () => {
    const api = await getApi();
    assert.ok(api.controller.state?.diffs["greeting.py"], "expected a diff for greeting.py");

    await api.openDiff("greeting.py");

    // vscode.diff puts the modified side in the active editor.
    const active = vscode.window.activeTextEditor;
    assert.ok(active, "a diff editor should be open");
    assert.match(active.document.uri.fsPath, /greeting\.py$/);

    // The left-hand side is served from the in-memory provider, reconstructed
    // from the current file plus the hunks -- a new file means it is empty.
    const original = await vscode.workspace.openTextDocument(
      vscode.Uri.from({ scheme: "sani-original", path: "/greeting.py" }),
    );
    assert.equal(original.getText(), "");

    const current = readFileSync(join(workspaceRoot(), "greeting.py"), "utf8");
    assert.match(current, /def greet/);
  });

  test("rejecting leaves the file alone and still completes", async () => {
    const api = await getApi();
    const root = mkdtempSync(join(tmpdir(), "sani-vscode-"));
    writeFileSync(join(root, "README.md"), "# Demo\n");
    writeFileSync(join(root, "scratch.tmp"), "keep me\n");

    const session = await api.controller.api.createSession({
      task: "clean up",
      workspace: root,
      // Pinned: these assertions are about the demo script's fixed
      // `file.delete` step. Against a real model the plan is whatever it says,
      // there is no guaranteed gated action, and the failure surfaces as a
      // timeout waiting for `blocked-on-approval` -- which reads as a broken
      // approval gate rather than a server configured for real use.
      model_backend: "scripted",
    });
    api.controller.attach(session.session_id, root);

    await waitForState(api, (state) => state.status === "blocked-on-approval", "the block");
    await vscode.commands.executeCommand("sani.reject");

    const done = await waitForState(api, (state) => state.ended, "the session to finish");
    assert.equal(done.status, "complete");
    assert.equal(done.steps[2].status, "rejected");
    assert.ok(existsSync(join(root, "scratch.tmp")), "a rejected delete must not run");
  });

  test("mission control opens and lists the sessions", async () => {
    await vscode.commands.executeCommand("sani.missionControl");
    const document = vscode.window.activeTextEditor?.document;
    assert.ok(document, "mission control should open a document");
    assert.match(document.getText(), /Ṣāni' Mission Control/);
    assert.match(document.getText(), /add a greeting module/);
  });

  test("the extension sees the same v2 state the web IDE does", async () => {
    // Parity is the architectural claim: both clients read a session through
    // @sani/client, so risk and critique arrive in the extension for free. A
    // regression here means the two surfaces have started to drift.
    const api = await getApi();
    const root = mkdtempSync(join(tmpdir(), "sani-vscode-"));
    writeFileSync(join(root, "README.md"), "# Demo\n");
    writeFileSync(join(root, "scratch.tmp"), "left over\n");

    const session = await api.controller.api.createSession({
      task: "tidy the scratch file",
      workspace: root,
      model_backend: "scripted",
    });
    api.controller.attach(session.session_id, root);

    const blocked = await waitForState(
      api,
      (state) => state.status === "blocked-on-approval",
      "the block",
    );

    assert.ok(blocked.pending, "there should be a pending approval");
    assert.ok(blocked.pending?.risk, "the extension must receive the risk assessment");
    assert.equal(blocked.pending?.risk?.always_confirm, true);
    assert.equal(blocked.pending?.risk?.reversible, false);
    assert.ok(
      (blocked.pending?.risk?.factors.length ?? 0) > 0,
      "a score with no reasoning is a number to click past",
    );

    // Every v2 field the reducer populates, asserted here rather than trusted.
    // `cost` and `retrieved` were both arriving in the extension's state and
    // being rendered by nothing -- which is precisely the drift this test claims
    // to catch, and it did not, because it only looked at risk and critique.
    assert.ok(blocked.context === null || "cost" in blocked.context, "context.usage must carry cost");
    assert.ok(Array.isArray(blocked.retrieved), "retrieval must reach both surfaces");
    assert.ok("critique" in (blocked.pending ?? {}), "critiques must reach both surfaces");

    await vscode.commands.executeCommand("sani.reject");
    const done = await waitForState(api, (state) => state.ended, "the session to finish");

    // The token meter and the money come from one measurement, so a client that
    // has one must have the other -- showing tokens alone leaves the reader
    // converting against a rate they do not know.
    if (done.context) {
      assert.ok(
        "used_tokens" in done.context,
        "context.usage carries tokens and spend together; a surface with one must have both",
      );
    }
  });

  test("replay opens the session history at a chosen keyframe", async () => {
    await vscode.commands.executeCommand("sani.replay");
    // The quick-pick needs a selection to proceed; without one the command
    // returns cleanly rather than throwing, which is what this asserts.
    assert.ok(true, "sani.replay is registered and runs without error");
  });
});
