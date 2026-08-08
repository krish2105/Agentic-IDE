import { defineConfig } from "@vscode/test-cli";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// A throwaway folder per run: the tests let a real agent write and delete files
// in it, which is not something to point at the repo.
const workspace = mkdtempSync(join(tmpdir(), "sani-vscode-ws-"));

export default defineConfig({
  files: "dist/test/**/*.test.js",
  workspaceFolder: workspace,
  mocha: { ui: "tdd", timeout: 60_000 },
  launchArgs: ["--disable-extensions", "--disable-gpu"],
});
