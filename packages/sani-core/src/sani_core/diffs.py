"""Diff generation and per-hunk application.

Hunks come from ``SequenceMatcher.get_grouped_opcodes``, which produces exactly
the groupings a unified diff would show. Working from opcodes rather than
parsing diff text means per-hunk accept/reject (spec Section 5) can be applied
exactly, with no patch-fuzzing.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Any

CONTEXT_LINES = 3


@dataclass(slots=True)
class Hunk:
    id: str
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    lines: list[str] = field(default_factory=list)

    @property
    def header(self) -> str:
        return (
            f"@@ -{self.old_start + 1},{self.old_lines} "
            f"+{self.new_start + 1},{self.new_lines} @@"
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Hunk":
        return cls(
            id=data["id"],
            old_start=data["old_start"],
            old_lines=data["old_lines"],
            new_start=data["new_start"],
            new_lines=data["new_lines"],
            lines=list(data.get("lines", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "header": self.header,
            "old_start": self.old_start,
            "old_lines": self.old_lines,
            "new_start": self.new_start,
            "new_lines": self.new_lines,
            "lines": self.lines,
        }


@dataclass(slots=True)
class FileDiff:
    path: str
    hunks: list[Hunk] = field(default_factory=list)
    unified: str = ""
    is_new_file: bool = False
    is_delete: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FileDiff":
        return cls(
            path=data["path"],
            hunks=[Hunk.from_dict(h) for h in data.get("hunks", [])],
            unified=data.get("unified", ""),
            is_new_file=data.get("is_new_file", False),
            is_delete=data.get("is_delete", False),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "unified": self.unified,
            "is_new_file": self.is_new_file,
            "is_delete": self.is_delete,
            "hunks": [h.to_dict() for h in self.hunks],
        }


def _split_lines(text: str) -> list[str]:
    if text == "":
        return []
    return text.splitlines(keepends=True)


def _grouped_opcodes(old: list[str], new: list[str]) -> list[list[tuple]]:
    matcher = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
    return list(matcher.get_grouped_opcodes(CONTEXT_LINES))


def compute_diff(path: str, old_text: str, new_text: str, *, is_delete: bool = False) -> FileDiff:
    old = _split_lines(old_text)
    new = _split_lines(new_text)

    hunks: list[Hunk] = []
    for i, group in enumerate(_grouped_opcodes(old, new)):
        lines: list[str] = []
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                lines.extend(f" {line}" for line in old[i1:i2])
            else:
                lines.extend(f"-{line}" for line in old[i1:i2])
                lines.extend(f"+{line}" for line in new[j1:j2])
        old_start, old_end = group[0][1], group[-1][2]
        new_start, new_end = group[0][3], group[-1][4]
        hunks.append(
            Hunk(
                id=f"h{i}",
                old_start=old_start,
                old_lines=old_end - old_start,
                new_start=new_start,
                new_lines=new_end - new_start,
                lines=lines,
            )
        )

    unified = "".join(
        difflib.unified_diff(old, new, fromfile=f"a/{path}", tofile=f"b/{path}", n=CONTEXT_LINES)
    )
    return FileDiff(
        path=path,
        hunks=hunks,
        unified=unified,
        is_new_file=old_text == "" and not is_delete,
        is_delete=is_delete,
    )


def apply_hunks(old_text: str, new_text: str, selected_ids: list[str] | None) -> str:
    """Rebuild file content with only ``selected_ids`` applied.

    ``None`` means "all hunks" -- the common full-accept path. An empty list
    means the user rejected every hunk, which yields the original content.
    """
    if selected_ids is None:
        return new_text

    old = _split_lines(old_text)
    new = _split_lines(new_text)
    selected = set(selected_ids)

    out: list[str] = []
    cursor = 0
    for i, group in enumerate(_grouped_opcodes(old, new)):
        g_old_start, g_old_end = group[0][1], group[-1][2]
        out.extend(old[cursor:g_old_start])
        if f"h{i}" in selected:
            for tag, i1, i2, j1, j2 in group:
                out.extend(old[i1:i2] if tag == "equal" else new[j1:j2])
        else:
            out.extend(old[g_old_start:g_old_end])
        cursor = g_old_end
    out.extend(old[cursor:])
    return "".join(out)
