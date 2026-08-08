"""The Phase 0 gate.

Spec Section 14: no later phase starts until the WebSocket stream and the
approval endpoint are proven end to end. These are the tests that prove it.
"""

from __future__ import annotations

from .helpers import (
    READ_WRITE_DELETE_SCRIPT,
    assert_parked,
    first,
    read_until,
    start_session,
    statuses,
    types,
)


def test_stream_blocks_on_approval_then_completes(client, manager, workspace):
    """Plan -> auto-approved work -> block on delete -> approve -> finish.

    All of it on one continuously open socket, which is the part that matters:
    the client that asked for the session is the client that gets the answer.
    """
    session_id = start_session(client, workspace, READ_WRITE_DELETE_SCRIPT)

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        before_approval = read_until(ws, "approval.required")
        # The status flip follows the approval request immediately.
        before_approval.append(ws.receive_json())
        seen = types(before_approval)

        # Planning is streamed and shown before anything executes (Section 8.3).
        assert seen[0] == "session.status"
        assert before_approval[0]["data"]["status"] == "planning"
        assert "agent.message.delta" in seen
        assert seen.index("plan.proposed") < seen.index("plan.step.started")

        plan = first(before_approval, "plan.proposed")["data"]["plan"]
        assert len(plan["steps"]) == 3

        # Every action is disclosed, including the two that were auto-approved.
        assert seen.count("tool.proposed") == 3
        assert seen.count("approval.resolved") == 2
        assert all(
            e["data"]["auto"] is True
            for e in before_approval
            if e["type"] == "approval.resolved"
        )

        # The write produced a diff before the block.
        diff_event = first(before_approval, "diff.generated")
        assert diff_event["data"]["diff"]["path"] == "greeting.py"
        assert diff_event["data"]["diff"]["is_new_file"] is True

        # The delete is the always-confirm action that stopped the run.
        approval = first(before_approval, "approval.required")["data"]
        action_id = approval["action"]["id"]
        assert approval["action"]["action_type"] == "file.delete"
        assert approval["decision"]["requires_approval"] is True
        assert "always-confirm" in approval["decision"]["reason"]
        assert statuses(before_approval)[-1] == "blocked-on-approval"

        # It is really blocked: nothing further is emitted, the earlier steps
        # landed on disk, and the delete has not happened.
        assert_parked(manager, session_id)
        assert (workspace / "greeting.py").exists()
        assert (workspace / "scratch.tmp").exists()

        state = client.get(f"/session/{session_id}").json()
        assert state["status"] == "blocked-on-approval"
        assert state["pending_action"]["id"] == action_id

        # Approve over HTTP; the answer arrives on the socket already open.
        ack = client.post(f"/session/{session_id}/approve", json={"action_id": action_id})
        assert ack.status_code == 200, ack.text
        assert ack.json()["approved"] is True

        after = read_until(ws, "session.complete")
        after_types = types(after)
        assert after_types[0] == "approval.resolved"
        assert after[0]["data"]["approved"] is True
        assert after[0]["data"]["auto"] is False
        assert "tool.result" in after_types
        assert after_types[-1] == "session.complete"

    assert not (workspace / "scratch.tmp").exists()
    assert client.get(f"/session/{session_id}").json()["status"] == "complete"


def test_rejecting_an_action_skips_the_step_and_leaves_the_file(client, manager, workspace):
    session_id = start_session(client, workspace, READ_WRITE_DELETE_SCRIPT)

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        events = read_until(ws, "approval.required")
        action_id = first(events, "approval.required")["data"]["action"]["id"]

        response = client.post(
            f"/session/{session_id}/reject",
            json={"action_id": action_id, "reason": "keep the scratch file"},
        )
        assert response.status_code == 200, response.text

        tail = read_until(ws, "session.complete")
        resolved = first(tail, "approval.resolved")["data"]
        assert resolved["approved"] is False
        assert resolved["note"] == "keep the scratch file"

    # Rejection is not failure: the session still completes, minus that step.
    state = client.get(f"/session/{session_id}").json()
    assert state["status"] == "complete"
    assert [s["status"] for s in state["plan"]["steps"]] == ["complete", "complete", "rejected"]
    assert (workspace / "scratch.tmp").exists()

    # A rejection also revokes earned autonomy for that action type.
    trust = client.get(f"/session/{session_id}/trust").json()["tiers"]
    assert trust["file.delete"]["consecutive_approvals"] == 0
    assert trust["file.delete"]["auto_approve"] is False


