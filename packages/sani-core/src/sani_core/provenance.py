"""Provenance: git blame for AI.

Which lines did the agent write, which did you, which session, and when. This
is the enterprise question the 2026 agent-observability research keeps raising
-- *what did the agent actually write, and can I audit it* -- and no shipping
IDE answers it.

Recording attribution is easy. Keeping it once a human edits the file
underneath is the hard part, and it is where this could quietly become a liar:
attribution that drifts still *looks* authoritative. So two rules govern this
module:

1. **Survive what can be survived.** A human inserting an import above an
   agent-written function has not un-written that function; the attribution
   moves down rather than evaporating.
2. **Decay rather than pretend.** A range that survived an edit is less certain
   than one never disturbed, and confidence says so. Past a floor the claim is
   dropped entirely, because a guess dressed as a record is worse than a blank.

Attribution is stored per line rather than as ranges. Ranges are more compact
but far harder to remap correctly, and remapping correctness is the whole
feature. Ranges are derived on the way out, for the UI.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Any

#: Multiplier applied to a surviving attribution each time the file is edited
#: around it.
CONFIDENCE_DECAY = 0.92

#: Below this, the record is dropped. Roughly 30 disturbances.
CONFIDENCE_FLOOR = 0.08


@dataclass(slots=True)
class Attribution:
    """Who wrote one line, and how sure we still are."""

    session_id: str
    model: str | None = None
    at: float = 0.0
    confidence: float = 1.0

    def decayed(self) -> "Attribution | None":
        confidence = self.confidence * CONFIDENCE_DECAY
        if confidence < CONFIDENCE_FLOOR:
            return None
        return Attribution(self.session_id, self.model, self.at, round(confidence, 4))

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "model": self.model,
            "at": self.at,
            "confidence": round(self.confidence, 4),
        }


@dataclass(slots=True)
class FileProvenance:
    path: str
    #: Index is the line number. ``None`` means "not agent-authored", which
    #: covers both human-written and never-attributed.
    lines: list[Attribution | None] = field(default_factory=list)

    @property
    def agent_lines(self) -> int:
        return sum(1 for entry in self.lines if entry is not None)

    @property
    def human_lines(self) -> int:
        return len(self.lines) - self.agent_lines

    def _resize(self, total_lines: int) -> None:
        if total_lines > len(self.lines):
            self.lines.extend([None] * (total_lines - len(self.lines)))
        elif total_lines < len(self.lines):
            del self.lines[total_lines:]

    def record_agent_lines(
        self, indices: list[int], attribution: Attribution, *, total_lines: int
    ) -> None:
        """Attribute specific lines to an agent write.

        Only the lines the agent actually touched are marked. Untouched lines
        stay unattributed rather than becoming agent-authored by proximity.
        """
        self._resize(total_lines)
        for index in indices:
            if 0 <= index < len(self.lines):
                self.lines[index] = attribution

    def ranges(self) -> list[dict[str, Any]]:
        """Contiguous same-session runs, for the UI.

        The editor paints ranges, not lines: 400 consecutive entries would be
        400 decorations describing one visual block.
        """
        out: list[dict[str, Any]] = []
        start: int | None = None
        current: Attribution | None = None

        for index, entry in enumerate([*self.lines, None]):
            same = (
                entry is not None
                and current is not None
                and entry.session_id == current.session_id
            )
            if same:
                continue
            if current is not None and start is not None:
                out.append({"start": start, "end": index - 1, **current.to_dict()})
            start = index if entry is not None else None
            current = entry

        return out

    def summary(self) -> dict[str, Any]:
        total = len(self.lines)
        return {
            "path": self.path,
            "total_lines": total,
            "agent_lines": self.agent_lines,
            "human_lines": self.human_lines,
            "agent_pct": round(self.agent_lines / total * 100, 2) if total else 0.0,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.summary(), "ranges": self.ranges()}


def remap_after_edit(
    file: FileProvenance, old_text: str, new_text: str
) -> FileProvenance:
    """Carry attribution across a human edit.

    Uses the same opcode machinery as the diff engine, so "what moved where" is
    answered identically in both places. Equal blocks carry their attribution
    (decayed); replaced and inserted lines become the human's; deleted lines
    take their attribution with them.
    """
    old_lines = old_text.split("\n") if old_text else []
    new_lines = new_text.split("\n") if new_text else []

    remapped: list[Attribution | None] = [None] * len(new_lines)
    unchanged = old_text == new_text

    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            # replace / insert: the human owns these lines now.
            # delete: nothing to carry forward.
            continue
        for offset in range(i2 - i1):
            source = i1 + offset
            target = j1 + offset
            if source >= len(file.lines) or target >= len(remapped):
                continue
            entry = file.lines[source]
            if entry is None:
                continue
            # A file that did not change was not disturbed, so its attribution
            # keeps full confidence. Anything else pays the decay.
            remapped[target] = entry if unchanged else entry.decayed()

    return FileProvenance(path=file.path, lines=remapped)


@dataclass(slots=True)
class WorkspaceProvenance:
    """Attribution for every file in one workspace."""

    files: dict[str, FileProvenance] = field(default_factory=dict)

    def file(self, path: str) -> FileProvenance:
        if path not in self.files:
            self.files[path] = FileProvenance(path=path)
        return self.files[path]

    def summary(self) -> dict[str, Any]:
        total = sum(len(f.lines) for f in self.files.values())
        agent = sum(f.agent_lines for f in self.files.values())
        return {
            "files": len(self.files),
            "total_lines": total,
            "agent_lines": agent,
            "human_lines": total - agent,
            "agent_pct": round(agent / total * 100, 2) if total else 0.0,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.summary(),
            "files": {path: f.to_dict() for path, f in self.files.items()},
        }
