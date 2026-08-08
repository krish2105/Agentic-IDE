"""Sani' agent engine.

Transport-agnostic by design: nothing in this package imports a web framework,
so the same core backs the FastAPI server, a CLI, and the test harness.
"""

from __future__ import annotations

from .actions import ProposedAction, ToolResult
from .approvals import AlreadyResolved, ApprovalOutcome, ApprovalRegistry, UnknownAction
from .context import ContextWindow
from .diffs import FileDiff, Hunk, apply_hunks, compute_diff
from .events import PROTOCOL_VERSION, Event, EventType
from .executor import Executor
from .permissions import (
    ALWAYS_CONFIRM,
    AUTO_FROM_START,
    ActionType,
    Decision,
    PermissionLocked,
    TrustLadder,
    evaluate,
)
from .plan import Plan, PlanStep, StepStatus
from .session import AgentSession, Lifecycle, SessionStatus
from .tools import build_tools

__version__ = "0.1.0"

__all__ = [
    "ALWAYS_CONFIRM",
    "AUTO_FROM_START",
    "PROTOCOL_VERSION",
    "ActionType",
    "AgentSession",
    "AlreadyResolved",
    "ApprovalOutcome",
    "ApprovalRegistry",
    "ContextWindow",
    "Decision",
    "Event",
    "EventType",
    "Executor",
    "FileDiff",
    "Hunk",
    "Lifecycle",
    "PermissionLocked",
    "Plan",
    "PlanStep",
    "ProposedAction",
    "SessionStatus",
    "StepStatus",
    "ToolResult",
    "TrustLadder",
    "UnknownAction",
    "__version__",
    "apply_hunks",
    "build_tools",
    "compute_diff",
    "evaluate",
]
