import { defineConfig } from "@vscode/test-cli";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// A throwaway folder per run: the tests let a real agent write and delete files
// in it, which is not something to point at the repo.
const workspace = mkdtempSync(join(tmpdir(), "sani-vscode-ws-"));

// The extension defaults to :8000, which is commonly occupied by something
// else on a developer machine. Pointing the run elsewhere is a local concern,
// so it is opt-in via env rather than a committed port change.
// `SANI_TEST_AUTH_TOKEN` goes in alongside it, so the suite can run against a
// server that has SANI_AUTH_TOKEN set. Without it every request 401s and the
// failures read as "Not Found"/"Unauthorized" from deep inside the client,
// which looks like an extension bug rather than a missing credential.
if (process.env.SANI_TEST_SERVER_URL || process.env.SANI_TEST_AUTH_TOKEN) {
  const settings = {};
  if (process.env.SANI_TEST_SERVER_URL)
    settings["sani.serverUrl"] = process.env.SANI_TEST_SERVER_URL;
  if (process.env.SANI_TEST_AUTH_TOKEN)
    settings["sani.authToken"] = process.env.SANI_TEST_AUTH_TOKEN;

  mkdirSync(join(workspace, ".vscode"), { recursive: true });
  writeFileSync(
    join(workspace, ".vscode", "settings.json"),
    JSON.stringify(settings, null, 2),
  );
}

// Short by construction: `/tmp/sani-vsct-XXXXXX` leaves ample room for the
// socket name VS Code appends. Overridable if you need to inspect the profile.
const userDataDir =
  process.env.SANI_TEST_USER_DATA_DIR ?? mkdtempSync(join(tmpdir(), "sani-vsct-"));

export default defineConfig({
  files: "dist/test/**/*.test.js",
  workspaceFolder: workspace,
  mocha: { ui: "tdd", timeout: 60_000 },
  launchArgs: [
    "--disable-extensions",
    "--disable-gpu",
    // VS Code puts its IPC socket inside the user-data dir, and the default sits
    // under this checkout -- whose path is long enough that the socket exceeds
    // the ~103-char limit macOS imposes on Unix domain sockets. It fails with
    // `listen EINVAL: invalid argument`, which names the socket and not the
    // cause. A short path is the default rather than opt-in because the limit is
    // about where the repo happens to live, so any deep checkout hits it and
    // nobody would guess the fix from the error.
    `--user-data-dir=${userDataDir}`,
  ],
});
