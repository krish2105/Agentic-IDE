"""Pending-approval registry.

When the permission engine blocks an action, the executor parks on a future
registered here. ``POST /session/{id}/approve`` (or ``/reject``) resolves it.
There is deliberately no timeout: a blocked session stays blocked until a human
decides. Auto-failing an approval after a delay would silently convert
"nobody looked at it" into "it was denied", which is a worse default for a tool
that is allowed to delete files.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from .actions import ProposedAction


class UnknownAction(KeyError):
    pass


class AlreadyResolved(Exception):
    pass


@dataclass(slots=True)
class ApprovalOutcome:
    approved: bool
    hunk_ids: list[str] | None = None
    note: str | None = None
    auto: bool = False

    def to_dict(self) -> dict:
        return {
            "approved": self.approved,
            "hunk_ids": self.hunk_ids,
            "note": self.note,
            "auto": self.auto,
        }


@dataclass(slots=True)
class PendingApproval:
    action: ProposedAction
    future: asyncio.Future[ApprovalOutcome]


@dataclass
class ApprovalRegistry:
    _pending: dict[str, PendingApproval] = field(default_factory=dict)

    def create(self, action: ProposedAction) -> PendingApproval:
        loop = asyncio.get_running_loop()
        pending = PendingApproval(action=action, future=loop.create_future())
        self._pending[action.id] = pending
        return pending

    def get(self, action_id: str) -> PendingApproval:
        try:
            return self._pending[action_id]
        except KeyError as exc:
            raise UnknownAction(action_id) from exc

    @property
    def outstanding(self) -> ProposedAction | None:
        for pending in self._pending.values():
            if not pending.future.done():
                return pending.action
        return None

    def resolve(
        self,
        action_id: str,
        *,
        approved: bool,
        hunk_ids: list[str] | None = None,
        note: str | None = None,
    ) -> ApprovalOutcome:
        pending = self.get(action_id)
        if pending.future.done():
            raise AlreadyResolved(action_id)
        outcome = ApprovalOutcome(approved=approved, hunk_ids=hunk_ids, note=note)
        pending.future.set_result(outcome)
        return outcome

    def abandon_all(self) -> None:
        """Release every parked waiter as rejected. Used when a session is killed."""
        for pending in self._pending.values():
            if not pending.future.done():
                pending.future.set_result(
                    ApprovalOutcome(approved=False, note="session terminated")
                )
