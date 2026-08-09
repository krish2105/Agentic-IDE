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
if (process.env.SANI_TEST_SERVER_URL) {
  mkdirSync(join(workspace, ".vscode"), { recursive: true });
  writeFileSync(
    join(workspace, ".vscode", "settings.json"),
    JSON.stringify({ "sani.serverUrl": process.env.SANI_TEST_SERVER_URL }, null, 2),
  );
}

export default defineConfig({
  files: "dist/test/**/*.test.js",
  workspaceFolder: workspace,
  mocha: { ui: "tdd", timeout: 60_000 },
  launchArgs: [
    "--disable-extensions",
    "--disable-gpu",
    // This checkout's path is long enough that VS Code's default user-data-dir
    // (nested under it) exceeds macOS's ~103-char limit for a Unix socket and
    // fails with `listen EINVAL`. Overridable for that reason only.
    ...(process.env.SANI_TEST_USER_DATA_DIR
      ? [`--user-data-dir=${process.env.SANI_TEST_USER_DATA_DIR}`]
      : []),
  ],
});
