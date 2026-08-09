"""GET /session/{id}/timeline -- replay.

Reads the same per-session log the WebSocket replays from, so the scrubber and
a reconnecting stream can never disagree about what happened. The keyframes are
computed in ``sani_core.replay`` rather than here, and certainly not in a
client: two surfaces deriving "what mattered in this run" independently is two
chances to derive it differently.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sani_core.replay import build_timeline

from ..deps import get_manager
from ..manager import SessionManager

router = APIRouter(tags=["timeline"])


@router.get("/session/{session_id}/timeline")
async def get_timeline(
    session_id: str,
    from_seq: int = Query(
        0, ge=0, description="Return only events after this seq. 0 returns the whole run."
    ),
    manager: SessionManager = Depends(get_manager),
) -> dict:
    record = manager.get(session_id)
    hub = record.hub

    window = hub.backlog(from_seq)
    timeline = build_timeline(session_id, window)

    # `last_seq` must describe the session, not the window. A client that
    # deep-linked to ?seq=N still needs to know how long the whole run is, or
    # the scrubber renders a track that stops short of the end.
    timeline["last_seq"] = hub.last_seq
    timeline["from_seq"] = from_seq
    timeline["complete"] = hub.closed

    return timeline
