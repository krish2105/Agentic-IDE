import { build, context } from "esbuild";

/**
 * Two bundles: the extension host (Node, `vscode` provided at runtime) and the
 * webview (browser). Both pull the shared client package straight from source,
 * which is the point -- the sidebar and the web IDE interpret a session with
 * the same reducer rather than two that can drift.
 */
const shared = {
  bundle: true,
  minify: process.argv.includes("--minify"),
  sourcemap: true,
  logLevel: "info",
  resolveExtensions: [".ts", ".tsx", ".js", ".mjs"],
};

const targets = [
  {
    ...shared,
    entryPoints: ["src/extension.ts"],
    outfile: "dist/extension.js",
    platform: "node",
    format: "cjs",
    target: "node20",
    external: ["vscode"],
  },
  {
    ...shared,
    entryPoints: ["src/webview/main.ts"],
    outfile: "dist/webview.js",
    platform: "browser",
    format: "iife",
    target: "es2022",
  },
  {
    ...shared,
    // Integration tests run inside the extension host, so they build like the
    // extension does: CommonJS, with vscode and mocha provided by the runner.
    entryPoints: ["src/test/integration.test.ts"],
    outfile: "dist/test/integration.test.js",
    platform: "node",
    format: "cjs",
    target: "node20",
    external: ["vscode", "mocha"],
    minify: false,
  },
];

if (process.argv.includes("--watch")) {
  for (const options of targets) {
    const ctx = await context(options);
    await ctx.watch();
  }
} else {
  await Promise.all(targets.map((options) => build(options)));
}
