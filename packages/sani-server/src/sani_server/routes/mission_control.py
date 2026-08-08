from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import get_manager
from ..manager import SessionManager

router = APIRouter(tags=["mission-control"])


@router.get("/mission-control")
async def mission_control(manager: SessionManager = Depends(get_manager)) -> dict:
    """One row per session, foreground and background alike (spec Section 5)."""
    return manager.mission_control()
