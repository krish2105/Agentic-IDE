"""Session Manager -- create, inspect and control Agent Sessions.

Single source of truth for session state (spec Section 2). Routes are thin
translations of these methods into HTTP; no business logic lives above this
layer, which is what keeps the two clients pure renderers.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from sani_core.approvals import ApprovalRegistry
from sani_core.critic import build_critic
from sani_core.events import EventType
from sani_core.executor import Executor
from sani_core.models import build_model
from sani_core.permissions import ActionType, PermissionLocked
from sani_core.rag import CodebaseIndex
from sani_core.session import AgentSession, Lifecycle, SessionStatus
from sani_core.tools import build_tools

from .archive import SessionArchive, build_archive, fire_and_forget
from .hub import SessionHub
from .runner import SandboxCommandRunner
from .sandbox import build_sandbox
from .stores import MemorySessionStore, SessionRecord, SessionStore, UnknownSession

#: ``none`` (default) or ``scripted``. A critic costs a second inference per
#: gated action, so it is opt-in.
CRITIC_ENV_VAR = "SANI_CRITIC"

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


#: Events after which the archived snapshot is refreshed.
SNAPSHOT_ON = frozenset(
    {EventType.SESSION_STATUS, EventType.SESSION_COMPLETE, EventType.SESSION_ERROR}
)


def _require_live(record) -> None:
    """Reject steering a session restored from the archive.

    Its executor died with the process that owned it. Accepting the call and
    silently doing nothing would be worse than a clear error.
    """
    if record.detached or record.executor is None:
        raise InvalidState(
            "session was restored from the archive and has no running executor"
        )


class SessionManager:
    def __init__(
        self,
        store: SessionStore | None = None,
        archive: SessionArchive | None = None,
        rag: CodebaseIndex | None = None,
    ) -> None:
        self.store = store or MemorySessionStore()
        self.archive: SessionArchive = archive or build_archive()
        # One index per server, keyed internally by workspace: two sessions on
        # the same repo share it rather than each paying to build their own.
        self.rag = rag or CodebaseIndex()
        self._writes: set[asyncio.Task] = set()

    def _persist(self, session: AgentSession) -> None:
        """Queue a snapshot without waiting for it."""
        if self.archive.enabled:
            fire_and_forget(
                self.archive.snapshot(session.id, session.to_dict()), keep=self._writes
            )

    async def _persist_now(self, session: AgentSession) -> None:
        """Write a snapshot and wait for it.

        Used at terminal transitions for the same reason the event log is
        flushed there: another process may read this session the instant it
        sees session.complete, and a stale snapshot at that moment is
        indistinguishable from a session that never finished.

        Queued snapshots are drained first. `_persist` is fire-and-forget and so
        unordered, which meant a snapshot queued two events ago could land
        *after* this awaited write and put the session back to `executing` --
        exactly the stale state this method exists to prevent. The event log
        already solved the same hazard with a single ordered writer; snapshots
        never got that treatment, and only a durable store made it visible.
        """
        if not self.archive.enabled:
            return

        pending = [task for task in self._writes if not task.done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        await self.archive.snapshot(session.id, session.to_dict())

    async def restore(self) -> int:
        """Rehydrate archived sessions at startup (Phase 3b).

        Returns how many were recovered. Sessions that were mid-flight when the
        process died are marked failed rather than left looking live: their
        executor is gone, and showing a spinner for work that will never resume
        would be a lie the user cannot detect.
        """
        if not self.archive.enabled:
            return 0

        recovered = 0
        for state in await self.archive.load():
            session_id = state.get("session_id")
            if not session_id or self.store.has(session_id):
                continue

            session = AgentSession.from_dict(state)
            hub = SessionHub(session_id, self.archive)
            hub.hydrate(await self.archive.events(session_id))

            if not session.is_terminal:
                session.status = SessionStatus.FAILED
                session.error = "session interrupted by a server restart"
                session.ended_at = time.time()
                self._persist(session)

            # No executor and no sandbox: this record is a readable history, not
            # a resumable run. Lifecycle calls against it fail loudly.
            self.store.put(
                SessionRecord(
                    session=session,
                    hub=hub,
                    executor=None,
                    sandbox=build_sandbox(session.workspace, session_id),
                    detached=True,
                )
            )
            recovered += 1
        return recovered

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

        hub = SessionHub(session.id, self.archive)
        # The sandbox is built first: the agent's shell tool executes through
        # it, so it is a dependency of the tools rather than a side channel.
        sandbox = build_sandbox(ws, session.id)
        async def emit(event):
            # Snapshot on every status transition: the archive is what a
            # restarted process and a second server instance read, and a stale
            # snapshot there is indistinguishable from a stuck session.
            #
            # On a terminal event the snapshot is written *before* publish, not
            # after. `_finish` sets the status before emitting, so the state is
            # already correct here -- and publishing first let a client see
            # session.complete while the snapshot still said `executing`, which
            # a second server then read as an interrupted run and marked failed.
            if event.is_terminal:
                await self._persist_now(session)
                return await hub.publish(event)

            payload = await hub.publish(event)
            if event.type in SNAPSHOT_ON:
                self._persist(session)
            return payload

        async def retrieve(task_text: str) -> tuple[str, list[str]]:
            """Retrieval is best-effort: an index problem must not fail a run."""
            try:
                matches = await self.rag.query(ws, task_text)
                if not matches:
                    return "", []
                return (
                    await self.rag.context_for(ws, task_text),
                    [match.chunk.label for match in matches],
                )
            except Exception:
                return "", []

        executor = Executor(
            session,
            tools=build_tools(tool_names, ws, runner=SandboxCommandRunner(sandbox)),
            model=build_model(model_backend, script=script),
            emit=emit,
            registry=ApprovalRegistry(),
            retriever=retrieve,
            critic=build_critic(os.environ.get(CRITIC_ENV_VAR)),
        )
        record = SessionRecord(
            session=session, hub=hub, executor=executor, sandbox=sandbox
        )
        self.store.put(record)

        # The executor runs detached. Clients attach to the stream whenever they
        # like; the hub's log means a late subscriber misses nothing.
        self._persist(session)
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
        _require_live(record)
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
        _require_live(record)
        record.executor.pause()
        return record

    def resume(self, session_id: str) -> SessionRecord:
        record = self.get(session_id)
        if record.session.is_terminal:
            raise InvalidState(f"session is {record.session.status.value}")
        _require_live(record)
        record.executor.resume()
        return record

    async def kill(self, session_id: str) -> SessionRecord:
        record = self.get(session_id)
        if record.session.is_terminal:
            return record
        _require_live(record)
        record.executor.kill()
        if record.task:
            # The executor stops at its next checkpoint. A tool call already in
            # flight is allowed to finish rather than leaving a half-written file.
            try:
                await asyncio.wait_for(asyncio.shield(record.task), timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                record.task.cancel()
        await record.sandbox.shutdown()
        await self._persist_now(record.session)
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
        self._persist(record.session)
        return self.trust(session_id)

    def mission_control(self) -> dict:
        records = self.list()
        rows = [r.session.to_mission_control_row() for r in records]
        detached = {r.session.id for r in records if r.detached}
        # Presence is live state, not history -- see routes/sessions.py.
        watchers = {r.session.id: r.hub.subscriber_count for r in records if r.hub}
        for row in rows:
            row["detached"] = row["session_id"] in detached
            row["watchers"] = watchers.get(row["session_id"], 0)
        return {
            "sessions": rows,
            "active": sum(1 for r in rows if r["status"] not in ("complete", "failed", "killed")),
            "awaiting_approval": sum(1 for r in rows if r["approval_needed"]),
            "store": self.archive.describe(),
        }


__all__ = [
    "InvalidState",
    "InvalidWorkspace",
    "PermissionLocked",
    "SessionManager",
    "SessionStatus",
    "UnknownSession",
]
