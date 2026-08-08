"""Durable session records (spec Phase 3b).

The in-memory store holds *runtime* handles -- the executor task, the sandbox,
the PTY. None of that can live in Redis; it is process-local by nature. What
can live in Redis is the record: the session snapshot and its event log.

Splitting the two that way keeps every existing call site synchronous and
means the archive is genuinely optional. Without it the server behaves exactly
as it did in Phase 0. With it, sessions survive the process, a second server
instance can stream a session it never created, and a restart can say honestly
what happened to work that was in flight.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from typing import Any, Protocol

ARCHIVE_ENV_VAR = "SANI_SESSION_STORE"
REDIS_URL_ENV_VAR = "SANI_REDIS_URL"
DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/0"

#: How long an archived session lives before Redis reclaims it. The in-memory
#: log was unbounded; this is the first time retention has an answer.
DEFAULT_TTL_S = 60 * 60 * 24 * 7


class SessionArchive(Protocol):
    """Durable side of a session. Every method must tolerate being a no-op."""

    @property
    def enabled(self) -> bool: ...

    async def snapshot(self, session_id: str, state: dict) -> None: ...

    async def append_event(self, session_id: str, payload: dict) -> None: ...

    async def load(self) -> list[dict]: ...

    async def events(self, session_id: str) -> list[dict]: ...

    def watch(self, session_id: str) -> AsyncIterator[dict]: ...

    async def close(self) -> None: ...

    def describe(self) -> dict: ...


class NullArchive:
    """The Phase 0 behaviour: sessions live and die with the process."""

    @property
    def enabled(self) -> bool:
        return False

    async def snapshot(self, session_id: str, state: dict) -> None:
        return None

    async def append_event(self, session_id: str, payload: dict) -> None:
        return None

    async def load(self) -> list[dict]:
        return []

    async def events(self, session_id: str) -> list[dict]:
        return []

    async def watch(self, session_id: str) -> AsyncIterator[dict]:
        # An empty async generator: nothing ever arrives from elsewhere.
        return
        yield {}  # pragma: no cover - unreachable, defines the generator

    async def close(self) -> None:
        return None

    def describe(self) -> dict:
        return {"kind": "memory", "durable": False}


class RedisArchive:
    """Redis-backed session records with cross-process fan-out.

    Two keys per session: a hash holding the latest snapshot, and a list
    holding every event in order. The list *is* the replay log, so a process
    that never saw the session can still answer ``?from_seq=N`` correctly.

    Live events additionally go to a pub/sub channel, which is what lets a
    second server instance stream a session it did not create.
    """

    def __init__(self, url: str | None = None, *, ttl_s: int = DEFAULT_TTL_S) -> None:
        import redis.asyncio as aioredis

        self.url = url or os.environ.get(REDIS_URL_ENV_VAR, DEFAULT_REDIS_URL)
        self.ttl_s = ttl_s
        self._redis = aioredis.from_url(self.url, decode_responses=True)

    @property
    def enabled(self) -> bool:
        return True

    @staticmethod
    def _snapshot_key(session_id: str) -> str:
        return f"sani:session:{session_id}"

    @staticmethod
    def _events_key(session_id: str) -> str:
        return f"sani:events:{session_id}"

    @staticmethod
    def _channel(session_id: str) -> str:
        return f"sani:stream:{session_id}"

    async def ping(self) -> bool:
        try:
            return bool(await self._redis.ping())
        except Exception:
            return False

    async def snapshot(self, session_id: str, state: dict) -> None:
        key = self._snapshot_key(session_id)
        await self._redis.set(key, json.dumps(state), ex=self.ttl_s)
        await self._redis.sadd("sani:sessions", session_id)

    async def append_event(self, session_id: str, payload: dict) -> None:
        encoded = json.dumps(payload)
        key = self._events_key(session_id)
        pipeline = self._redis.pipeline()
        pipeline.rpush(key, encoded)
        pipeline.expire(key, self.ttl_s)
        pipeline.publish(self._channel(session_id), encoded)
        await pipeline.execute()

    async def load(self) -> list[dict]:
        ids = await self._redis.smembers("sani:sessions")
        states: list[dict] = []
        for session_id in sorted(ids):
            raw = await self._redis.get(self._snapshot_key(session_id))
            if raw is None:
                # The snapshot expired; drop the dangling index entry.
                await self._redis.srem("sani:sessions", session_id)
                continue
            states.append(json.loads(raw))
        return states

    async def events(self, session_id: str) -> list[dict]:
        raw = await self._redis.lrange(self._events_key(session_id), 0, -1)
        return [json.loads(item) for item in raw]

    async def watch(self, session_id: str) -> AsyncIterator[dict]:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(self._channel(session_id))
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                yield json.loads(message["data"])
        finally:
            await pubsub.unsubscribe(self._channel(session_id))
            await pubsub.aclose()

    async def forget(self, session_id: str) -> None:
        await self._redis.delete(self._snapshot_key(session_id), self._events_key(session_id))
        await self._redis.srem("sani:sessions", session_id)

    async def close(self) -> None:
        try:
            await self._redis.aclose()
        except Exception:
            pass

    def describe(self) -> dict:
        return {"kind": "redis", "durable": True, "url": self.url, "ttl_s": self.ttl_s}


def build_archive(kind: str | None = None, url: str | None = None) -> SessionArchive:
    resolved = (kind or os.environ.get(ARCHIVE_ENV_VAR, "memory")).lower()
    if resolved in ("memory", "none", ""):
        return NullArchive()
    if resolved == "redis":
        return RedisArchive(url)
    raise ValueError(f"unknown session store {resolved!r} (expected 'memory' or 'redis')")


def fire_and_forget(coro: Any, *, keep: set[asyncio.Task]) -> None:
    """Run an archive write without making the caller wait on Redis.

    Event emission is on the hot path of every session; a durable write must
    never be what delays a client seeing a token. Failures are swallowed on
    purpose -- losing an archive write degrades replay, but blocking or
    crashing the executor over it would be worse.
    """
    task = asyncio.ensure_future(coro)
    keep.add(task)

    def _done(finished: asyncio.Task) -> None:
        keep.discard(finished)
        if not finished.cancelled():
            # Consume the exception so a failed archive write does not surface
            # as an unretrieved-task warning on an unrelated code path.
            finished.exception()

    task.add_done_callback(_done)
