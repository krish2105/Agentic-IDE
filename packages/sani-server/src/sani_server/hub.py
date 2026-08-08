"""Per-session event log and WebSocket fan-out.

The log is what makes reconnection work. Every event gets a monotonic ``seq``,
so a client that drops mid-run reconnects with ``?from_seq=N`` and receives
exactly what it missed -- no gaps, no duplicates. Spec Section 13 names
reattach-after-disconnect as the least forgiving component in the build; it is
cheap to get right here and very expensive to retrofit later, so Phase 0 pays
for it up front even though background sessions do not arrive until Phase 3b.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager

from sani_core.events import Event

#: Sentinel pushed to every subscriber when a session ends, so socket handlers
#: close cleanly instead of blocking forever on an empty queue.
CLOSED = object()


class SessionHub:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._log: list[dict] = []
        self._subscribers: set[asyncio.Queue] = set()
        self._seq = 0
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def last_seq(self) -> int:
        return self._seq

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    async def publish(self, event: Event) -> dict:
        """Stamp, persist and fan out one event. Matches ``sani_core.EmitFn``."""
        self._seq += 1
        event.seq = self._seq
        payload = event.to_dict()
        self._log.append(payload)

        for queue in list(self._subscribers):
            queue.put_nowait(payload)

        if event.is_terminal:
            self.close()
        return payload

    def backlog(self, from_seq: int = 0) -> list[dict]:
        """Every event after ``from_seq``. ``0`` replays the session from birth."""
        if from_seq <= 0:
            return list(self._log)
        return [e for e in self._log if e["seq"] > from_seq]

    @contextmanager
    def subscribe(self) -> Iterator[asyncio.Queue]:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(queue)
        if self._closed:
            queue.put_nowait(CLOSED)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for queue in list(self._subscribers):
            queue.put_nowait(CLOSED)
