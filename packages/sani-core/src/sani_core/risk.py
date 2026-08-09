"""Blast-radius assessment: what an action reaches, before it runs.

The documented failure mode in 2026 agentic coding is not obviously-bad output.
It is output that *looks* right, arriving through an approval flow that shows a
diff and asks "ok?" without ever stating what the action actually touches or
how hard it is to undo. Approving becomes a reflex, and the gate becomes
theatre.

So the gate gets an answer computed before execution: what is reached, how much
changes, and whether it can be taken back.

Three constraints shape this module:

1. **It runs on the proposal only.** ``propose()`` is side-effect free and must
   stay that way, so nothing here executes, fetches, or mutates anything. Every
   input is already on the ``ProposedAction``.
2. **It is advisory.** A score never widens the always-confirm tier, never
   auto-approves, and never gates anything by itself. ``permissions.evaluate()``
   remains the only chokepoint.
3. **It explains itself.** A bare number is something to click past. The factors
   are the feature; the score is only their summary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .actions import ProposedAction
from .permissions import ALWAYS_CONFIRM, ActionType

Band = Literal["low", "medium", "high", "critical"]

#: Actions whose effect cannot be undone from inside the product. A write is
#: recoverable -- the previous content is in the diff and in git. A delete, a
#: history rewrite, a network call that already left the building, and a secret
#: that has already entered a model's context are not.
IRREVERSIBLE: frozenset[ActionType] = frozenset(
    {
        ActionType.FILE_DELETE,
        ActionType.GIT_HISTORY_REWRITE,
        ActionType.SHELL_NETWORK,
        ActionType.SECRET_ACCESS,
        ActionType.BROWSER_NAVIGATE_EXTERNAL,
    }
)

#: Starting point per action type, before magnitude is considered. The
#: always-confirm tier begins high on purpose: a tier the spec says has no
#: exceptions must never render as routine.
BASE_SCORE: dict[ActionType, int] = {
    ActionType.FILE_READ: 5,
    ActionType.FILE_WRITE: 20,
    ActionType.FILE_DELETE: 75,
    ActionType.SHELL_TEST: 15,
    ActionType.SHELL_OTHER: 35,
    ActionType.SHELL_NETWORK: 70,
    ActionType.GIT_COMMIT: 20,
    ActionType.GIT_HISTORY_REWRITE: 85,
    ActionType.DEPENDENCY_LOCKED: 25,
    ActionType.DEPENDENCY_NEW: 60,
    ActionType.SECRET_ACCESS: 80,
    ActionType.PATH_OUTSIDE_WORKSPACE: 75,
    ActionType.BROWSER_ACTION: 25,
    ActionType.BROWSER_NAVIGATE_EXTERNAL: 60,
}

DEFAULT_BASE = 30

#: Floor for anything in the always-confirm tier, whatever its size.
ALWAYS_CONFIRM_FLOOR = 50


@dataclass(slots=True)
class RiskAssessment:
    score: int = 0
    reversible: bool = True
    always_confirm: bool = False
    reaches_network: bool = False
    leaves_workspace: bool = False
    lines_changed: int = 0
    files_touched: int = 0
    factors: list[str] = field(default_factory=list)

    @property
    def band(self) -> Band:
        if self.score >= 75:
            return "critical"
        if self.score >= 50:
            return "high"
        if self.score >= 25:
            return "medium"
        return "low"

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "band": self.band,
            "reversible": self.reversible,
            "always_confirm": self.always_confirm,
            "reaches_network": self.reaches_network,
            "leaves_workspace": self.leaves_workspace,
            "lines_changed": self.lines_changed,
            "files_touched": self.files_touched,
            "factors": list(self.factors),
        }


def _magnitude_penalty(lines: int) -> int:
    """How much the size of a change adds.

    Deliberately sublinear and capped: the difference between 10 and 300 changed
    lines matters a great deal, the difference between 3,000 and 6,000 barely
    does -- past a point nobody is reading it either way.
    """
    if lines <= 0:
        return 0
    if lines < 20:
        return 3
    if lines < 100:
        return 8
    if lines < 400:
        return 15
    return 22


def assess(action: ProposedAction) -> RiskAssessment:
    """Score one proposed action. Pure: no I/O, no execution, no mutation."""
    action_type = action.action_type
    factors: list[str] = []

    score = BASE_SCORE.get(action_type, DEFAULT_BASE)
    always_confirm = action_type in ALWAYS_CONFIRM
    reversible = action_type not in IRREVERSIBLE

    if always_confirm:
        factors.append(
            "In the always-confirm tier — this cannot be auto-approved at any trust level"
        )

    if not reversible:
        factors.append("Cannot be undone from inside Ṣāni'")

    reaches_network = action_type in (
        ActionType.SHELL_NETWORK,
        ActionType.DEPENDENCY_NEW,
        ActionType.BROWSER_NAVIGATE_EXTERNAL,
    )
    if reaches_network:
        factors.append("Reaches the network — effects can leave this machine")

    leaves_workspace = action_type is ActionType.PATH_OUTSIDE_WORKSPACE
    if leaves_workspace:
        factors.append("Touches a path outside the session workspace")

    if action_type is ActionType.SECRET_ACCESS:
        factors.append(
            "Reads a secret — credentials would enter the model's context and cannot be taken back"
        )

    # Magnitude, from the diff already attached to the proposal.
    additions = action.diff.additions if action.diff else 0
    deletions = action.diff.deletions if action.diff else 0
    lines_changed = additions + deletions
    files_touched = 1 if action.diff else 0

    if lines_changed:
        score += _magnitude_penalty(lines_changed)
        # Removing code weighs more than adding it: deleting something you did
        # not read is a worse failure than adding something you can read.
        score += _magnitude_penalty(deletions) // 2
        plural = "" if files_touched == 1 else "s"
        factors.append(
            f"{additions} added / {deletions} removed across {files_touched} file{plural}"
        )

    # Where a shell command lands is part of the decision, not a detail.
    runs_in = (action.preview or {}).get("runs_in") or {}
    if runs_in and not runs_in.get("isolated", False):
        score += 10
        factors.append("Runs directly on this machine, not in a sandbox")
    elif runs_in.get("isolated"):
        factors.append("Runs inside the session sandbox")

    if always_confirm:
        score = max(score, ALWAYS_CONFIRM_FLOOR)

    score = max(0, min(100, score))

    if not factors:
        factors.append("Routine action within the workspace")

    return RiskAssessment(
        score=score,
        reversible=reversible,
        always_confirm=always_confirm,
        reaches_network=reaches_network,
        leaves_workspace=leaves_workspace,
        lines_changed=lines_changed,
        files_touched=files_touched,
        factors=factors,
    )
