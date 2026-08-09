"""Provenance: git blame for AI.

Which lines did the agent write, which did you, and when? The enterprise
question the 2026 research keeps raising is "what did the agent actually
write, and can I audit it" -- and no shipping IDE answers it.

The hard part is not recording attribution, it is *keeping* it once a human
edits the file underneath. Attribution that silently drifts is worse than none,
because it looks authoritative while being wrong. So the rule here is: survive
what can be survived, and decay confidence for the rest rather than pretending.
"""

from __future__ import annotations

from sani_core.provenance import (
    Attribution,
    FileProvenance,
    WorkspaceProvenance,
    remap_after_edit,
)


def agent(session: str = "ses_1", at: float = 100.0) -> Attribution:
    return Attribution(session_id=session, model="test-model", at=at)


# ---- recording ---------------------------------------------------------------


def test_a_fresh_file_has_no_attribution():
    file = FileProvenance(path="a.py")
    assert file.agent_lines == 0
    assert file.summary()["agent_pct"] == 0.0


def test_recording_an_agent_write_attributes_the_written_lines():
    file = FileProvenance(path="a.py")
    file.record_agent_lines([0, 1, 2], agent(), total_lines=5)

    assert file.agent_lines == 3
    assert file.human_lines == 2
    assert file.summary()["agent_pct"] == 60.0


def test_attribution_records_which_session_and_model_wrote_it():
    file = FileProvenance(path="a.py")
    file.record_agent_lines([0], agent(session="ses_abc"), total_lines=1)

    entry = file.lines[0]
    assert entry is not None
    assert entry.session_id == "ses_abc"
    assert entry.model == "test-model"


def test_a_later_write_overwrites_an_earlier_attribution():
    file = FileProvenance(path="a.py")
    file.record_agent_lines([0], agent(session="old", at=1.0), total_lines=2)
    file.record_agent_lines([0], agent(session="new", at=2.0), total_lines=2)

    assert file.lines[0].session_id == "new"


def test_growing_a_file_extends_the_attribution_table():
    file = FileProvenance(path="a.py")
    file.record_agent_lines([0], agent(), total_lines=1)
    file.record_agent_lines([4], agent(), total_lines=5)

    assert len(file.lines) == 5
    assert file.lines[4] is not None
    # The lines the agent did not touch stay unattributed rather than becoming
    # agent-authored by proximity.
    assert file.lines[2] is None


# ---- surviving human edits ---------------------------------------------------


def test_an_unchanged_file_keeps_its_attribution_exactly():
    file = FileProvenance(path="a.py")
    file.record_agent_lines([0, 1], agent(), total_lines=3)
    text = "a\nb\nc"

    remapped = remap_after_edit(file, text, text)
    assert remapped.agent_lines == 2
    assert remapped.lines[0].confidence == 1.0


def test_inserting_a_line_above_shifts_attribution_down():
    """The core case. A human adds an import at the top; the agent's function
    is still the agent's function, just two lines lower."""
    file = FileProvenance(path="a.py")
    file.record_agent_lines([0, 1], agent(), total_lines=2)

    remapped = remap_after_edit(file, "def f():\n    pass", "import os\n\ndef f():\n    pass")

    assert remapped.lines[0] is None, "the new import is the human's"
    assert remapped.lines[1] is None
    assert remapped.lines[2] is not None, "the agent's lines moved down, not away"
    assert remapped.lines[3] is not None


def test_deleting_a_line_removes_only_that_attribution():
    file = FileProvenance(path="a.py")
    file.record_agent_lines([0, 1, 2], agent(), total_lines=3)

    remapped = remap_after_edit(file, "a\nb\nc", "a\nc")

    assert len(remapped.lines) == 2
    assert remapped.agent_lines == 2


def test_a_human_rewriting_an_agent_line_takes_ownership_of_it():
    file = FileProvenance(path="a.py")
    file.record_agent_lines([0, 1], agent(), total_lines=2)

    remapped = remap_after_edit(file, "a\nb", "a\nEDITED")

    assert remapped.lines[0] is not None, "the untouched line is still the agent's"
    assert remapped.lines[1] is None, "the rewritten line is now the human's"


def test_surviving_attribution_loses_confidence_when_the_file_moved_around():
    """Honesty rule: a range that survived an edit is less certain than one that
    was never disturbed, and the number has to say so."""
    file = FileProvenance(path="a.py")
    file.record_agent_lines([0], agent(), total_lines=1)

    remapped = remap_after_edit(file, "a", "prefix\na")
    survivor = remapped.lines[1]

    assert survivor is not None
    assert survivor.confidence < 1.0


def test_confidence_decays_further_across_repeated_edits():
    file = FileProvenance(path="a.py")
    file.record_agent_lines([0], agent(), total_lines=1)

    once = remap_after_edit(file, "a", "x\na")
    twice = remap_after_edit(once, "x\na", "y\nx\na")

    assert twice.lines[2].confidence < once.lines[1].confidence


def test_attribution_is_dropped_once_confidence_collapses():
    # Past a point, claiming authorship is a guess dressed as a record.
    file = FileProvenance(path="a.py")
    file.record_agent_lines([0], agent(), total_lines=1)

    text = "a"
    current = file
    for index in range(40):
        new_text = f"line{index}\n{text}"
        current = remap_after_edit(current, text, new_text)
        text = new_text

    assert current.agent_lines == 0, "a claim nobody can stand behind is dropped"


def test_remapping_an_empty_file_does_not_explode():
    assert remap_after_edit(FileProvenance(path="a.py"), "", "").lines == []


# ---- workspace ---------------------------------------------------------------


def test_the_workspace_aggregates_across_files():
    workspace = WorkspaceProvenance()
    workspace.file("a.py").record_agent_lines([0, 1], agent(), total_lines=2)
    workspace.file("b.py").record_agent_lines([0], agent(), total_lines=4)

    board = workspace.summary()
    assert board["files"] == 2
    assert board["agent_lines"] == 3
    assert board["total_lines"] == 6
    assert board["agent_pct"] == 50.0


def test_an_empty_workspace_summarises_without_dividing_by_zero():
    board = WorkspaceProvenance().summary()
    assert board["files"] == 0
    assert board["agent_pct"] == 0.0


def test_it_serialises_to_plain_json():
    workspace = WorkspaceProvenance()
    workspace.file("a.py").record_agent_lines([0], agent(), total_lines=2)

    payload = workspace.to_dict()
    assert "files" in payload
    assert payload["files"]["a.py"]["agent_lines"] == 1
    assert isinstance(payload["files"]["a.py"]["ranges"], list)


def test_ranges_collapse_adjacent_lines_from_the_same_session():
    """The UI paints ranges, not individual lines: 400 consecutive entries would
    be 400 decorations for one visual block."""
    file = FileProvenance(path="a.py")
    file.record_agent_lines([0, 1, 2, 5], agent(session="ses_x"), total_lines=6)

    ranges = file.to_dict()["ranges"]
    assert [(r["start"], r["end"]) for r in ranges] == [(0, 2), (5, 5)]
