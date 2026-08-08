"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sani_core import PROTOCOL_VERSION, __version__
from sani_core.approvals import AlreadyResolved, UnknownAction
from sani_core.events import EventType
from sani_core.permissions import ALWAYS_CONFIRM, PermissionLocked
from sani_core.tools import ToolError

from .manager import InvalidState, InvalidWorkspace, SessionManager
from .routes import ROUTERS
from .routes.workspace import FileOutsideWorkspace
from .sandbox import SandboxError
from .stores import UnknownSession

#: The server has no auth and the shell adapter executes commands, so the
#: default origins are local development only. Do not widen this without adding
#: auth. ``SANI_CORS_ORIGINS`` takes a comma-separated list for a non-default
#: dev port; "*" is deliberately not special-cased.
DEFAULT_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]
CORS_ORIGINS_ENV_VAR = "SANI_CORS_ORIGINS"


def allowed_origins() -> list[str]:
    configured = os.environ.get(CORS_ORIGINS_ENV_VAR)
    if not configured:
        return DEFAULT_ORIGINS
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # Stop detached executors so uvicorn's shutdown is not held open by a
    # session parked on an approval nobody is going to give.
    for record in app.state.manager.list():
        if record.task and not record.task.done():
            record.executor.kill()
            record.task.cancel()
            await asyncio.gather(record.task, return_exceptions=True)
        await record.sandbox.shutdown()


def create_app(manager: SessionManager | None = None) -> FastAPI:
    app = FastAPI(
        title="Sani' Studio Server",
        version=__version__,
        summary="Agent session management, WebSocket streaming and approval gating",
        lifespan=lifespan,
    )
    app.state.manager = manager or SessionManager()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for router in ROUTERS:
        app.include_router(router)

    def _error(status_code: int, error: str, detail: str) -> JSONResponse:
        return JSONResponse(status_code=status_code, content={"error": error, "detail": detail})

    @app.exception_handler(UnknownSession)
    async def _unknown_session(request: Request, exc: UnknownSession):
        return _error(404, "unknown_session", f"no session {exc.args[0]!r}")

    @app.exception_handler(UnknownAction)
    async def _unknown_action(request: Request, exc: UnknownAction):
        return _error(404, "unknown_action", f"no pending action {exc.args[0]!r}")

    @app.exception_handler(AlreadyResolved)
    async def _already_resolved(request: Request, exc: AlreadyResolved):
        return _error(409, "already_resolved", f"action {exc.args[0]!r} was already decided")

    @app.exception_handler(InvalidWorkspace)
    async def _invalid_workspace(request: Request, exc: InvalidWorkspace):
        return _error(400, "invalid_workspace", str(exc))

    @app.exception_handler(InvalidState)
    async def _invalid_state(request: Request, exc: InvalidState):
        return _error(409, "invalid_state", str(exc))

    @app.exception_handler(PermissionLocked)
    async def _permission_locked(request: Request, exc: PermissionLocked):
        return _error(400, "permission_locked", str(exc))

    @app.exception_handler(ToolError)
    async def _tool_error(request: Request, exc: ToolError):
        return _error(400, "tool_error", str(exc))

    @app.exception_handler(FileOutsideWorkspace)
    async def _outside_workspace(request: Request, exc: FileOutsideWorkspace):
        return _error(403, "outside_workspace", str(exc))

    @app.exception_handler(SandboxError)
    async def _sandbox_error(request: Request, exc: SandboxError):
        return _error(500, "sandbox_error", str(exc))

    @app.get("/healthz", tags=["meta"])
    async def healthz() -> dict:
        return {
            "ok": True,
            "version": __version__,
            "protocol_version": PROTOCOL_VERSION,
            "event_types": [e.value for e in EventType],
            "always_confirm": sorted(a.value for a in ALWAYS_CONFIRM),
        }

    return app


app = create_app()
