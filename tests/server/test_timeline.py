"""GET /session/{id}/timeline -- the replay endpoint.

Replay reads the same log the stream replays from, so the two can never
disagree about what happened. The endpoint adds the computed keyframes, which
belong on the server because clients hold no business logic.
"""

from __future__ import annotations

from .helpers import READ_WRITE_DELETE_SCRIPT, read_until, start_session


def test_timeline_returns_the_whole_log_with_keyframes(client, workspace):
    session_id = start_session(client, workspace, READ_WRITE_DELETE_SCRIPT)

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        read_until(ws, "approval.required")
    client.post(f"/session/{session_id}/kill")

    response = client.get(f"/session/{session_id}/timeline")
    assert response.status_code == 200
    body = response.json()

    assert body["session_id"] == session_id
    assert body["count"] == len(body["events"])
    assert body["last_seq"] == body["events"][-1]["seq"]
    assert body["keyframes"]


def test_the_timeline_log_is_gapless_and_monotonic(client, workspace):
    """The scrubber's whole contract: seq n is always reachable."""
    session_id = start_session(client, workspace, READ_WRITE_DELETE_SCRIPT)

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        read_until(ws, "approval.required")
    client.post(f"/session/{session_id}/kill")

    seqs = [event["seq"] for event in client.get(f"/session/{session_id}/timeline").json()["events"]]
    assert seqs == list(range(1, len(seqs) + 1))


def test_a_parked_approval_appears_as_a_keyframe(client, workspace):
    session_id = start_session(client, workspace, READ_WRITE_DELETE_SCRIPT)

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        read_until(ws, "approval.required")

    body = client.get(f"/session/{session_id}/timeline").json()
    kinds = {frame["kind"] for frame in body["keyframes"]}
    assert "approval" in kinds

    client.post(f"/session/{session_id}/kill")


def test_timeline_of_an_unknown_session_is_404(client):
    response = client.get("/session/ses_nope/timeline")
    assert response.status_code == 404
    assert response.json()["error"] == "unknown_session"


def test_a_brand_new_session_has_a_well_formed_empty_timeline(client, workspace):
    """A session created a moment ago may have no events yet. The scrubber has
    to render that rather than crash on it."""
    session_id = start_session(client, workspace, [])
    body = client.get(f"/session/{session_id}/timeline").json()

    assert body["count"] >= 0
    assert body["first_seq"] >= 0
    assert isinstance(body["keyframes"], list)
    client.post(f"/session/{session_id}/kill")


def test_from_seq_narrows_the_window_without_breaking_the_shape(client, workspace):
    """Deep-linking to ?seq=N should not require shipping the whole log."""
    session_id = start_session(client, workspace, READ_WRITE_DELETE_SCRIPT)

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        read_until(ws, "approval.required")
    client.post(f"/session/{session_id}/kill")

    full = client.get(f"/session/{session_id}/timeline").json()
    tail = client.get(f"/session/{session_id}/timeline?from_seq=3").json()

    assert tail["count"] < full["count"]
    assert all(event["seq"] > 3 for event in tail["events"])
    # last_seq still describes the session, not the window -- the scrubber needs
    # to know how long the whole run is even when it only fetched a slice.
    assert tail["last_seq"] == full["last_seq"]
