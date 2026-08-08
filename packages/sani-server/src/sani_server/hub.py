"""Per-session event log and WebSocket fan-out.

The log is what makes reconnection work. Every event gets a monotonic ``seq``,
so a client that drops mid-run reconnects with ``?from_seq=N`` and receives
exactly what it missed -- no gaps, no duplicates. Spec Section 13 names
reattach-after-disconnect as the least forgiving component in the build.

With an archive attached (Phase 3b) the same log is mirrored to Redis, so the
guarantee survives the process and reaches server instances that never saw the
session start.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager

from sani_core.events import Event

from .archive import NullArchive, SessionArchive

#: Sentinel pushed to every subscriber when a session ends, so socket handlers
#: close cleanly instead of blocking forever on an empty queue.
CLOSED = object()


class SessionHub:
    def __init__(self, session_id: str, archive: SessionArchive | None = None) -> None:
        self.session_id = session_id
        self.archive: SessionArchive = archive or NullArchive()
        self._log: list[dict] = []
        self._subscribers: set[asyncio.Queue] = set()
        self._seq = 0
        self._closed = False
        self._archive_queue: asyncio.Queue | None = None
        self._writer: asyncio.Task | None = None
        self._relay: asyncio.Task | None = None

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
        self._deliver(payload)

        if self.archive.enabled:
            # Queued rather than awaited: a slow Redis must not be what delays a
            # client seeing a token. A single writer drains the queue, because
            # concurrent writes to one list arrive out of order and a replayed
            # log with holes in it is worse than a slow one.
            self._ensure_writer()
            self._archive_queue.put_nowait(payload)  # type: ignore[union-attr]

        if event.is_terminal:
            # The one place the write *is* awaited. Once a client has seen
            # session.complete, the archive must already be complete -- another
            # process may read it the moment this returns.
            await self.flush()
            self.close()
        return payload

    def _ensure_writer(self) -> None:
        if self._writer is not None:
            return
        self._archive_queue = asyncio.Queue()

        async def drain() -> None:
            assert self._archive_queue is not None
            while True:
                payload = await self._archive_queue.get()
                try:
                    await self.archive.append_event(self.session_id, payload)
                except Exception:
                    # Losing an archive write degrades replay; letting it kill
                    # the session would be the worse failure.
                    pass
                finally:
                    self._archive_queue.task_done()

        self._writer = asyncio.ensure_future(drain())

    async def flush(self) -> None:
        """Wait for every queued archive write to land."""
        if self._archive_queue is not None:
            await self._archive_queue.join()

    def _deliver(self, payload: dict) -> None:
        self._log.append(payload)
        for queue in list(self._subscribers):
            queue.put_nowait(payload)

    def ingest(self, payload: dict) -> None:
        """Accept an event produced by another process.

        Used by the Redis relay. Deliberately does not re-archive: the process
        that produced it already did, and echoing would duplicate the log.
        """
        if payload["seq"] <= self._seq:
            return
        self._seq = payload["seq"]
        self._deliver(payload)
        if payload["type"] in ("session.complete", "session.error"):
            self.close()

    def hydrate(self, events: list[dict]) -> None:
        """Restore a log read back from the archive."""
        if not events:
            return
        self._log = list(events)
        self._seq = events[-1]["seq"]
        if events[-1]["type"] in ("session.complete", "session.error"):
            self._closed = True

    def start_relay(self) -> None:
        """Forward events published by other processes into local subscribers."""
        if self._relay or not self.archive.enabled or self._closed:
            return

        async def relay() -> None:
            try:
                async for payload in self.archive.watch(self.session_id):
                    self.ingest(payload)
                    if self._closed:
                        return
            except asyncio.CancelledError:
                raise
            except Exception:
                # A dropped relay degrades live cross-process streaming to
                # replay-on-reconnect. That is worth surviving quietly.
                return

        self._relay = asyncio.ensure_future(relay())

    def backlog(self, from_seq: int = 0) -> list[dict]:
        """Every event after ``from_seq``. ``0`` replays the session from birth."""
        if from_seq <= 0:
            return list(self._log)
        return [event for event in self._log if event["seq"] > from_seq]

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
        if self._relay:
            self._relay.cancel()
            self._relay = None
        if self._writer:
            self._writer.cancel()
            self._writer = None
        for queue in list(self._subscribers):
            queue.put_nowait(CLOSED)
