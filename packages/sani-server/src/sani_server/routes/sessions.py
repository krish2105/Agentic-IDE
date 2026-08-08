from __future__ import annotations

from fastapi import APIRouter, Depends, status

from ..deps import get_manager
from ..manager import SessionManager
from ..schemas import CreateSessionRequest

router = APIRouter(tags=["sessions"])


@router.post("/session", status_code=status.HTTP_201_CREATED)
async def create_session(
    body: CreateSessionRequest, manager: SessionManager = Depends(get_manager)
) -> dict:
    """Create an Agent Session and start it.

    Returns immediately: planning happens on a detached task and is reported
    over ``/session/{id}/stream``. Connecting late is safe -- the stream replays
    from the beginning by default.
    """
    record = manager.create(
        task=body.task,
        workspace=body.workspace,
        tools=body.tools,
        lifecycle=body.lifecycle,
        script=body.script,
        model_backend=body.model_backend,
        trust_overrides=body.trust_overrides,
    )
    return record.session.to_dict()


@router.get("/session/{session_id}")
async def get_session(session_id: str, manager: SessionManager = Depends(get_manager)) -> dict:
    """Session status, current plan and trust tier state."""
    record = manager.get(session_id)
    return record.session.to_dict()
