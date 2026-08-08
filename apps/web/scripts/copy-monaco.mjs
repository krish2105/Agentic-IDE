/**
 * Copy Monaco's AMD bundle into public/ so the editor loads from this origin.
 *
 * @monaco-editor/react fetches from a CDN by default. That makes the IDE fail
 * on an offline machine and puts a third-party origin in the load path of the
 * main editing surface, so we serve it ourselves instead.
 */
import { cp, mkdir } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const destination = join(here, "..", "public", "monaco", "vs");

// Resolved rather than guessed at a relative path: npm workspaces hoist
// dependencies to the repo root, so monaco is not reliably a sibling.
//
// Resolving its entry point and walking up, rather than asking for
// "monaco-editor/package.json" directly -- the package's exports map does not
// expose that subpath, so the direct lookup throws.
const require = createRequire(import.meta.url);

function packageRoot(specifier) {
  let dir = dirname(require.resolve(specifier));
  while (dir !== dirname(dir)) {
    if (dir.endsWith(`node_modules/${specifier}`)) return dir;
    dir = dirname(dir);
  }
  throw new Error(`could not locate the ${specifier} package root`);
}

let source;
try {
  source = join(packageRoot("monaco-editor"), "min", "vs");
} catch (error) {
  console.error(`monaco-editor could not be located: ${error.message}`);
  console.error("run `npm install` at the repo root");
  process.exit(1);
}

await mkdir(dirname(destination), { recursive: true });
await cp(source, destination, { recursive: true });
console.log(`monaco copied from ${source} to ${destination}`);