def test_reconnect_replays_exactly_what_was_missed(client, manager, workspace):
    """Drop mid-run, approve while disconnected, reattach with from_seq."""
    session_id = start_session(client, workspace, READ_WRITE_DELETE_SCRIPT)

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        early = read_until(ws, "plan.proposed")
    last_seq = early[-1]["seq"]
    assert [e["seq"] for e in early] == list(range(1, len(early) + 1))

    # While nobody is listening, the run continues and parks on the delete.
    with client.websocket_connect(f"/session/{session_id}/stream?from_seq={last_seq}") as ws:
        missed = read_until(ws, "approval.required")
        assert missed[0]["seq"] == last_seq + 1, "replay must start at the first missed event"
        assert "plan.proposed" not in types(missed), "already-seen events must not repeat"

        action_id = first(missed, "approval.required")["data"]["action"]["id"]
        client.post(f"/session/{session_id}/approve", json={"action_id": action_id})
        read_until(ws, "session.complete")

    # Replaying from zero on a finished session yields a gapless log.
    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        full = read_until(ws, "session.complete")

    seqs = [e["seq"] for e in full]
    assert seqs == list(range(1, len(seqs) + 1)), "sequence must be gapless"
    assert len(seqs) == len(set(seqs)), "sequence must have no duplicates"
    assert types(full)[-1] == "session.complete"


def test_two_clients_receive_the_same_stream(client, manager, workspace):
    """Mission Control and an editor watch one session at the same time."""
    session_id = start_session(client, workspace, READ_WRITE_DELETE_SCRIPT)

    with client.websocket_connect(f"/session/{session_id}/stream") as ws_a:
        with client.websocket_connect(f"/session/{session_id}/stream") as ws_b:
            events_a = read_until(ws_a, "approval.required")
            events_b = read_until(ws_b, "approval.required")

            assert [e["seq"] for e in events_a] == [e["seq"] for e in events_b]
            assert types(events_a) == types(events_b)

            action_id = first(events_a, "approval.required")["data"]["action"]["id"]
            client.post(f"/session/{session_id}/approve", json={"action_id": action_id})

            tail_a = read_until(ws_a, "session.complete")
            tail_b = read_until(ws_b, "session.complete")
            assert [e["seq"] for e in tail_a] == [e["seq"] for e in tail_b]


def test_partial_hunk_approval_applies_only_selected_hunks(client, manager, workspace):
    """Per-hunk accept/reject (Section 5) writes only what the user kept."""
    target = workspace / "config.py"
    target.write_text("\n".join(f"line {i}" for i in range(1, 31)) + "\n")

    edited = target.read_text().splitlines()
    edited[0] = "line 1 CHANGED AT TOP"
    edited[-1] = "line 30 CHANGED AT BOTTOM"
    script = [
        {
            "description": "Edit config in two places",
            "tool": "file_editor",
            "params": {"op": "write", "path": "config.py", "content": "\n".join(edited) + "\n"},
        }
    ]
    # Writes are auto-approved by default, so this session opts out at creation
    # time -- patching trust after POST /session would race the first step.
    session_id = start_session(
        client, workspace, script, trust_overrides={"file.write": False}
    )

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        events = read_until(ws, "approval.required")
        action = first(events, "approval.required")["data"]["action"]
        hunks = action["diff"]["hunks"]
        assert len(hunks) == 2, "edits at both ends of the file should be separate hunks"

        client.post(
            f"/session/{session_id}/approve",
            json={"action_id": action["id"], "hunk_ids": [hunks[0]["id"]]},
        )
        read_until(ws, "session.complete")

    written = target.read_text()
    assert "line 1 CHANGED AT TOP" in written
    assert "line 30 CHANGED AT BOTTOM" not in written
    assert written.rstrip().endswith("line 30")
