"""Pause, resume and kill.

Each test parks the session on an approval first. That is the one point where
the executor's position is deterministic, so the lifecycle transition under
test happens at a known place in the plan rather than wherever the scheduler
happened to be.
"""

from __future__ import annotations

from .helpers import first, read_until, start_session, statuses, types

#: Blocks on step 0, then has two trivial steps left to run afterwards.
BLOCK_THEN_WORK = [
    {
        "description": "Remove the scratch file",
        "tool": "file_editor",
        "params": {"op": "delete", "path": "scratch.tmp"},
    },
    {
        "description": "Say hello",
        "tool": "shell",
        "params": {"command": "echo hello"},
    },
    {
        "description": "Say goodbye",
        "tool": "shell",
        "params": {"command": "echo goodbye"},
    },
]

ALLOW_SHELL = {"shell.other": True}


def test_pause_takes_effect_at_the_next_step_boundary_and_resume_continues(
    client, workspace
):
    session_id = start_session(
        client, workspace, BLOCK_THEN_WORK, trust_overrides=ALLOW_SHELL
    )

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        events = read_until(ws, "approval.required")
        action_id = first(events, "approval.required")["data"]["action"]["id"]

        # Requested while parked, so it lands at the boundary after step 0.
        assert client.post(f"/session/{session_id}/pause").json()["pause_requested"] is True
        client.post(f"/session/{session_id}/approve", json={"action_id": action_id})

        paused_at = read_until(ws, "session.status")
        while paused_at[-1]["data"].get("status") != "paused":
            paused_at += read_until(ws, "session.status")

        # Step 0 finished before the pause landed; steps 1 and 2 have not run.
        assert "tool.result" in types(paused_at)
        assert not (workspace / "scratch.tmp").exists()
        assert client.get(f"/session/{session_id}").json()["status"] == "paused"

        assert client.post(f"/session/{session_id}/resume").json()["pause_requested"] is False
        tail = read_until(ws, "session.complete")

    assert "executing" in statuses(tail)
    state = client.get(f"/session/{session_id}").json()
    assert state["status"] == "complete"
    assert [s["status"] for s in state["plan"]["steps"]] == ["complete"] * 3


def test_kill_while_blocked_ends_the_session_and_skips_the_rest(client, workspace):
    session_id = start_session(
        client, workspace, BLOCK_THEN_WORK, trust_overrides=ALLOW_SHELL
    )

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        read_until(ws, "approval.required")

        killed = client.post(f"/session/{session_id}/kill")
        assert killed.status_code == 200
        assert killed.json()["status"] == "killed"

        tail = read_until(ws, "session.complete")

    # The parked approval resolves as rejected rather than hanging forever.
    resolved = first(tail, "approval.resolved")["data"]
    assert resolved["approved"] is False
    assert resolved["note"] == "session terminated"
    assert first(tail, "session.complete")["data"]["status"] == "killed"

    state = client.get(f"/session/{session_id}").json()
    assert state["status"] == "killed"
    assert [s["status"] for s in state["plan"]["steps"]] == ["skipped", "skipped", "skipped"]
    assert (workspace / "scratch.tmp").exists(), "the blocked delete must not have run"


def test_the_socket_closes_itself_when_the_session_ends(client, workspace):
    """No sentinel-watching required on the client: the stream just ends."""
    session_id = start_session(client, workspace, [{
        "description": "Say hello",
        "tool": "shell",
        "params": {"command": "echo hello"},
    }], trust_overrides=ALLOW_SHELL)

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        read_until(ws, "session.complete")
        # Anything after a terminal event is a closed socket, not more data.
        try:
            extra = ws.receive()
        except Exception:
            extra = {"type": "websocket.close"}
    assert extra["type"] in ("websocket.close", "websocket.disconnect")


def test_lifecycle_calls_on_a_finished_session_are_rejected(client, workspace):
    session_id = start_session(client, workspace, [])

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        read_until(ws, "session.complete")

    assert client.post(f"/session/{session_id}/pause").status_code == 409
    assert client.post(f"/session/{session_id}/resume").status_code == 409
    # Killing something already dead is a no-op, not an error.
    assert client.post(f"/session/{session_id}/kill").status_code == 200


def test_late_subscriber_gets_the_whole_run_from_the_log(client, workspace):
    """Connecting after a session finishes still replays it in full."""
    session_id = start_session(client, workspace, [{
        "description": "Say hello",
        "tool": "shell",
        "params": {"command": "echo hello"},
    }], trust_overrides=ALLOW_SHELL)

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        read_until(ws, "session.complete")

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        replayed = read_until(ws, "session.complete")

    assert types(replayed)[0] == "session.status"
    assert types(replayed)[-1] == "session.complete"
    assert [e["seq"] for e in replayed] == list(range(1, len(replayed) + 1))
