"""Concrete actions and their results.

A ``PlanStep`` is intent; a ``ProposedAction`` is the specific, classified thing
about to happen. The split exists so the permission engine has something exact
to judge, and so the client can show the user a preview at the decision point
rather than a vague description.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from .diffs import FileDiff
from .permissions import ActionType


def new_action_id() -> str:
    return f"act_{uuid.uuid4().hex[:12]}"


@dataclass(slots=True)
class ProposedAction:
    action_type: ActionType
    tool: str
    summary: str
    step_index: int
    payload: dict[str, Any] = field(default_factory=dict)
    #: Human-facing preview shown at the approval prompt: a diff, a command
    #: line, a target path. Never contains anything the client must interpret.
    preview: dict[str, Any] = field(default_factory=dict)
    diff: FileDiff | None = None
    id: str = field(default_factory=new_action_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "action_type": self.action_type.value,
            "tool": self.tool,
            "summary": self.summary,
            "step_index": self.step_index,
            "preview": self.preview,
            "diff": self.diff.to_dict() if self.diff else None,
        }


@dataclass(slots=True)
class ToolResult:
    ok: bool
    summary: str
    output: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    diff: FileDiff | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "summary": self.summary,
            "output": self.output,
            "data": self.data,
            "diff": self.diff.to_dict() if self.diff else None,
        }
