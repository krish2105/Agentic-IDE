"""The Agent Session -- the atomic unit of the whole system (spec Section 4).

A session is the same object whether it runs foreground or background, and
whether its tool adapter writes files, runs a shell, or (in Phase 3c) drives a
headless browser. That is the primitive the three "stretch" features collapse
into, so it holds state and nothing else: no transport, no execution logic.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .actions import ProposedAction
from .context import ContextWindow
from .diffs import FileDiff
from .permissions import TrustLadder
from .plan import Plan


class SessionStatus(str, Enum):
    PLANNING = "planning"
    EXECUTING = "executing"
    BLOCKED_ON_APPROVAL = "blocked-on-approval"
    PAUSED = "paused"
    COMPLETE = "complete"
    FAILED = "failed"
    KILLED = "killed"


TERMINAL_STATUSES = frozenset(
    {SessionStatus.COMPLETE, SessionStatus.FAILED, SessionStatus.KILLED}
)


class Lifecycle(str, Enum):
    FOREGROUND = "foreground"
    BACKGROUND = "background"


def new_session_id() -> str:
    return f"ses_{uuid.uuid4().hex[:12]}"


@dataclass
class AgentSession:
    task: str
    workspace: Path
    id: str = field(default_factory=new_session_id)
    lifecycle: Lifecycle = Lifecycle.FOREGROUND
    status: SessionStatus = SessionStatus.PLANNING
    tools: list[str] = field(default_factory=lambda: ["file_editor", "shell"])
    plan: Plan | None = None
    history: list[dict] = field(default_factory=list)
    trust: TrustLadder = field(default_factory=TrustLadder)
    context: ContextWindow = field(default_factory=ContextWindow)
    #: Keyed by path so a file edited twice shows one cumulative diff.
    diffs: dict[str, FileDiff] = field(default_factory=dict)
    pending_action: ProposedAction | None = None
    current_step: int | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    ended_at: float | None = None

    @property
    def elapsed_s(self) -> float:
        return round((self.ended_at or time.time()) - self.created_at, 3)

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @property
    def active_tool(self) -> str | None:
        if self.plan and self.current_step is not None:
            if 0 <= self.current_step < len(self.plan.steps):
                return self.plan.steps[self.current_step].tool
        return None

    def record_diff(self, diff: FileDiff) -> None:
        self.diffs[diff.path] = diff

    def to_dict(self) -> dict:
        return {
            "session_id": self.id,
            "task": self.task,
            "workspace": str(self.workspace),
            "lifecycle": self.lifecycle.value,
            "status": self.status.value,
            "tools": self.tools,
            "plan": self.plan.to_dict() if self.plan else None,
            "current_step": self.current_step,
            "active_tool": self.active_tool,
            "pending_action": self.pending_action.to_dict() if self.pending_action else None,
            "trust": self.trust.to_dict(),
            "context": self.context.to_dict(),
            "diffs": [d.to_dict() for d in self.diffs.values()],
            "error": self.error,
            "created_at": self.created_at,
            "ended_at": self.ended_at,
            "elapsed_s": self.elapsed_s,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgentSession":
        """Rebuild a session from an archived snapshot (Phase 3b).

        The pending action is deliberately not restored: it referenced a future
        in a process that no longer exists, so presenting it as still awaiting
        a decision would offer the user a button that cannot work.
        """
        session = cls(
            task=data["task"],
            workspace=Path(data["workspace"]),
            id=data["session_id"],
            lifecycle=Lifecycle(data.get("lifecycle", "foreground")),
            status=SessionStatus(data.get("status", "planning")),
            tools=list(data.get("tools", [])),
            trust=TrustLadder.from_dict(data.get("trust", {})),
            context=ContextWindow.from_dict(data.get("context", {})),
            current_step=data.get("current_step"),
            error=data.get("error"),
            created_at=data.get("created_at", time.time()),
            ended_at=data.get("ended_at"),
        )
        if data.get("plan"):
            session.plan = Plan.from_dict(data["plan"])
        for diff in data.get("diffs", []):
            session.record_diff(FileDiff.from_dict(diff))
        return session

    def to_mission_control_row(self) -> dict:
        """The one-row-per-session shape the dashboard renders (spec Section 5)."""
        step_desc = None
        if self.plan and self.current_step is not None:
            if 0 <= self.current_step < len(self.plan.steps):
                step_desc = self.plan.steps[self.current_step].description
        return {
            "session_id": self.id,
            "task": self.task,
            "status": self.status.value,
            "lifecycle": self.lifecycle.value,
            "current_step": self.current_step,
            "current_step_description": step_desc,
            "total_steps": len(self.plan.steps) if self.plan else 0,
            "elapsed_s": self.elapsed_s,
            "active_tool": self.active_tool,
            "approval_needed": self.status is SessionStatus.BLOCKED_ON_APPROVAL,
            "pending_action": self.pending_action.to_dict() if self.pending_action else None,
        }
