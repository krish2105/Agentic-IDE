"""Phase 3b: sessions that outlive the process, against a real Redis.

Spec Section 13 calls background persistence the biggest technical risk in the
build and says reattaching to a live session after disconnect is the least
forgiving part. These tests run a real ``redis-server`` rather than a fake, so
what is verified is the behaviour rather than a mock's opinion of it.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import time

import pytest
from fastapi.testclient import TestClient
from sani_server.app import create_app
from sani_server.archive import RedisArchive, build_archive
from sani_server.manager import SessionManager

from .helpers import READ_WRITE_DELETE_SCRIPT, first, read_until, start_session, types

pytestmark = pytest.mark.skipif(
    shutil.which("redis-server") is None, reason="redis-server is not installed"
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def redis_url(tmp_path_factory):
    """A throwaway redis-server for the module."""
    port = _free_port()
    directory = tmp_path_factory.mktemp("redis")
    process = subprocess.Popen(
        ["redis-server", "--port", str(port), "--dir", str(directory), "--save", ""],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"redis://127.0.0.1:{port}/0"
    for _ in range(100):
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                break
        time.sleep(0.05)
    else:  # pragma: no cover - only on a broken box
        process.kill()
        pytest.skip("redis-server did not start")

    yield url
    process.terminate()
    process.wait(timeout=10)


@pytest.fixture
def make_client(redis_url):
    """Build independent app instances that share one Redis.

    Separate managers and separate archives, same backing store -- which is
    exactly the shape of two server processes behind a load balancer.
    """
    clients = []

    def factory():
        manager = SessionManager(archive=RedisArchive(redis_url))
        client = TestClient(create_app(manager))
        client.__enter__()
        clients.append(client)
        return client

    yield factory
    for client in reversed(clients):
        client.__exit__(None, None, None)


def test_the_archive_is_reported_so_clients_know_what_they_have(make_client):
    body = make_client().get("/healthz").json()
    assert body["session_store"]["kind"] == "redis"
    assert body["session_store"]["durable"] is True


def test_a_finished_session_survives_the_process(make_client, workspace):
    first_server = make_client()
    session_id = start_session(first_server, workspace, READ_WRITE_DELETE_SCRIPT)

    with first_server.websocket_connect(f"/session/{session_id}/stream") as ws:
        events = read_until(ws, "approval.required")
        action_id = first(events, "approval.required")["data"]["action"]["id"]
        first_server.post(f"/session/{session_id}/approve", json={"action_id": action_id})
        original = events + read_until(ws, "session.complete")

    # A different server instance, sharing only Redis, finds the whole session.
    second_server = make_client()
    state = second_server.get(f"/session/{session_id}").json()
    assert state["status"] == "complete"
    assert state["task"] == "demo task"
    assert [s["status"] for s in state["plan"]["steps"]] == ["complete"] * 3

    # Including the diffs, so the Diffs tab is not empty after a restart.
    files = second_server.get(f"/session/{session_id}/diff").json()["files"]
    assert {f["path"] for f in files} == {"greeting.py", "scratch.tmp"}

    # And the full event log replays, gapless.
    with second_server.websocket_connect(f"/session/{session_id}/stream") as ws:
        replayed = read_until(ws, "session.complete")
    seqs = [e["seq"] for e in replayed]
    assert seqs == list(range(1, len(seqs) + 1)), "the replayed log must be gapless"
    assert types(replayed) == types(original), "replay must match what the owner saw"


def test_a_second_instance_streams_a_session_it_never_created(make_client, workspace):
    """Live cross-process fan-out, not just replay."""
    owner = make_client()
    session_id = start_session(owner, workspace, READ_WRITE_DELETE_SCRIPT)

    with owner.websocket_connect(f"/session/{session_id}/stream") as owner_ws:
        events = read_until(owner_ws, "approval.required")
        action_id = first(events, "approval.required")["data"]["action"]["id"]

        observer = make_client()
        with observer.websocket_connect(f"/session/{session_id}/stream") as observer_ws:
            # The observer catches up on everything so far from the Redis log.
            caught_up = read_until(observer_ws, "approval.required")
            assert first(caught_up, "approval.required")["data"]["action"]["id"] == action_id

            # Now resolve on the owner and watch it arrive on the observer.
            owner.post(f"/session/{session_id}/approve", json={"action_id": action_id})

            live = read_until(observer_ws, "session.complete")
            assert "approval.resolved" in types(live)
            assert types(live)[-1] == "session.complete"

        read_until(owner_ws, "session.complete")


def test_a_session_interrupted_by_a_restart_says_so(make_client, workspace, redis_url):
    """No spinner for work that will never resume."""
    owner = make_client()
    session_id = start_session(owner, workspace, READ_WRITE_DELETE_SCRIPT)

    with owner.websocket_connect(f"/session/{session_id}/stream") as ws:
        read_until(ws, "approval.required")

    # The owner never resolves it; a fresh instance restores the record.
    survivor = make_client()
    state = survivor.get(f"/session/{session_id}").json()
    assert state["status"] == "failed"
    assert "interrupted" in state["error"]

    # It is history, not something you can steer.
    for endpoint in ("pause", "resume"):
        response = survivor.post(f"/session/{session_id}/{endpoint}")
        assert response.status_code == 409
        assert response.json()["error"] == "invalid_state"

    board = survivor.get("/mission-control").json()
    row = next(r for r in board["sessions"] if r["session_id"] == session_id)
    assert row["detached"] is True

    owner.post(f"/session/{session_id}/kill")


def test_restore_re_derives_trust_rather_than_trusting_the_snapshot(make_client, workspace):
    """A snapshot is untrusted input once it has been through Redis."""
    owner = make_client()
    session_id = start_session(owner, workspace, [])
    with owner.websocket_connect(f"/session/{session_id}/stream") as ws:
        read_until(ws, "session.complete")

    url = owner.app.state.manager.archive.url

    async def forge() -> None:
        # One coroutine, one event loop: the redis client binds its connection
        # to the loop it was first used on.
        archive = RedisArchive(url)
        state = next(s for s in await archive.load() if s["session_id"] == session_id)
        state["trust"]["file.delete"]["auto_approve"] = True
        state["trust"]["file.delete"]["consecutive_approvals"] = 999
        await archive.snapshot(session_id, state)
        await archive.close()

    _run(forge())

    restored = make_client()
    tiers = restored.get(f"/session/{session_id}/trust").json()["tiers"]
    assert tiers["file.delete"]["auto_approve"] is False
    assert tiers["file.delete"]["always_confirm"] is True


def test_build_archive_selection():
    assert build_archive("memory").enabled is False
    with pytest.raises(ValueError, match="unknown session store"):
        build_archive("dynamodb")


def _run(coro):
    """Run one coroutine from sync test code."""
    import asyncio

    return asyncio.run(coro)
