"""``PgVectorStore`` against a real Postgres.

Spec Section 3 offers pgvector as the durable alternative to the in-memory
index, but the code had no reachable Postgres to run against, so it could only
say honestly that it had never executed. This environment has Postgres 17
with the vector extension already running locally, so these are that
verification, not a mock's opinion of it -- same reasoning
``test_redis_sessions.py`` uses a real ``redis-server``. Skipped, not faked,
wherever a Postgres is not actually reachable.

Each test gets its own table: the fixture drops ``sani_chunks`` after every
test, so `` CREATE TABLE IF NOT EXISTS`` in ``PgVectorStore._connect`` remakes
it fresh next time rather than tests leaking rows into each other.
"""

from __future__ import annotations

import getpass
import os
import shutil
import subprocess

import pytest
from sani_core.rag.chunker import Chunk
from sani_core.rag.store import PgVectorStore, build_vector_store

DSN_ENV_VAR = "SANI_PG_DSN"
DEFAULT_TEST_DSN = f"postgresql://{getpass.getuser()}@localhost:5432/postgres"


def _postgres_reachable() -> bool:
    if not shutil.which("pg_isready"):
        return False
    try:
        result = subprocess.run(
            ["pg_isready", "-h", "localhost", "-p", "5432"],
            capture_output=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return False
    return result.returncode == 0


pytestmark = pytest.mark.skipif(
    not _postgres_reachable(), reason="no reachable Postgres on localhost:5432"
)


def _chunk(path: str, name: str) -> Chunk:
    return Chunk(
        path=path, text=f"def {name}(): pass", start_line=1, end_line=1,
        kind="function", name=name,
    )


@pytest.fixture
async def store():
    instance = PgVectorStore(
        dsn=os.environ.get(DSN_ENV_VAR, DEFAULT_TEST_DSN), dimensions=4
    )
    yield instance
    pool = await instance._connect()
    async with pool.acquire() as connection:
        await connection.execute("DROP TABLE IF EXISTS sani_chunks")
    await pool.close()


async def test_replace_and_query_round_trip_through_real_postgres(store):
    chunks = [_chunk("a.py", "alpha"), _chunk("b.py", "beta")]
    vectors = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]]

    count = await store.replace("ws-1", chunks, vectors)
    assert count == 2

    matches = await store.query("ws-1", [1.0, 0.0, 0.0, 0.0], limit=5)
    assert [m.chunk.name for m in matches] == ["alpha", "beta"]
    assert matches[0].score > matches[1].score


async def test_replace_swaps_rather_than_accumulates(store):
    await store.replace("ws-2", [_chunk("a.py", "alpha")], [[1.0, 0.0, 0.0, 0.0]])
    await store.replace("ws-2", [_chunk("c.py", "gamma")], [[0.0, 0.0, 1.0, 0.0]])

    assert (await store.stats("ws-2"))["chunks"] == 1
    matches = await store.query("ws-2", [0.0, 0.0, 1.0, 0.0], limit=5)
    assert [m.chunk.name for m in matches] == ["gamma"]


async def test_workspaces_do_not_see_each_others_chunks(store):
    await store.replace("ws-a", [_chunk("a.py", "alpha")], [[1.0, 0.0, 0.0, 0.0]])
    await store.replace("ws-b", [_chunk("b.py", "beta")], [[0.0, 1.0, 0.0, 0.0]])

    assert (await store.stats("ws-a"))["chunks"] == 1
    matches = await store.query("ws-a", [1.0, 0.0, 0.0, 0.0], limit=5)
    assert [m.chunk.name for m in matches] == ["alpha"]


async def test_an_unindexed_workspace_queries_empty_rather_than_raising(store):
    assert await store.query("ws-never-indexed", [1.0, 0.0, 0.0, 0.0], limit=5) == []
    assert (await store.stats("ws-never-indexed"))["indexed"] is False


def test_it_now_reports_itself_as_verified():
    assert build_vector_store("pgvector").describe()["verified"] is True
