"""GET /provenance -- attribution across a workspace.

Derived from the diffs the agent already emitted rather than tracked
separately, so it cannot disagree with the diff history.
"""

from __future__ import annotations

from .helpers import READ_WRITE_DELETE_SCRIPT, read_until, start_session


def test_agent_written_lines_are_attributed_to_their_session(client, workspace):
    session_id = start_session(client, workspace, READ_WRITE_DELETE_SCRIPT)

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        read_until(ws, "approval.required")
    client.post(f"/session/{session_id}/kill")

    body = client.get(f"/provenance?session_id={session_id}").json()

    assert body["agent_lines"] > 0
    assert "greeting.py" in body["files"]
    ranges = body["files"]["greeting.py"]["ranges"]
    assert ranges
    assert ranges[0]["session_id"] == session_id


def test_provenance_can_be_addressed_by_workspace_path(client, workspace):
    session_id = start_session(client, workspace, READ_WRITE_DELETE_SCRIPT)

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        read_until(ws, "approval.required")
    client.post(f"/session/{session_id}/kill")

    by_path = client.get(f"/provenance?workspace={workspace}").json()
    by_session = client.get(f"/provenance?session_id={session_id}").json()
    assert by_path["agent_lines"] == by_session["agent_lines"]


def test_a_workspace_the_agent_never_touched_reports_nothing(client, tmp_path):
    body = client.get(f"/provenance?workspace={tmp_path}").json()
    assert body["files"] == {}
    assert body["agent_lines"] == 0
    assert body["agent_pct"] == 0.0


def test_provenance_requires_a_target(client):
    response = client.get("/provenance")
    assert response.status_code == 400


def test_ranges_carry_the_model_that_wrote_them(client, workspace):
    """The audit question is not just 'an agent' but 'which one, when'."""
    session_id = start_session(client, workspace, READ_WRITE_DELETE_SCRIPT)

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        read_until(ws, "approval.required")
    client.post(f"/session/{session_id}/kill")

    entry = client.get(f"/provenance?session_id={session_id}").json()["files"]["greeting.py"]
    first = entry["ranges"][0]
    assert "model" in first
    assert "at" in first
    assert first["confidence"] == 1.0
