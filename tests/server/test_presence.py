"""Multiplayer presence: how many people are watching a session.

The protocol already guarantees that multiple clients may subscribe to one
session and all receive identical frames -- that invariant *is* the multiplayer
feature. What was missing was any way to know someone else is there.

Presence is deliberately **not** an event in the log. The log is history: what
the agent did, replayable forever. People joining and leaving is ephemeral
state about right now, and putting it in the log would mean a replay re-enacts
viewers arriving, inflating the timeline with noise that has nothing to do with
the run. So it rides on the session payload, which clients already poll.
"""

from __future__ import annotations

from .helpers import READ_WRITE_DELETE_SCRIPT, read_until, start_session


def test_a_session_with_no_watchers_reports_zero(client, workspace):
    session_id = start_session(client, workspace, [])
    assert client.get(f"/session/{session_id}").json()["watchers"] == 0
    client.post(f"/session/{session_id}/kill")


def test_an_open_stream_counts_as_a_watcher(client, workspace):
    session_id = start_session(client, workspace, READ_WRITE_DELETE_SCRIPT)

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        read_until(ws, "approval.required")
        assert client.get(f"/session/{session_id}").json()["watchers"] == 1

    client.post(f"/session/{session_id}/kill")


def test_two_streams_are_two_watchers(client, workspace):
    """The point of the feature: you can see that someone else is looking."""
    session_id = start_session(client, workspace, READ_WRITE_DELETE_SCRIPT)

    with client.websocket_connect(f"/session/{session_id}/stream") as first:
        read_until(first, "approval.required")
        with client.websocket_connect(f"/session/{session_id}/stream") as second:
            read_until(second, "approval.required")
            assert client.get(f"/session/{session_id}").json()["watchers"] == 2

    client.post(f"/session/{session_id}/kill")


def test_watchers_drop_when_a_client_leaves(client, workspace):
    session_id = start_session(client, workspace, READ_WRITE_DELETE_SCRIPT)

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        read_until(ws, "approval.required")
        assert client.get(f"/session/{session_id}").json()["watchers"] == 1

    assert client.get(f"/session/{session_id}").json()["watchers"] == 0
    client.post(f"/session/{session_id}/kill")


def test_mission_control_reports_watchers_per_row(client, workspace):
    session_id = start_session(client, workspace, READ_WRITE_DELETE_SCRIPT)

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        read_until(ws, "approval.required")
        row = next(
            entry
            for entry in client.get("/mission-control").json()["sessions"]
            if entry["session_id"] == session_id
        )
        assert row["watchers"] == 1

    client.post(f"/session/{session_id}/kill")


def test_presence_never_reaches_the_replayable_log(client, workspace):
    """History is what the agent did. Who watched is not part of that."""
    session_id = start_session(client, workspace, READ_WRITE_DELETE_SCRIPT)

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        read_until(ws, "approval.required")
    client.post(f"/session/{session_id}/kill")

    types = {
        event["type"] for event in client.get(f"/session/{session_id}/timeline").json()["events"]
    }
    assert not any(kind.startswith("presence") for kind in types)
