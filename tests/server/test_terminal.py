"""The interactive terminal, driven over its real WebSocket."""

from __future__ import annotations

import pytest
from sani_server.sandbox import LocalSandbox, build_sandbox
from sani_server.sandbox.base import SandboxError

from .helpers import start_session

READ_LIMIT = 200


def read_until_text(ws, needle: str, limit: int = READ_LIMIT) -> str:
    """Accumulate terminal output until ``needle`` shows up."""
    buffer = ""
    for _ in range(limit):
        message = ws.receive_json()
        if message["type"] == "output":
            buffer += message["data"]
            if needle in buffer:
                return buffer
        elif message["type"] == "exit":
            raise AssertionError(f"shell exited before {needle!r}; saw {buffer!r}")
    raise AssertionError(f"never saw {needle!r}; saw {buffer!r}")


@pytest.fixture
def session_id(client, workspace):
    return start_session(client, workspace, [])


def test_terminal_runs_a_command_and_returns_its_output(client, session_id):
    with client.websocket_connect(f"/session/{session_id}/terminal") as ws:
        ready = ws.receive_json()
        assert ready["type"] == "ready"
        assert ready["sandbox"]["kind"] == "local"

        ws.send_json({"type": "input", "data": "echo phase-one-works\r"})
        assert "phase-one-works" in read_until_text(ws, "phase-one-works")


def test_the_terminal_starts_in_the_session_workspace(client, session_id, workspace):
    with client.websocket_connect(f"/session/{session_id}/terminal") as ws:
        ws.receive_json()
        ws.send_json({"type": "input", "data": "pwd\r"})
        output = read_until_text(ws, str(workspace))
    assert str(workspace) in output


def test_the_terminal_sees_files_the_agent_wrote(client, session_id, workspace):
    (workspace / "written_by_agent.py").write_text("x = 1\n")

    with client.websocket_connect(f"/session/{session_id}/terminal") as ws:
        ws.receive_json()
        ws.send_json({"type": "input", "data": "ls\r"})
        assert "written_by_agent.py" in read_until_text(ws, "written_by_agent.py")


def test_resize_is_applied_to_the_pty(client, session_id):
    with client.websocket_connect(f"/session/{session_id}/terminal?cols=80&rows=24") as ws:
        ws.receive_json()
        ws.send_json({"type": "resize", "cols": 132, "rows": 43})
        ws.send_json({"type": "input", "data": "stty size\r"})
        assert "43 132" in read_until_text(ws, "43 132")


def test_exiting_the_shell_reports_exit(client, session_id):
    with client.websocket_connect(f"/session/{session_id}/terminal") as ws:
        ws.receive_json()
        ws.send_json({"type": "input", "data": "exit\r"})
        for _ in range(READ_LIMIT):
            if ws.receive_json()["type"] == "exit":
                return
    raise AssertionError("shell exit was never reported")


def test_terminal_on_an_unknown_session_is_refused(client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/session/ses_nope/terminal") as ws:
            ws.receive_json()
    assert exc.value.code == 4404


def test_local_sandbox_is_honest_about_providing_no_isolation(tmp_path):
    described = LocalSandbox(tmp_path).describe()
    assert described["kind"] == "local"
    assert described["isolated"] is False


def test_sandbox_selection(tmp_path):
    assert build_sandbox(tmp_path, "ses_x").kind == "local"
    assert build_sandbox(tmp_path, "ses_x", "docker").kind == "docker"
    with pytest.raises(SandboxError, match="unknown sandbox"):
        build_sandbox(tmp_path, "ses_x", "kubernetes")


def test_docker_sandbox_reports_itself_as_unverified(tmp_path):
    """It has never run against a live daemon; the description must say so."""
    described = build_sandbox(tmp_path, "ses_abc", "docker").describe()
    assert described["container"] == "sani-ses_abc"
    assert described["isolated"] is True
    assert described["verified"] is False
