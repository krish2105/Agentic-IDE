from __future__ import annotations

from fastapi import Request, WebSocket

from .manager import SessionManager


def get_manager(request: Request) -> SessionManager:
    return request.app.state.manager


def get_manager_ws(websocket: WebSocket) -> SessionManager:
    return websocket.app.state.manager
