"""Session Manager -- create, inspect and control Agent Sessions.

Single source of truth for session state (spec Section 2). Routes are thin
translations of these methods into HTTP; no business logic lives above this
layer, which is what keeps the two clients pure renderers.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Any

from sani_core.approvals import ApprovalRegistry
from sani_core.executor import Executor
from sani_core.models import build_model
from sani_core.permissions import ActionType, PermissionLocked
from sani_core.session import AgentSession, Lifecycle, SessionStatus
from sani_core.tools import build_tools

from .hub import SessionHub
from .sandbox import build_sandbox
from .stores import MemorySessionStore, SessionRecord, SessionStore, UnknownSession

#: When set, every session workspace must live inside this directory.
WORKSPACE_ROOT_ENV = "SANI_WORKSPACE_ROOT"

#: Directories a workspace may never be, even with no root configured. Not a
#: security boundary -- Phase 0 has no auth and must not be exposed -- but it
#: stops an obvious typo from pointing an agent at the filesystem root.
FORBIDDEN_WORKSPACES = frozenset(
    {"/", "/etc", "/usr", "/bin", "/sbin", "/lib", "/boot", "/dev", "/proc", "/sys", "/var"}
)


class InvalidWorkspace(ValueError):
    pass


class InvalidState(Exception):
    """A lifecycle transition that does not apply to the session's status."""


class SessionManager:
    def __init__(self, store: SessionStore | None = None) -> None:
        self.store = store or MemorySessionStore()

    # ---- workspace ----

    @staticmethod
    def _resolve_workspace(raw: str | None) -> Path:
        if raw is None:
            root = os.environ.get(WORKSPACE_ROOT_ENV)
            base = Path(root).resolve() if root else Path(tempfile.gettempdir())
            base.mkdir(parents=True, exist_ok=True)
            return Path(tempfile.mkdtemp(prefix="sani-ws-", dir=base)).resolve()

        path = Path(raw).expanduser().resolve()
        if not path.is_dir():
            raise InvalidWorkspace(f"workspace {path} does not exist or is not a directory")
        if str(path) in FORBIDDEN_WORKSPACES:
            raise InvalidWorkspace(f"{path} is not a permitted workspace")

        configured_root = os.environ.get(WORKSPACE_ROOT_ENV)
        if configured_root:
            root = Path(configured_root).resolve()
            if not path.is_relative_to(root):
                raise InvalidWorkspace(
                    f"workspace {path} is outside {WORKSPACE_ROOT_ENV} ({root})"
                )
        return path

    # ---- lifecycle ----

    def create(
        self,
        *,
        task: str,
        workspace: str | None = None,
        tools: list[str] | None = None,
        lifecycle: str = "foreground",
        script: list[dict[str, Any]] | None = None,
        model_backend: str | None = None,
        trust_overrides: dict[str, bool] | None = None,
    ) -> SessionRecord:
        ws = self._resolve_workspace(workspace)
        tool_names = tools or ["file_editor", "shell"]

        session = AgentSession(
            task=task,
            workspace=ws,
            tools=tool_names,
            lifecycle=Lifecycle(lifecycle),
        )
        # Applied before the executor starts, so a client asking for
        # manual-approval-everything is never racing the first step.
        for raw_type, auto in (trust_overrides or {}).items():
            try:
                parsed = ActionType(raw_type)
            except ValueError as exc:
                raise InvalidState(f"unknown action_type {raw_type!r}") from exc
            session.trust.set_auto_approve(parsed, auto)

        hub = SessionHub(session.id)
        executor = Executor(
            session,
            tools=build_tools(tool_names, ws),
            model=build_model(model_backend, script=script),
            emit=hub.publish,
            registry=ApprovalRegistry(),
        )
        record = SessionRecord(
            session=session,
            hub=hub,
            executor=executor,
            sandbox=build_sandbox(ws, session.id),
        )
        self.store.put(record)

        # The executor runs detached. Clients attach to the stream whenever they
        # like; the hub's log means a late subscriber misses nothing.
        record.task = asyncio.create_task(executor.run(), name=f"sani-exec-{session.id}")
        return record

    def get(self, session_id: str) -> SessionRecord:
        return self.store.get(session_id)

    def list(self) -> list[SessionRecord]:
        return self.store.list()

    # ---- approvals ----

    def resolve_approval(
        self,
        session_id: str,
        action_id: str,
        *,
        approved: bool,
        hunk_ids: list[str] | None = None,
        note: str | None = None,
    ) -> dict:
        record = self.get(session_id)
        outcome = record.executor.registry.resolve(
            action_id, approved=approved, hunk_ids=hunk_ids, note=note
        )
        return {
            "session_id": session_id,
            "action_id": action_id,
            **outcome.to_dict(),
            "status": record.session.status.value,
        }

    # ---- control ----

    def pause(self, session_id: str) -> SessionRecord:
        record = self.get(session_id)
        if record.session.is_terminal:
            raise InvalidState(f"session is {record.session.status.value}")
        record.executor.pause()
        return record

    def resume(self, session_id: str) -> SessionRecord:
        record = self.get(session_id)
        if record.session.is_terminal:
            raise InvalidState(f"session is {record.session.status.value}")
        record.executor.resume()
        return record

    async def kill(self, session_id: str) -> SessionRecord:
        record = self.get(session_id)
        if record.session.is_terminal:
            return record
        record.executor.kill()
        if record.task:
            # The executor stops at its next checkpoint. A tool call already in
            # flight is allowed to finish rather than leaving a half-written file.
            try:
                await asyncio.wait_for(asyncio.shield(record.task), timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                record.task.cancel()
        await record.sandbox.shutdown()
        return record

    # ---- views ----

    def diff(self, session_id: str) -> dict:
        record = self.get(session_id)
        return {
            "session_id": session_id,
            "files": [d.to_dict() for d in record.session.diffs.values()],
        }

    def trust(self, session_id: str) -> dict:
        record = self.get(session_id)
        return {"session_id": session_id, "tiers": record.session.trust.to_dict()}

    def set_trust(self, session_id: str, action_type: str, auto_approve: bool) -> dict:
        record = self.get(session_id)
        try:
            parsed = ActionType(action_type)
        except ValueError as exc:
            raise InvalidState(f"unknown action_type {action_type!r}") from exc
        record.session.trust.set_auto_approve(parsed, auto_approve)
        return self.trust(session_id)

    def mission_control(self) -> dict:
        rows = [r.session.to_mission_control_row() for r in self.list()]
        return {
            "sessions": rows,
            "active": sum(1 for r in rows if r["status"] not in ("complete", "failed", "killed")),
            "awaiting_approval": sum(1 for r in rows if r["approval_needed"]),
        }


__all__ = [
    "InvalidState",
    "InvalidWorkspace",
    "PermissionLocked",
    "SessionManager",
    "SessionStatus",
    "UnknownSession",
]
