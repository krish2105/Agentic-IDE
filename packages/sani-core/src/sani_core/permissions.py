"""The permission engine.

Section 5 of the build spec defines two tiers:

* an auto-approved-from-session-start tier (low risk, reversible), and
* a fixed always-confirm tier that no trust state can override.

The always-confirm tier is what makes "autonomous-by-default" defensible rather
than reckless, so it is enforced *here*, at a single chokepoint consulted
immediately before execution -- not at plan time, and not in the tool adapters.
No trust setting, no API caller and no adapter can route around it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ActionType(str, Enum):
    FILE_READ = "file.read"
    FILE_WRITE = "file.write"
    FILE_DELETE = "file.delete"
    PATH_OUTSIDE_WORKSPACE = "path.outside_workspace"
    # Spec Section 5 names *writes* to secrets. Widened to cover reads as well:
    # piping a credential file into a model's context is just as irreversible.
    SECRET_ACCESS = "secret.access"
    SHELL_TEST = "shell.test"
    SHELL_NETWORK = "shell.network"
    SHELL_OTHER = "shell.other"
    GIT_COMMIT = "git.commit"
    GIT_HISTORY_REWRITE = "git.history_rewrite"
    DEPENDENCY_LOCKED = "dependency.locked"
    DEPENDENCY_NEW = "dependency.new"


#: Spec Section 5, verbatim: "Always requires explicit confirmation, no
#: exceptions, regardless of trust level." Six action types, one per bullet.
ALWAYS_CONFIRM: frozenset[ActionType] = frozenset(
    {
        ActionType.FILE_DELETE,
        ActionType.GIT_HISTORY_REWRITE,
        ActionType.SHELL_NETWORK,
        ActionType.DEPENDENCY_NEW,
        ActionType.SECRET_ACCESS,
        ActionType.PATH_OUTSIDE_WORKSPACE,
    }
)

#: Spec Section 5: auto-approved from session start.
AUTO_FROM_START: frozenset[ActionType] = frozenset(
    {
        ActionType.FILE_READ,
        ActionType.FILE_WRITE,
        ActionType.SHELL_TEST,
        ActionType.GIT_COMMIT,
        ActionType.DEPENDENCY_LOCKED,
    }
)

#: Consecutive manual approvals of one action type before it earns auto-approval.
TRUST_PROMOTION_THRESHOLD = 3


@dataclass(slots=True)
class TrustTier:
    action_type: ActionType
    auto_approve: bool = False
    consecutive_approvals: int = 0

    @property
    def always_confirm(self) -> bool:
        return self.action_type in ALWAYS_CONFIRM

    def to_dict(self) -> dict:
        return {
            "action_type": self.action_type.value,
            "auto_approve": self.auto_approve and not self.always_confirm,
            "consecutive_approvals": self.consecutive_approvals,
            "always_confirm": self.always_confirm,
            "promotion_threshold": TRUST_PROMOTION_THRESHOLD,
        }


@dataclass(slots=True)
class TrustLadder:
    """Per-session, per-action-type trust state (spec Section 4)."""

    tiers: dict[ActionType, TrustTier] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for action_type in ActionType:
            if action_type not in self.tiers:
                self.tiers[action_type] = TrustTier(
                    action_type=action_type,
                    auto_approve=action_type in AUTO_FROM_START,
                )

    def tier(self, action_type: ActionType) -> TrustTier:
        return self.tiers[action_type]

    def record_manual_approval(self, action_type: ActionType) -> None:
        """A human approved this action type by hand. Climb the ladder."""
        tier = self.tiers[action_type]
        tier.consecutive_approvals += 1
        if (
            tier.consecutive_approvals >= TRUST_PROMOTION_THRESHOLD
            and action_type not in ALWAYS_CONFIRM
        ):
            tier.auto_approve = True

    def record_rejection(self, action_type: ActionType) -> None:
        """A human said no. Reset the streak and revoke earned autonomy."""
        tier = self.tiers[action_type]
        tier.consecutive_approvals = 0
        tier.auto_approve = False

    def set_auto_approve(self, action_type: ActionType, value: bool) -> None:
        """Manual override from ``PATCH /session/{id}/trust``.

        Raises for always-confirm types. The engine ignores the flag for those
        regardless, but failing loudly here stops a client from believing it
        turned something on that it did not.
        """
        if action_type in ALWAYS_CONFIRM and value:
            raise PermissionLocked(action_type)
        tier = self.tiers[action_type]
        tier.auto_approve = value
        if not value:
            tier.consecutive_approvals = 0

    def to_dict(self) -> dict[str, dict]:
        return {a.value: t.to_dict() for a, t in self.tiers.items()}

    @classmethod
    def from_dict(cls, data: dict[str, dict]) -> "TrustLadder":
        """Rebuild a ladder from a snapshot.

        Deliberately re-derives ``auto_approve`` through the always-confirm
        check rather than trusting the stored flag: a snapshot is untrusted
        input once it has been through Redis, and this is the one place a
        corrupted record could otherwise widen the safety tier.
        """
        ladder = cls()
        for raw_type, tier_state in (data or {}).items():
            try:
                action_type = ActionType(raw_type)
            except ValueError:
                continue
            tier = ladder.tiers[action_type]
            tier.consecutive_approvals = int(tier_state.get("consecutive_approvals", 0))
            tier.auto_approve = bool(tier_state.get("auto_approve", False)) and (
                action_type not in ALWAYS_CONFIRM
            )
        return ladder


class PermissionLocked(Exception):
    """Raised when a caller tries to auto-approve an always-confirm action."""

    def __init__(self, action_type: ActionType) -> None:
        self.action_type = action_type
        super().__init__(
            f"{action_type.value} is in the fixed always-confirm tier and "
            "cannot be auto-approved at any trust level"
        )


@dataclass(slots=True)
class Decision:
    requires_approval: bool
    reason: str
    action_type: ActionType

    def to_dict(self) -> dict:
        return {
            "requires_approval": self.requires_approval,
            "reason": self.reason,
            "action_type": self.action_type.value,
        }


def evaluate(action_type: ActionType, ladder: TrustLadder) -> Decision:
    """The single chokepoint. Every action passes through here before it runs.

    Order matters: the always-confirm check happens before the ladder is even
    consulted, so a corrupted or maliciously-set ladder cannot unlock it.
    """
    if action_type in ALWAYS_CONFIRM:
        return Decision(
            requires_approval=True,
            reason="always-confirm tier: irreversible or high-blast-radius action",
            action_type=action_type,
        )

    tier = ladder.tier(action_type)
    if tier.auto_approve:
        return Decision(
            requires_approval=False,
            reason="auto-approved by trust tier",
            action_type=action_type,
        )

    return Decision(
        requires_approval=True,
        reason=(
            f"trust not yet earned "
            f"({tier.consecutive_approvals}/{TRUST_PROMOTION_THRESHOLD} approvals)"
        ),
        action_type=action_type,
    )
