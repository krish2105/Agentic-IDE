"""Session storage interface.

Phase 0 ships the in-memory implementation only. Phase 3b adds a Redis-backed
one for background persistence; every call site goes through this protocol so
that swap touches no route and no manager logic.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from sani_core.executor import Executor
from sani_core.session import AgentSession

from ..hub import SessionHub


@dataclass
class SessionRecord:
    """A live session plus the runtime handles the transport needs.

    Only ``session`` is serialisable state. A Redis store persists that and
    rebuilds ``hub`` / ``executor`` / ``task`` on reattach.
    """

    session: AgentSession
    hub: SessionHub
    executor: Executor
    task: asyncio.Task | None = None


class UnknownSession(KeyError):
    pass


class SessionStore(Protocol):
    def put(self, record: SessionRecord) -> None: ...

    def get(self, session_id: str) -> SessionRecord: ...

    def has(self, session_id: str) -> bool: ...

    def list(self) -> list[SessionRecord]: ...

    def delete(self, session_id: str) -> None: ...
