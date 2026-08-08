from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import get_manager
from ..manager import SessionManager
from ..schemas import ApproveRequest, RejectRequest

router = APIRouter(tags=["approvals"])


@router.post("/session/{session_id}/approve")
async def approve(
    session_id: str, body: ApproveRequest, manager: SessionManager = Depends(get_manager)
) -> dict:
    """Approve a pending action, optionally accepting only some of its hunks.

    Returns an acknowledgement, not the post-execution state: the executor
    resumes asynchronously and reports what happened over the stream. Clients
    that need the outcome read ``approval.resolved`` and ``tool.result``.
    """
    return manager.resolve_approval(
        session_id,
        body.action_id,
        approved=True,
        hunk_ids=body.hunk_ids,
        note=body.note,
    )


@router.post("/session/{session_id}/reject")
async def reject(
    session_id: str, body: RejectRequest, manager: SessionManager = Depends(get_manager)
) -> dict:
    """Reject a pending action. The step is skipped and the plan continues."""
    return manager.resolve_approval(
        session_id, body.action_id, approved=False, note=body.reason
    )
