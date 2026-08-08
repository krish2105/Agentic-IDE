from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import get_manager
from ..manager import SessionManager

router = APIRouter(tags=["lifecycle"])


@router.post("/session/{session_id}/pause")
async def pause(session_id: str, manager: SessionManager = Depends(get_manager)) -> dict:
    """Request a pause.

    Takes effect at the next step boundary -- a tool call already running is
    allowed to finish rather than being interrupted mid-write. Watch for
    ``session.status`` with ``paused`` to know it landed.
    """
    record = manager.pause(session_id)
    return {"session_id": session_id, "pause_requested": True,
            "status": record.session.status.value}


@router.post("/session/{session_id}/resume")
async def resume(session_id: str, manager: SessionManager = Depends(get_manager)) -> dict:
    record = manager.resume(session_id)
    return {"session_id": session_id, "pause_requested": False,
            "status": record.session.status.value}


@router.post("/session/{session_id}/kill")
async def kill(session_id: str, manager: SessionManager = Depends(get_manager)) -> dict:
    """Terminate the session. Any parked approval resolves as rejected."""
    record = await manager.kill(session_id)
    return record.session.to_dict()
