from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import get_manager
from ..manager import SessionManager
from ..schemas import TrustPatchRequest

router = APIRouter(tags=["trust"])


@router.get("/session/{session_id}/trust")
async def get_trust(session_id: str, manager: SessionManager = Depends(get_manager)) -> dict:
    """Trust tier state per action type, including which tiers are locked."""
    return manager.trust(session_id)


@router.patch("/session/{session_id}/trust")
async def patch_trust(
    session_id: str, body: TrustPatchRequest, manager: SessionManager = Depends(get_manager)
) -> dict:
    """Manually toggle auto-approval for one action type.

    Rejects with 400 for always-confirm action types. The permission engine
    ignores the flag for those regardless, but failing loudly here stops a
    client from believing it enabled something it did not.
    """
    return manager.set_trust(session_id, body.action_type, body.auto_approve)
