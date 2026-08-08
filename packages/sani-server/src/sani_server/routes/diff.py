from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import get_manager
from ..manager import SessionManager

router = APIRouter(tags=["diff"])


@router.get("/session/{session_id}/diff")
async def get_diff(session_id: str, manager: SessionManager = Depends(get_manager)) -> dict:
    """Full diff for the session, one entry per file, split into hunks."""
    return manager.diff(session_id)
