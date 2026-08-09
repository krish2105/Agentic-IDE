"""Replay: turning an event log back into a navigable timeline.

The log is already monotonic and gapless because reconnect depends on it, so
replay is the same primitive pointed at the past. What it needs on top is
*keyframes* -- the handful of seqs a human actually wants to jump between --
and those are computed here rather than in a client, because two clients
computing them independently is two chances to disagree.
"""

from __future__ import annotations

from sani_core.replay import Keyframe, build_timeline, keyframes_from


def event(seq: int, type_: str, data: dict | None = None, ts: float = 0.0) -> dict:
    return {
        "v": 1,
        "seq": seq,
        "session_id": "ses_x",
        "ts": ts or float(seq),
        "type": type_,
        "data": data or {},
    }


RUN = [
    event(1, "session.status", {"status": "planning"}),
    event(2, "agent.message.delta", {"text": "think"}),
    event(3, "rag.retrieved", {"chunks": [{"path": "a.py"}]}),
    event(4, "plan.proposed", {"plan": {"steps": [{}, {}]}}),
    event(5, "session.status", {"status": "executing"}),
    event(6, "tool.proposed", {"action": {"action_type": "file.write"}}),
    event(7, "approval.resolved", {"auto": True}),
    event(8, "diff.generated", {"diff": {"path": "greeting.py"}}),
    event(9, "tool.proposed", {"action": {"action_type": "file.delete"}}),
    event(10, "approval.required", {"action": {"summary": "Delete scratch.tmp"}}),
    event(11, "approval.resolved", {"auto": False, "approved": True}),
    event(12, "tool.result", {"result": {"ok": False}}),
    event(13, "session.complete", {"status": "complete", "elapsed_s": 2.5}),
]


# ---- keyframes ---------------------------------------------------------------


def test_keyframes_pick_out_the_moments_a_human_would_scrub_to():
    frames = keyframes_from(RUN)
    kinds = [frame.kind for frame in frames]

    # A plan being proposed, a human decision, a file changing, a failure and
    # the end. Not every event -- the point is a shortlist.
    assert "plan" in kinds
    assert "approval" in kinds
    assert "diff" in kinds
    assert "terminal" in kinds


def test_an_approval_that_stopped_for_a_human_outranks_an_auto_approval():
    frames = keyframes_from(RUN)
    approvals = [frame for frame in frames if frame.kind == "approval"]

    # seq 7 was auto-approved and seq 10 parked on a human. Only the one that
    # actually asked something of the user is worth a marker.
    assert [frame.seq for frame in approvals] == [10]


def test_a_failed_tool_result_is_a_keyframe():
    frames = keyframes_from(RUN)
    failures = [frame for frame in frames if frame.kind == "failure"]
    assert [frame.seq for frame in failures] == [12]


def test_a_successful_tool_result_is_not_a_keyframe():
    log = [event(1, "tool.result", {"result": {"ok": True}})]
    assert keyframes_from(log) == []


def test_keyframes_are_ordered_by_seq():
    frames = keyframes_from(RUN)
    assert [frame.seq for frame in frames] == sorted(frame.seq for frame in frames)


def test_keyframes_carry_a_human_readable_label():
    frames = keyframes_from(RUN)
    approval = next(frame for frame in frames if frame.kind == "approval")
    assert "Delete scratch.tmp" in approval.label


def test_an_empty_log_yields_no_keyframes():
    assert keyframes_from([]) == []


# ---- timeline ----------------------------------------------------------------


def test_build_timeline_reports_the_span_and_the_frames():
    timeline = build_timeline("ses_x", RUN)

    assert timeline["session_id"] == "ses_x"
    assert timeline["first_seq"] == 1
    assert timeline["last_seq"] == 13
    assert timeline["count"] == 13
    assert timeline["keyframes"]


def test_build_timeline_reports_duration_from_the_event_timestamps():
    timeline = build_timeline("ses_x", RUN)
    # ts is seq-derived in the fixture: 1.0 through 13.0.
    assert timeline["duration_s"] == 12.0


def test_build_timeline_on_an_empty_log_is_still_well_formed():
    # A session that has only just been created has no events yet, and the
    # scrubber must render rather than crash.
    timeline = build_timeline("ses_new", [])

    assert timeline["session_id"] == "ses_new"
    assert timeline["first_seq"] == 0
    assert timeline["last_seq"] == 0
    assert timeline["count"] == 0
    assert timeline["duration_s"] == 0.0
    assert timeline["keyframes"] == []


def test_keyframe_serialises_to_plain_json():
    frame = Keyframe(seq=4, kind="plan", label="Plan proposed — 2 steps", ts=4.0)
    assert frame.to_dict() == {
        "seq": 4,
        "kind": "plan",
        "label": "Plan proposed — 2 steps",
        "ts": 4.0,
    }
