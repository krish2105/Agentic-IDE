"""`critique.emitted` on the wire.

The critic is a second opinion on the agent's own output, for the documented
top failure of 2026 agentic coding: code that looks right. It is advisory --
it cannot approve, reject, or delay anything.
"""

from __future__ import annotations

import pytest

from .helpers import READ_WRITE_DELETE_SCRIPT, first, read_until, start_session, types


@pytest.fixture
def critic_on(monkeypatch):
    monkeypatch.setenv("SANI_CRITIC", "scripted")


def test_no_critique_is_emitted_when_the_critic_is_off(client, workspace):
    """Off by default: a second inference per gated action costs real money."""
    session_id = start_session(client, workspace, READ_WRITE_DELETE_SCRIPT)

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        events = read_until(ws, "approval.required")

    assert "critique.emitted" not in types(events)
    client.post(f"/session/{session_id}/kill")


def test_a_critique_is_emitted_before_the_approval(client, workspace, critic_on):
    session_id = start_session(client, workspace, READ_WRITE_DELETE_SCRIPT)

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        events = read_until(ws, "approval.required")

    seen = types(events)
    assert "critique.emitted" in seen
    assert seen.index("critique.emitted") < seen.index("approval.required")

    client.post(f"/session/{session_id}/kill")


def test_the_critique_names_the_action_it_reviewed(client, workspace, critic_on):
    session_id = start_session(client, workspace, READ_WRITE_DELETE_SCRIPT)

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        events = read_until(ws, "approval.required")

    critique = first(events, "critique.emitted")["data"]
    approval = first(events, "approval.required")["data"]
    assert critique["action_id"] == approval["action"]["id"]
    assert critique["critique"]["reviewed_by"] == "scripted"

    client.post(f"/session/{session_id}/kill")


def test_a_delete_only_change_is_flagged_by_the_critic(client, workspace, critic_on):
    """The shape of a model regenerating a file it never fully saw."""
    session_id = start_session(client, workspace, READ_WRITE_DELETE_SCRIPT)

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        events = read_until(ws, "approval.required")

    critique = first(events, "critique.emitted")["data"]["critique"]
    assert critique["clean"] is False
    assert critique["concerns"]

    client.post(f"/session/{session_id}/kill")


def test_the_critique_does_not_gate_anything(client, workspace, critic_on):
    """Advisory means advisory: a concerned critic must not block, and a clean
    one must not clear an always-confirm action."""
    session_id = start_session(client, workspace, READ_WRITE_DELETE_SCRIPT)

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        events = read_until(ws, "approval.required")
        action_id = first(events, "approval.required")["data"]["action"]["id"]
        # The delete still stopped for a human despite the critique existing,
        # and approving still works normally.
        assert (
            client.post(
                f"/session/{session_id}/approve", json={"action_id": action_id}
            ).status_code
            == 200
        )
        read_until(ws, "session.complete")


def test_a_critic_that_throws_never_blocks_the_approval(client, workspace, monkeypatch):
    """A broken critic must not be what stops a human being asked."""
    import sani_core.critic as critic_module

    class Exploding:
        name = "exploding"

        async def review(self, action, task):
            raise RuntimeError("critic is down")

    monkeypatch.setattr(critic_module, "build_critic", lambda kind=None: Exploding())
    import sani_server.manager as manager_module

    monkeypatch.setattr(manager_module, "build_critic", lambda kind=None: Exploding())

    session_id = start_session(client, workspace, READ_WRITE_DELETE_SCRIPT)

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        events = read_until(ws, "approval.required")

    # The approval still arrived, and the failure was reported rather than
    # swallowed.
    assert "approval.required" in types(events)
    critique = first(events, "critique.emitted")["data"]["critique"]
    assert critique["error"].startswith("RuntimeError")
    assert critique["reviewed_by"] is None

    client.post(f"/session/{session_id}/kill")
