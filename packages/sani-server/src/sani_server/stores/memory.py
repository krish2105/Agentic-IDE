"""In-process session store. Phase 0 default."""

from __future__ import annotations

from .base import SessionRecord, UnknownSession


class MemorySessionStore:
    def __init__(self) -> None:
        self._records: dict[str, SessionRecord] = {}

    def put(self, record: SessionRecord) -> None:
        self._records[record.session.id] = record

    def get(self, session_id: str) -> SessionRecord:
        try:
            return self._records[session_id]
        except KeyError as exc:
            raise UnknownSession(session_id) from exc

    def has(self, session_id: str) -> bool:
        return session_id in self._records

    def list(self) -> list[SessionRecord]:
        return sorted(self._records.values(), key=lambda r: r.session.created_at)

    def delete(self, session_id: str) -> None:
        self._records.pop(session_id, None)
