"""A failing step must not take the whole session with it.

`CLAUDE.md` documents this: "A failing tool call marks its step `failed` and
the plan continues." That held only when a tool *returned* an unsuccessful
result. A tool that **raised** -- which is what reading a missing file does --
escaped the step and killed the session.

It is an easy failure to ship because the common demo path never hits it, and
an expensive one to hit in practice: the agent guesses a filename that does not
exist on step one, and everything after it is discarded rather than attempted.
"""

from __future__ import annotations

from .helpers import first, read_until, start_session, types

#: Step 0 reads a file that is not there. Steps 1 and 2 are perfectly valid and
#: must still run.
MISSING_FILE_FIRST = [
    {
        "description": "Read a file that does not exist",
        "tool": "file_editor",
        "params": {"op": "read", "path": "definitely-not-here.md"},
    },
    {
        "description": "Write the greeting module",
        "tool": "file_editor",
        "params": {"op": "write", "path": "greeting.py", "content": "x = 1\n"},
    },
    {
        "description": "Read it back",
        "tool": "file_editor",
        "params": {"op": "read", "path": "greeting.py"},
    },
]


def test_a_raising_tool_fails_its_step_not_the_session(client, workspace):
    session_id = start_session(client, workspace, MISSING_FILE_FIRST)

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        events = read_until(ws, "session.complete")

    assert "session.error" not in types(events), "the session must not die on one bad step"
    assert first(events, "session.complete")["data"]["status"] == "complete"


def test_the_steps_after_a_failure_still_run(client, workspace):
    session_id = start_session(client, workspace, MISSING_FILE_FIRST)

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        events = read_until(ws, "session.complete")

    completed = [e for e in events if e["type"] == "plan.step.completed"]
    statuses = [e["data"]["step"]["status"] for e in completed]

    assert statuses[0] == "failed"
    assert statuses[1] == "complete", "the write after the failure must still happen"
    assert (workspace / "greeting.py").exists()


def test_the_failure_is_reported_as_a_tool_result_not_swallowed(client, workspace):
    """A step that quietly disappears is worse than one that failed loudly."""
    session_id = start_session(client, workspace, MISSING_FILE_FIRST)

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        events = read_until(ws, "session.complete")

    results = [e for e in events if e["type"] == "tool.result"]
    failed = [e for e in results if e["data"]["result"]["ok"] is False]

    assert failed, "the failing step must still emit a result"
    assert "definitely-not-here.md" in failed[0]["data"]["result"]["summary"]


def test_an_unknown_tool_still_fails_the_whole_session(client, workspace):
    """The deliberate exception to the rule above.

    A missing file is a runtime problem with one step. A tool the session was
    never given is structural: every step using it would fail identically, and
    the useful signal is "your tool configuration is wrong" rather than the same
    per-step failure repeated. This behaviour predates the fix and is kept.
    """
    session_id = start_session(
        client,
        workspace,
        [{"description": "Use a tool that does not exist", "tool": "telepathy", "params": {}}],
    )

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        events = read_until(ws, "session.error")

    assert first(events, "session.error")["data"]["status"] == "failed"
    assert "telepathy" in first(events, "session.error")["data"]["error"]
