import assert from "node:assert/strict";
import { test } from "node:test";
import {
  agentAuthoredLines,
  hunkSummary,
  reconstructOriginal,
  toLineRanges,
} from "../src/diff-apply.ts";
import type { FileDiff } from "../src/types.ts";

/** Mirrors what the server's difflib-derived hunks look like on the wire. */
function diff(partial: Partial<FileDiff> & Pick<FileDiff, "hunks">): FileDiff {
  return {
    path: "f.py",
    unified: "",
    is_new_file: false,
    is_delete: false,
    ...partial,
  };
}

test("a single replacement reconstructs the original exactly", () => {
  const original = "one\ntwo\nthree\n";
  const current = "one\nTWO\nthree\n";
  const fileDiff = diff({
    hunks: [
      {
        id: "h0",
        header: "@@ -1,3 +1,3 @@",
        old_start: 0,
        old_lines: 3,
        new_start: 0,
        new_lines: 3,
        lines: [" one\n", "-two\n", "+TWO\n", " three\n"],
      },
    ],
  });

  assert.equal(reconstructOriginal(current, fileDiff), original);
});

test("regions between two hunks come from the current file untouched", () => {
  const original = Array.from({ length: 30 }, (_, i) => `line ${i + 1}\n`).join("");
  const currentLines = original.split(/(?<=\n)/);
  currentLines[0] = "TOP\n";
  currentLines[29] = "BOTTOM\n";
  const current = currentLines.join("");

  const fileDiff = diff({
    hunks: [
      {
        id: "h0",
        header: "",
        old_start: 0,
        old_lines: 4,
        new_start: 0,
        new_lines: 4,
        lines: ["-line 1\n", "+TOP\n", " line 2\n", " line 3\n", " line 4\n"],
      },
      {
        id: "h1",
        header: "",
        old_start: 26,
        old_lines: 4,
        new_start: 26,
        new_lines: 4,
        lines: [" line 27\n", " line 28\n", " line 29\n", "-line 30\n", "+BOTTOM\n"],
      },
    ],
  });

  assert.equal(reconstructOriginal(current, fileDiff), original);
});

test("insertions shrink the original by the inserted lines", () => {
  const current = "a\nNEW1\nNEW2\nb\n";
  const fileDiff = diff({
    hunks: [
      {
        id: "h0",
        header: "",
        old_start: 0,
        old_lines: 2,
        new_start: 0,
        new_lines: 4,
        lines: [" a\n", "+NEW1\n", "+NEW2\n", " b\n"],
      },
    ],
  });
  assert.equal(reconstructOriginal(current, fileDiff), "a\nb\n");
});

test("deletions restore the removed lines", () => {
  const current = "a\nd\n";
  const fileDiff = diff({
    hunks: [
      {
        id: "h0",
        header: "",
        old_start: 0,
        old_lines: 4,
        new_start: 0,
        new_lines: 2,
        lines: [" a\n", "-b\n", "-c\n", " d\n"],
      },
    ],
  });
  assert.equal(reconstructOriginal(current, fileDiff), "a\nb\nc\nd\n");
});

test("a new file has an empty original, whatever its hunks say", () => {
  const fileDiff = diff({
    is_new_file: true,
    hunks: [
      {
        id: "h0",
        header: "",
        old_start: 0,
        old_lines: 0,
        new_start: 0,
        new_lines: 2,
        lines: ["+a\n", "+b\n"],
      },
    ],
  });
  assert.equal(reconstructOriginal("a\nb\n", fileDiff), "");
});

test("added lines are located in the new file's coordinates", () => {
  const fileDiff = diff({
    hunks: [
      {
        id: "h0",
        header: "",
        old_start: 10,
        old_lines: 5,
        new_start: 10,
        new_lines: 6,
        // new-file lines:  10      11      (removed)  12      13      14
        lines: [" ctx\n", "+add1\n", "-gone\n", "+add2\n", " ctx\n", " ctx\n"],
      },
    ],
  });
  assert.deepEqual(agentAuthoredLines(fileDiff), [11, 12]);
});

test("a removed line does not advance the new-file cursor", () => {
  const fileDiff = diff({
    hunks: [
      {
        id: "h0",
        header: "",
        old_start: 0,
        old_lines: 3,
        new_start: 0,
        new_lines: 1,
        lines: ["-a\n", "-b\n", "+c\n"],
      },
    ],
  });
  assert.deepEqual(agentAuthoredLines(fileDiff), [0]);
});

test("consecutive lines collapse into ranges", () => {
  assert.deepEqual(toLineRanges([3, 4, 5, 9, 11, 12]), [
    [3, 5],
    [9, 9],
    [11, 12],
  ]);
  assert.deepEqual(toLineRanges([]), []);
  assert.deepEqual(toLineRanges([7, 7, 7]), [[7, 7]]);
});

test("hunk summaries count both sides", () => {
  assert.deepEqual(
    hunkSummary({
      id: "h0",
      header: "",
      old_start: 0,
      old_lines: 0,
      new_start: 0,
      new_lines: 0,
      lines: [" a\n", "+b\n", "+c\n", "-d\n"],
    }),
    { added: 2, removed: 1 },
  );
});
