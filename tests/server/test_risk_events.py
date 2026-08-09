"""`risk.assessed` on the wire.

The assessment is advisory: it exists to make the stakes legible at the moment
a human is asked to take responsibility. It must never become a second gate,
and it must never change what the permission engine decides.
"""

from __future__ import annotations

from .helpers import READ_WRITE_DELETE_SCRIPT, first, read_until, start_session, types


def test_risk_is_assessed_before_the_approval_is_requested(client, workspace):
    """Ordering matters: a client should be able to render the stakes and the
    request together, not pop a score in after the user has already read it."""
    session_id = start_session(client, workspace, READ_WRITE_DELETE_SCRIPT)

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        events = read_until(ws, "approval.required")

    seen = types(events)
    assert "risk.assessed" in seen
    assert seen.index("risk.assessed") < seen.index("approval.required")

    client.post(f"/session/{session_id}/kill")


def test_the_assessment_names_the_action_it_belongs_to(client, workspace):
    session_id = start_session(client, workspace, READ_WRITE_DELETE_SCRIPT)

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        events = read_until(ws, "approval.required")

    risk = first(events, "risk.assessed")["data"]
    approval = first(events, "approval.required")["data"]
    assert risk["action_id"] == approval["action"]["id"]

    client.post(f"/session/{session_id}/kill")


def test_a_delete_is_reported_as_irreversible_and_always_confirm(client, workspace):
    session_id = start_session(client, workspace, READ_WRITE_DELETE_SCRIPT)

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        events = read_until(ws, "approval.required")

    risk = first(events, "risk.assessed")["data"]["risk"]
    assert risk["always_confirm"] is True
    assert risk["reversible"] is False
    assert risk["band"] in ("high", "critical")
    assert risk["factors"], "a score with no reasoning is a number to click past"

    client.post(f"/session/{session_id}/kill")


def test_risk_does_not_gate_anything_by_itself(client, workspace):
    """A high score must not block an action the permission engine allowed, and
    a low one must not clear an always-confirm action."""
    session_id = start_session(client, workspace, READ_WRITE_DELETE_SCRIPT)

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        events = read_until(ws, "approval.required")

    # The auto-approved write earlier in the script still resolved automatically
    # despite carrying a nonzero score, and the delete still stopped.
    resolved = [e for e in events if e["type"] == "approval.resolved"]
    assert any(e["data"].get("auto") for e in resolved)
    assert first(events, "approval.required")["data"]["action"]["action_type"] == "file.delete"

    client.post(f"/session/{session_id}/kill")


def test_an_older_client_ignoring_risk_assessed_still_works(client, workspace):
    """The additive-protocol claim: new event types are not breaking changes."""
    session_id = start_session(client, workspace, READ_WRITE_DELETE_SCRIPT)

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        events = read_until(ws, "approval.required")

    # Drop every frame a pre-risk client would not recognise; the remaining
    # stream must still be a coherent, gapless-in-order session.
    known = [e for e in events if e["type"] != "risk.assessed"]
    seqs = [e["seq"] for e in known]
    assert seqs == sorted(seqs)
    assert "approval.required" in types(known)

    client.post(f"/session/{session_id}/kill")
