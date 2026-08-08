"""Phase 3c end to end: a browser session through the real server."""

from __future__ import annotations

import http.server
import threading
from functools import partial

import pytest

from .helpers import assert_parked, first, read_until, start_session, types

pytest.importorskip("playwright.async_api", reason="playwright not installed")

PAGE = """<!doctype html>
<html><body><h1>Sani Studio</h1><p>all systems nominal</p></body></html>
"""


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    root = tmp_path_factory.mktemp("site")
    (root / "index.html").write_text(PAGE)
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/index.html"
    server.shutdown()


def test_a_browser_session_verifies_a_page_and_leaves_a_screenshot(
    client, workspace, site
):
    script = [
        {"description": "open the app", "tool": "browser",
         "params": {"op": "goto", "url": site}},
        {"description": "check it rendered", "tool": "browser",
         "params": {"op": "assert_text", "text": "all systems nominal"}},
        {"description": "capture the result", "tool": "browser",
         "params": {"op": "screenshot", "name": "landing"}},
    ]
    session_id = start_session(
        client,
        workspace,
        script,
        tools=["browser"],
        trust_overrides={"browser.action": True},
    )

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        events = read_until(ws, "session.complete")

    assert types(events)[-1] == "session.complete"
    state = client.get(f"/session/{session_id}").json()
    assert state["status"] == "complete"
    assert [s["status"] for s in state["plan"]["steps"]] == ["complete"] * 3

    # The screenshot is a real artifact inside the workspace...
    results = [e["data"]["result"] for e in events if e["type"] == "tool.result"]
    artifact = next(r["data"]["artifact"] for r in results if r["data"].get("kind") == "image")
    assert (workspace / artifact).exists()

    # ...and the file API serves it, so a client can actually show it.
    raw = client.get(f"/session/{session_id}/file/raw", params={"path": artifact})
    assert raw.status_code == 200
    assert raw.headers["content-type"] == "image/png"
    assert raw.content[:8] == b"\x89PNG\r\n\x1a\n"

    # It shows up in the tree too, rather than hiding in a temp directory.
    paths = [e["path"] for e in client.get(f"/session/{session_id}/files").json()["entries"]]
    assert artifact in paths


def test_navigating_off_the_machine_stops_for_a_human(client, manager, workspace):
    """A browser reaching the internet is the same decision as curl."""
    script = [
        {"description": "visit an external site", "tool": "browser",
         "params": {"op": "goto", "url": "https://example.com"}},
    ]
    session_id = start_session(
        client,
        workspace,
        script,
        tools=["browser"],
        trust_overrides={"browser.action": True},
    )

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        events = read_until(ws, "approval.required")
        approval = first(events, "approval.required")["data"]

        assert approval["action"]["action_type"] == "browser.navigate_external"
        assert approval["action"]["preview"]["leaves_this_machine"] is True
        assert "always-confirm" in approval["decision"]["reason"]
        assert_parked(manager, session_id)

        client.post(
            f"/session/{session_id}/reject",
            json={"action_id": approval["action"]["id"], "reason": "no external calls"},
        )
        read_until(ws, "session.complete")

    state = client.get(f"/session/{session_id}").json()
    assert state["plan"]["steps"][0]["status"] == "rejected"


def test_a_failing_assertion_marks_the_step_failed_and_continues(client, workspace, site):
    script = [
        {"description": "open the app", "tool": "browser",
         "params": {"op": "goto", "url": site}},
        {"description": "check for something absent", "tool": "browser",
         "params": {"op": "assert_text", "text": "catastrophic failure"}},
        {"description": "carry on regardless", "tool": "browser",
         "params": {"op": "text", "selector": "h1"}},
    ]
    session_id = start_session(
        client, workspace, script, tools=["browser"],
        trust_overrides={"browser.action": True},
    )

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        read_until(ws, "session.complete")

    state = client.get(f"/session/{session_id}").json()
    assert [s["status"] for s in state["plan"]["steps"]] == ["complete", "failed", "complete"]
    assert state["status"] == "complete"
