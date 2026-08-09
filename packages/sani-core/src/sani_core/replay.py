"""Replay: an event log turned back into a navigable timeline.

The log is already monotonic and gapless -- reconnect depends on it -- so
replay is that same primitive pointed at the past rather than at a dropped
connection. Scrubbing a finished session is just feeding the reducer history
with a clock attached.

What replay needs beyond the raw log is *keyframes*: the handful of sequence
numbers a human actually wants to jump between. Those live here, in the core,
for the same reason risk and provenance do -- two clients computing them
independently is two chances to disagree about what mattered in a run.

Pure functions over plain dicts. No transport, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

#: What kind of moment a marker represents. Ordered roughly by how much a
#: reviewer cares: a human decision beats a file write beats a plan.
KeyframeKind = Literal["plan", "approval", "diff", "failure", "terminal"]


@dataclass(slots=True, frozen=True)
class Keyframe:
    """One scrubbable moment in a session."""

    seq: int
    kind: KeyframeKind
    label: str
    ts: float

    def to_dict(self) -> dict[str, Any]:
        return {"seq": self.seq, "kind": self.kind, "label": self.label, "ts": self.ts}


def _plan_label(data: dict) -> str:
    steps = (data.get("plan") or {}).get("steps") or []
    return f"Plan proposed — {len(steps)} step{'s' if len(steps) != 1 else ''}"


def _approval_label(data: dict) -> str:
    action = data.get("action") or {}
    summary = action.get("summary") or action.get("action_type") or "action"
    return f"Approval required — {summary}"


def _diff_label(data: dict) -> str:
    diff = data.get("diff") or {}
    path = diff.get("path") or "a file"
    return f"Changed {path}"


def _terminal_label(event_type: str, data: dict) -> str:
    if event_type == "session.error":
        return f"Failed — {data.get('error', 'unknown error')}"
    status = data.get("status", "complete")
    return "Terminated" if status == "killed" else "Complete"


def keyframes_from(events: list[dict]) -> list[Keyframe]:
    """The shortlist of moments worth jumping to.

    Deliberately *not* every event. A scrubber whose every pixel is a marker
    is a scrubber with no markers -- the value is in the selection.
    """
    frames: list[Keyframe] = []

    for event in events:
        event_type = event.get("type")
        data = event.get("data") or {}
        seq = event.get("seq", 0)
        ts = float(event.get("ts", 0.0))

        if event_type == "plan.proposed":
            frames.append(Keyframe(seq, "plan", _plan_label(data), ts))

        elif event_type == "approval.required":
            # Only approvals that actually stopped for a human. An auto-approved
            # action still emits approval.resolved with auto=true, and marking
            # those would bury the decisions the reviewer came here to find.
            frames.append(Keyframe(seq, "approval", _approval_label(data), ts))

        elif event_type == "diff.generated":
            frames.append(Keyframe(seq, "diff", _diff_label(data), ts))

        elif event_type == "tool.result":
            result = data.get("result") or {}
            if result.get("ok") is False:
                summary = result.get("summary") or result.get("error") or "tool failed"
                frames.append(Keyframe(seq, "failure", f"Failed — {summary}", ts))

        elif event_type in ("session.complete", "session.error"):
            frames.append(Keyframe(seq, "terminal", _terminal_label(event_type, data), ts))

    frames.sort(key=lambda frame: frame.seq)
    return frames


def build_timeline(session_id: str, events: list[dict]) -> dict[str, Any]:
    """The full replay payload for one session.

    Returns the raw log alongside the computed markers. The client folds the
    events through the reducer it already has -- it does not reimplement the
    fold, which is what keeps the web IDE and the extension showing the same
    history.
    """
    if not events:
        return {
            "session_id": session_id,
            "first_seq": 0,
            "last_seq": 0,
            "count": 0,
            "duration_s": 0.0,
            "keyframes": [],
            "events": [],
        }

    first = events[0]
    last = events[-1]

    return {
        "session_id": session_id,
        "first_seq": first.get("seq", 0),
        "last_seq": last.get("seq", 0),
        "count": len(events),
        "duration_s": round(float(last.get("ts", 0.0)) - float(first.get("ts", 0.0)), 3),
        "keyframes": [frame.to_dict() for frame in keyframes_from(events)],
        "events": events,
    }
