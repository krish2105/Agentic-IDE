"""The Tool Adapter interface (spec Section 4).

``propose()`` / ``execute()`` / ``result()``. Every tool implements these three
and nothing else, which is what lets the Browser Subagent in Phase 3c be "just
another adapter" rather than a parallel system.

The split is load-bearing: ``propose`` must be side-effect free, because its
output is what the permission engine judges and what the user sees at the
approval prompt. Anything a tool does before ``execute`` has escaped the gate.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from ..actions import ProposedAction, ToolResult
from ..plan import PlanStep


class ToolError(Exception):
    pass


class ToolAdapter(ABC):
    name: str = "tool"

    def __init__(self, workspace: Path) -> None:
        self.workspace = Path(workspace).resolve()

    @abstractmethod
    def propose(self, step: PlanStep) -> ProposedAction:
        """Classify the step into a concrete action. Must not touch anything."""

    @abstractmethod
    async def execute(self, action: ProposedAction, *, hunk_ids: list[str] | None = None) -> Any:
        """Perform the action. Only ever called after the gate has cleared it."""

    @abstractmethod
    def result(self, action: ProposedAction, raw: Any) -> ToolResult:
        """Normalise raw output into the shape clients render."""
