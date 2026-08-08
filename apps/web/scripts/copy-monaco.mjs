/**
 * Copy Monaco's AMD bundle into public/ so the editor loads from this origin.
 *
 * @monaco-editor/react fetches from a CDN by default. That makes the IDE fail
 * on an offline machine and puts a third-party origin in the load path of the
 * main editing surface, so we serve it ourselves instead.
 */
import { cp, mkdir, stat } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const source = join(here, "..", "node_modules", "monaco-editor", "min", "vs");
const destination = join(here, "..", "public", "monaco", "vs");

try {
  await stat(source);
} catch {
  console.error(`monaco-editor not found at ${source}; run npm install first`);
  process.exit(1);
}

await mkdir(dirname(destination), { recursive: true });
await cp(source, destination, { recursive: true });
console.log(`monaco copied to ${destination}`);
