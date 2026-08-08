"""Shared helpers for the WebSocket end-to-end tests."""

from __future__ import annotations

import time
from typing import Any

#: A three-step plan that exercises every interesting branch in one run: an
#: auto-approved read, an auto-approved write that produces a diff, and a
#: delete that the always-confirm tier must block.
READ_WRITE_DELETE_SCRIPT: list[dict[str, Any]] = [
    {
        "description": "Read the project README",
        "tool": "file_editor",
        "params": {"op": "read", "path": "README.md"},
    },
    {
        "description": "Write the greeting module",
        "tool": "file_editor",
        "params": {
            "op": "write",
            "path": "greeting.py",
            "content": 'def greet(name):\n    return f"Hello, {name}!"\n',
        },
    },
    {
        "description": "Remove the obsolete scratch file",
        "tool": "file_editor",
        "params": {"op": "delete", "path": "scratch.tmp"},
    },
]

TERMINAL_TYPES = {"session.complete", "session.error"}

#: Guards against a hung test blocking the suite if the stream never reaches
#: the event we are waiting for.
MAX_EVENTS = 500


def start_session(client, workspace, script, *, task: str = "demo task", **overrides) -> str:
    body = {"task": task, "workspace": str(workspace), "script": script}
    body.update(overrides)
    response = client.post("/session", json=body)
    assert response.status_code == 201, response.text
    return response.json()["session_id"]


def read_until(ws, *stop_types: str, limit: int = MAX_EVENTS) -> list[dict]:
    """Drain the socket until one of ``stop_types`` arrives, inclusive.

    Also stops on a terminal event so a test waiting for something that never
    comes fails on an assertion rather than hanging.
    """
    stop = set(stop_types) | TERMINAL_TYPES
    events: list[dict] = []
    for _ in range(limit):
        event = ws.receive_json()
        events.append(event)
        if event["type"] in stop:
            return events
    raise AssertionError(f"never saw {stop_types} in {limit} events")


def types(events: list[dict]) -> list[str]:
    return [e["type"] for e in events]


def first(events: list[dict], event_type: str) -> dict:
    for event in events:
        if event["type"] == event_type:
            return event
    raise AssertionError(f"no {event_type} in {types(events)}")


def statuses(events: list[dict]) -> list[str]:
    return [e["data"]["status"] for e in events if e["type"] == "session.status"]


def assert_parked(manager, session_id: str, settle_s: float = 0.15) -> None:
    """Assert the executor is genuinely blocked, not merely slow.

    Reading from the socket to prove nothing arrives would hang forever, so
    this watches the hub's sequence counter instead: if it does not move while
    the event loop is free to run, nothing is being emitted.
    """
    hub = manager.get(session_id).hub
    before = hub.last_seq
    time.sleep(settle_s)
    assert hub.last_seq == before, "session emitted events while it should have been blocked"
