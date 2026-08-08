"""The WebSocket stream.

Broadcast-only by design. Approvals travel over HTTP (``POST /approve``), never
over this socket, so a dropped or duplicated client connection can never strand
a pending action or double-resolve one. The socket carries truth outward; it
accepts nothing inward.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query, WebSocket
from starlette.websockets import WebSocketDisconnect

from ..hub import CLOSED
from ..stores import UnknownSession

router = APIRouter()

WS_UNKNOWN_SESSION = 4404


async def _watch_for_disconnect(websocket: WebSocket) -> None:
    """Resolve as soon as the client goes away.

    A send-only loop would not notice a disconnect until its next write, which
    for a session parked on an approval could be never.
    """
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
    except (WebSocketDisconnect, RuntimeError):
        return


@router.websocket("/session/{session_id}/stream")
async def stream_session(
    websocket: WebSocket,
    session_id: str,
    from_seq: int = Query(0, ge=0, description="Replay events after this seq. 0 replays all."),
) -> None:
    manager = websocket.app.state.manager
    try:
        record = manager.get(session_id)
    except UnknownSession:
        await websocket.close(code=WS_UNKNOWN_SESSION, reason="unknown session")
        return

    await websocket.accept()
    hub = record.hub

    with hub.subscribe() as queue:
        # Subscribing before snapshotting the backlog means no event can slip
        # between the two. Anything that arrives during the replay is already
        # queued, and last_sent filters the overlap.
        last_sent = from_seq
        try:
            for payload in hub.backlog(from_seq):
                await websocket.send_json(payload)
                last_sent = payload["seq"]
        except (WebSocketDisconnect, RuntimeError):
            return

        disconnect_watch = asyncio.create_task(_watch_for_disconnect(websocket))
        try:
            while True:
                getter = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait(
                    {getter, disconnect_watch}, return_when=asyncio.FIRST_COMPLETED
                )
                if disconnect_watch in done:
                    getter.cancel()
                    return

                payload = getter.result()
                if payload is CLOSED:
                    break
                if payload["seq"] <= last_sent:
                    continue
                await websocket.send_json(payload)
                last_sent = payload["seq"]
        except (WebSocketDisconnect, RuntimeError):
            return
        finally:
            disconnect_watch.cancel()

    try:
        await websocket.close(code=1000)
    except RuntimeError:
        pass
