"""Vector storage.

In-memory by default: a codebase index is cheap to rebuild and nothing here is
worth a database for a single-user dev tool. pgvector is available behind a
flag for the case where it is. It was written against no reachable Postgres
and reported that honestly; ``tests/core/test_pgvector_store.py`` now runs it
for real against a live Postgres+pgvector whenever one is reachable on
``localhost:5432``, the same "skip, don't fake" rule
``test_redis_sessions.py`` uses for a real ``redis-server`` -- so this is
verified, not merely written.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

from .chunker import Chunk
from .embed import cosine

VECTOR_STORE_ENV_VAR = "SANI_VECTOR_STORE"
PG_DSN_ENV_VAR = "SANI_PG_DSN"


@dataclass(slots=True)
class Match:
    chunk: Chunk
    score: float

    def to_dict(self) -> dict:
        return {**self.chunk.to_dict(), "score": round(self.score, 4)}


class VectorStore(ABC):
    kind: str = "store"

    @abstractmethod
    async def replace(self, workspace: str, chunks: list[Chunk], vectors: list[list[float]]) -> int:
        """Swap in a fresh index for a workspace. Returns the chunk count."""

    @abstractmethod
    async def query(self, workspace: str, vector: list[float], limit: int) -> list[Match]: ...

    @abstractmethod
    async def stats(self, workspace: str) -> dict: ...

    async def drop(self, workspace: str) -> None:
        return None

    def describe(self) -> dict:
        return {"kind": self.kind}


class MemoryVectorStore(VectorStore):
    kind = "memory"

    def __init__(self) -> None:
        self._by_workspace: dict[str, tuple[list[Chunk], list[list[float]]]] = {}

    async def replace(self, workspace: str, chunks: list[Chunk], vectors: list[list[float]]) -> int:
        self._by_workspace[workspace] = (chunks, vectors)
        return len(chunks)

    async def query(self, workspace: str, vector: list[float], limit: int) -> list[Match]:
        chunks, vectors = self._by_workspace.get(workspace, ([], []))
        scored = [
            Match(chunk=chunk, score=cosine(vector, stored))
            for chunk, stored in zip(chunks, vectors)
        ]
        # A zero score means no shared tokens at all; returning those would pad
        # the planner's context with text that matched nothing.
        scored = [match for match in scored if match.score > 0]
        scored.sort(key=lambda match: match.score, reverse=True)
        return scored[:limit]

    async def stats(self, workspace: str) -> dict:
        chunks, _ = self._by_workspace.get(workspace, ([], []))
        files = {chunk.path for chunk in chunks}
        return {"chunks": len(chunks), "files": len(files), "indexed": bool(chunks)}

    async def drop(self, workspace: str) -> None:
        self._by_workspace.pop(workspace, None)

    def describe(self) -> dict:
        return {"kind": self.kind, "durable": False, "verified": True}


class PgVectorStore(VectorStore):
    """pgvector-backed storage (spec Section 3).

    Verified against a real Postgres 17 + pgvector -- see
    ``tests/core/test_pgvector_store.py``. To use it: start Postgres with the
    pgvector extension, set SANI_VECTOR_STORE=pgvector and SANI_PG_DSN, index
    a workspace and query it.
    """

    kind = "pgvector"

    def __init__(self, dsn: str | None = None, dimensions: int = 512) -> None:
        self.dsn = dsn or os.environ.get(PG_DSN_ENV_VAR, "")
        self.dimensions = dimensions
        self._pool = None

    async def _connect(self):
        if self._pool is not None:
            return self._pool
        try:
            import asyncpg
        except ImportError as exc:  # pragma: no cover - optional extra
            raise RuntimeError(
                "SANI_VECTOR_STORE=pgvector requires asyncpg: uv sync --extra pgvector"
            ) from exc

        self._pool = await asyncpg.create_pool(self.dsn)
        async with self._pool.acquire() as connection:
            await connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
            await connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS sani_chunks (
                    id          bigserial PRIMARY KEY,
                    workspace   text NOT NULL,
                    path        text NOT NULL,
                    name        text,
                    kind        text,
                    start_line  int NOT NULL,
                    end_line    int NOT NULL,
                    body        text NOT NULL,
                    embedding   vector({self.dimensions})
                )
                """
            )
            await connection.execute(
                "CREATE INDEX IF NOT EXISTS sani_chunks_workspace "
                "ON sani_chunks (workspace)"
            )
        return self._pool

    async def replace(self, workspace: str, chunks: list[Chunk], vectors: list[list[float]]) -> int:
        pool = await self._connect()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "DELETE FROM sani_chunks WHERE workspace = $1", workspace
                )
                await connection.executemany(
                    "INSERT INTO sani_chunks "
                    "(workspace, path, name, kind, start_line, end_line, body, embedding) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
                    [
                        (
                            workspace,
                            chunk.path,
                            chunk.name,
                            chunk.kind,
                            chunk.start_line,
                            chunk.end_line,
                            chunk.text,
                            str(vector),
                        )
                        for chunk, vector in zip(chunks, vectors)
                    ],
                )
        return len(chunks)

    async def query(self, workspace: str, vector: list[float], limit: int) -> list[Match]:
        pool = await self._connect()
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                "SELECT path, name, kind, start_line, end_line, body, "
                "1 - (embedding <=> $2) AS score "
                "FROM sani_chunks WHERE workspace = $1 "
                "ORDER BY embedding <=> $2 LIMIT $3",
                workspace,
                str(vector),
                limit,
            )
        return [
            Match(
                chunk=Chunk(
                    path=row["path"],
                    text=row["body"],
                    start_line=row["start_line"],
                    end_line=row["end_line"],
                    kind=row["kind"],
                    name=row["name"],
                ),
                score=float(row["score"]),
            )
            for row in rows
        ]

    async def stats(self, workspace: str) -> dict:
        pool = await self._connect()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT count(*) AS chunks, count(DISTINCT path) AS files "
                "FROM sani_chunks WHERE workspace = $1",
                workspace,
            )
        return {"chunks": row["chunks"], "files": row["files"], "indexed": row["chunks"] > 0}

    def describe(self) -> dict:
        return {"kind": self.kind, "durable": True, "verified": True, "dsn_set": bool(self.dsn)}


def build_vector_store(kind: str | None = None, *, dimensions: int = 512) -> VectorStore:
    resolved = (kind or os.environ.get(VECTOR_STORE_ENV_VAR, "memory")).lower()
    if resolved == "memory":
        return MemoryVectorStore()
    if resolved == "pgvector":
        return PgVectorStore(dimensions=dimensions)
    raise ValueError(f"unknown vector store {resolved!r} (expected 'memory' or 'pgvector')")
