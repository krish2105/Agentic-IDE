/**
 * Turning a FileDiff back into something an editor can render.
 *
 * The server sends hunks with context, not whole-file snapshots, which is right
 * for the wire but not enough for VS Code's diff editor -- that wants two full
 * documents. Both helpers here derive what is missing from the current file
 * plus the hunks, so no extra round trip is needed.
 */

import type { FileDiff, Hunk } from "./types.ts";

function splitKeepingEnds(text: string): string[] {
  if (text === "") return [];
  return text.split(/(?<=\n)/);
}

/**
 * Rebuild the pre-edit contents of a file from its current contents plus the
 * diff that produced them.
 *
 * Regions between hunks are unchanged, so they come from the current file;
 * inside a hunk, the old side is its context and removed lines.
 */
export function reconstructOriginal(currentText: string, diff: FileDiff): string {
  if (diff.is_new_file) return "";

  const current = splitKeepingEnds(currentText);
  const out: string[] = [];
  let cursor = 0;

  for (const hunk of diff.hunks) {
    out.push(...current.slice(cursor, hunk.new_start));
    for (const line of hunk.lines) {
      const marker = line[0];
      if (marker === "-" || marker === " ") out.push(line.slice(1));
    }
    cursor = hunk.new_start + hunk.new_lines;
  }

  out.push(...current.slice(cursor));
  return out.join("");
}

/** Zero-based line numbers in the *new* file that the agent added or changed. */
export function agentAuthoredLines(diff: FileDiff): number[] {
  const lines: number[] = [];
  for (const hunk of diff.hunks) {
    let lineNumber = hunk.new_start;
    for (const raw of hunk.lines) {
      const marker = raw[0];
      if (marker === "+") {
        lines.push(lineNumber);
        lineNumber += 1;
      } else if (marker === " ") {
        lineNumber += 1;
      }
      // A removed line occupies no room in the new file, so the cursor holds.
    }
  }
  return lines;
}

/** Collapse consecutive line numbers into inclusive ranges, for decorations. */
export function toLineRanges(lines: number[]): Array<[number, number]> {
  const sorted = [...new Set(lines)].sort((a, b) => a - b);
  const ranges: Array<[number, number]> = [];

  for (const line of sorted) {
    const last = ranges.at(-1);
    if (last && line === last[1] + 1) last[1] = line;
    else ranges.push([line, line]);
  }
  return ranges;
}

export function hunkSummary(hunk: Hunk): { added: number; removed: number } {
  let added = 0;
  let removed = 0;
  for (const line of hunk.lines) {
    if (line[0] === "+") added += 1;
    else if (line[0] === "-") removed += 1;
  }
  return { added, removed };
}
