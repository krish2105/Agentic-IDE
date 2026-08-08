"""WebSocket bridge between xterm.js and the session sandbox.

Separate from the agent's shell tool on purpose: this is the human's terminal.
Nothing typed here passes through the permission engine, because gating a
person's own shell would be theatre -- they can already run anything the server
user can. The agent's commands are the ones that get judged.

Frames are JSON both ways:
    client -> {"type": "input",  "data": "ls\\r"}
              {"type": "resize", "cols": 120, "rows": 30}
    server -> {"type": "ready",  "sandbox": {...}}
              {"type": "output", "data": "..."}
              {"type": "exit"}
"""

from __future__ import annotations

import asyncio
import codecs

from fastapi import APIRouter, Query, WebSocket
from starlette.websockets import WebSocketDisconnect

from ..sandbox import SandboxError
from ..stores import UnknownSession

router = APIRouter()

WS_UNKNOWN_SESSION = 4404
WS_SANDBOX_FAILED = 1011

MAX_COLS = 500
MAX_ROWS = 200


@router.websocket("/session/{session_id}/terminal")
async def terminal(
    websocket: WebSocket,
    session_id: str,
    cols: int = Query(80, ge=1, le=MAX_COLS),
    rows: int = Query(24, ge=1, le=MAX_ROWS),
) -> None:
    manager = websocket.app.state.manager
    try:
        record = manager.get(session_id)
    except UnknownSession:
        await websocket.close(code=WS_UNKNOWN_SESSION, reason="unknown session")
        return

    await websocket.accept()

    try:
        session_terminal = await record.sandbox.open_terminal(cols=cols, rows=rows)
    except SandboxError as exc:
        await websocket.send_json({"type": "error", "data": str(exc)})
        await websocket.close(code=WS_SANDBOX_FAILED)
        return

    await websocket.send_json({"type": "ready", "sandbox": record.sandbox.describe()})

    async def pump_output() -> None:
        # A PTY read can split a multi-byte character across chunks, so decode
        # incrementally rather than per-chunk.
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        while True:
            chunk = await session_terminal.read()
            if not chunk:
                await websocket.send_json({"type": "exit"})
                return
            await websocket.send_json({"type": "output", "data": decoder.decode(chunk)})

    async def pump_input() -> None:
        while True:
            message = await websocket.receive_json()
            kind = message.get("type")
            if kind == "input":
                await session_terminal.write(message.get("data", "").encode())
            elif kind == "resize":
                session_terminal.resize(
                    min(int(message.get("cols", cols)), MAX_COLS),
                    min(int(message.get("rows", rows)), MAX_ROWS),
                )

    output_task = asyncio.create_task(pump_output())
    input_task = asyncio.create_task(pump_input())
    try:
        await asyncio.wait({output_task, input_task}, return_when=asyncio.FIRST_COMPLETED)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        for task in (output_task, input_task):
            task.cancel()
        await asyncio.gather(output_task, input_task, return_exceptions=True)
        await session_terminal.close()

    try:
        await websocket.close(code=1000)
    except RuntimeError:
        pass
