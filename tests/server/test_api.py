"""The rest of the Section 7 surface: errors, diff, trust, mission control."""

from __future__ import annotations

from .helpers import READ_WRITE_DELETE_SCRIPT, first, read_until, start_session, types

ECHO = {"description": "echo", "tool": "shell", "params": {"command": "echo hi"}}


def test_healthz_publishes_the_protocol_contract(client):
    body = client.get("/healthz").json()
    assert body["ok"] is True
    assert body["protocol_version"] == 1
    assert "approval.required" in body["event_types"]
    assert "file.delete" in body["always_confirm"]


def test_create_without_a_workspace_gets_a_scratch_directory(client):
    body = client.post("/session", json={"task": "no workspace given", "script": []}).json()
    assert body["workspace"].rsplit("/", 1)[-1].startswith("sani-ws-")
    assert body["status"] in ("planning", "executing", "complete")


def test_unknown_session_is_404_everywhere(client):
    missing = "ses_doesnotexist"
    assert client.get(f"/session/{missing}").status_code == 404
    assert client.get(f"/session/{missing}/diff").status_code == 404
    assert client.get(f"/session/{missing}/trust").status_code == 404
    assert client.post(f"/session/{missing}/kill").status_code == 404
    response = client.post(f"/session/{missing}/approve", json={"action_id": "act_x"})
    assert response.status_code == 404
    assert response.json()["error"] == "unknown_session"


def test_unknown_and_double_resolved_actions(client, workspace):
    session_id = start_session(client, workspace, READ_WRITE_DELETE_SCRIPT)

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        events = read_until(ws, "approval.required")
        action_id = first(events, "approval.required")["data"]["action"]["id"]

        bogus = client.post(f"/session/{session_id}/approve", json={"action_id": "act_nope"})
        assert bogus.status_code == 404
        assert bogus.json()["error"] == "unknown_action"

        assert client.post(
            f"/session/{session_id}/approve", json={"action_id": action_id}
        ).status_code == 200

        # A double-click on Approve must not re-run the action.
        again = client.post(f"/session/{session_id}/approve", json={"action_id": action_id})
        assert again.status_code == 409
        assert again.json()["error"] == "already_resolved"

        read_until(ws, "session.complete")


def test_invalid_workspace_is_rejected(client, tmp_path):
    response = client.post(
        "/session", json={"task": "bad path", "workspace": str(tmp_path / "nope"), "script": []}
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_workspace"

    forbidden = client.post("/session", json={"task": "root", "workspace": "/", "script": []})
    assert forbidden.status_code == 400


def test_unknown_tool_in_a_plan_fails_the_session_not_the_server(client, workspace):
    script = [{"description": "use a browser", "tool": "browser", "params": {}}]
    session_id = start_session(client, workspace, script)

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        events = read_until(ws, "session.error")

    error = first(events, "session.error")["data"]
    assert error["status"] == "failed"
    assert "browser" in error["error"]
    assert client.get(f"/session/{session_id}").json()["status"] == "failed"


def test_diff_endpoint_returns_per_file_hunks(client, workspace):
    session_id = start_session(client, workspace, READ_WRITE_DELETE_SCRIPT)

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        events = read_until(ws, "approval.required")
        action_id = first(events, "approval.required")["data"]["action"]["id"]
        client.post(f"/session/{session_id}/approve", json={"action_id": action_id})
        read_until(ws, "session.complete")

    files = client.get(f"/session/{session_id}/diff").json()["files"]
    by_path = {f["path"]: f for f in files}

    assert by_path["greeting.py"]["is_new_file"] is True
    assert by_path["greeting.py"]["hunks"][0]["lines"][0].startswith("+")
    assert "+++ b/greeting.py" in by_path["greeting.py"]["unified"]
    assert by_path["scratch.tmp"]["is_delete"] is True


def test_trust_ladder_promotes_after_three_manual_approvals(client, workspace):
    """`echo` is shell.other, which starts un-trusted and has to earn autonomy."""
    script = [dict(ECHO, description=f"echo {i}") for i in range(4)]
    session_id = start_session(client, workspace, script)

    approvals = 0
    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        events = read_until(ws, "approval.required", "session.complete")
        while types(events)[-1] != "session.complete":
            action_id = events[-1]["data"]["action"]["id"]
            client.post(f"/session/{session_id}/approve", json={"action_id": action_id})
            approvals += 1
            events = read_until(ws, "approval.required", "session.complete")

    # Three approvals earn the tier; the fourth step runs unattended.
    assert approvals == 3
    tier = client.get(f"/session/{session_id}/trust").json()["tiers"]["shell.other"]
    assert tier["auto_approve"] is True
    assert tier["consecutive_approvals"] == 3
    assert tier["always_confirm"] is False

    state = client.get(f"/session/{session_id}").json()
    assert [s["status"] for s in state["plan"]["steps"]] == ["complete"] * 4


def test_trust_patch_round_trips_for_an_unlocked_tier(client, workspace):
    session_id = start_session(client, workspace, [])

    body = client.patch(
        f"/session/{session_id}/trust",
        json={"action_type": "shell.other", "auto_approve": True},
    ).json()
    assert body["tiers"]["shell.other"]["auto_approve"] is True

    bad = client.patch(
        f"/session/{session_id}/trust",
        json={"action_type": "not.a.real.type", "auto_approve": True},
    )
    assert bad.status_code == 409
    assert bad.json()["error"] == "invalid_state"


def test_mission_control_lists_every_session_with_its_badge(client, workspace):
    blocked_id = start_session(client, workspace, READ_WRITE_DELETE_SCRIPT)
    quick_id = start_session(client, workspace, [], lifecycle="background")

    with client.websocket_connect(f"/session/{blocked_id}/stream") as ws:
        read_until(ws, "approval.required")

        with client.websocket_connect(f"/session/{quick_id}/stream") as quick_ws:
            read_until(quick_ws, "session.complete")

        board = client.get("/mission-control").json()

    rows = {r["session_id"]: r for r in board["sessions"]}
    assert set(rows) == {blocked_id, quick_id}

    blocked = rows[blocked_id]
    assert blocked["approval_needed"] is True
    assert blocked["status"] == "blocked-on-approval"
    assert blocked["total_steps"] == 3
    assert blocked["current_step"] == 2
    assert blocked["current_step_description"] == "Remove the obsolete scratch file"
    assert blocked["active_tool"] == "file_editor"
    assert blocked["pending_action"]["action_type"] == "file.delete"
    assert blocked["elapsed_s"] >= 0

    assert rows[quick_id]["lifecycle"] == "background"
    assert rows[quick_id]["approval_needed"] is False
    assert board["awaiting_approval"] == 1
    assert board["active"] == 1

    client.post(f"/session/{blocked_id}/kill")


def test_streaming_an_unknown_session_closes_the_socket(client):
    from starlette.websockets import WebSocketDisconnect

    try:
        with client.websocket_connect("/session/ses_nope/stream") as ws:
            ws.receive_json()
        raise AssertionError("expected the socket to be refused")
    except WebSocketDisconnect as exc:
        assert exc.code == 4404
