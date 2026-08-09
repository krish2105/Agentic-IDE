"""Blast-radius assessment.

The 2026 research is blunt about this: the top developer frustration with AI
coding is not obviously-bad output, it is code that *looks correct* while being
wrong, and approval flows that show a diff and ask "ok?" without saying what
the action actually reaches.

So the gate gets an answer to "what will this touch, and how hard is it to
undo?" computed *before* execution. It runs on the proposed action only --
``propose()`` is side-effect free and must stay that way, so nothing here may
execute, fetch, or mutate anything.

Scoring is advisory. It informs a human decision; it never widens the
always-confirm tier and never auto-approves.
"""

from __future__ import annotations

from sani_core.actions import ProposedAction
from sani_core.diffs import FileDiff, Hunk
from sani_core.permissions import ActionType
from sani_core.risk import RiskAssessment, assess


def action(
    action_type: ActionType,
    *,
    summary: str = "do a thing",
    preview: dict | None = None,
    diff: FileDiff | None = None,
) -> ProposedAction:
    return ProposedAction(
        action_type=action_type,
        tool="file_editor",
        summary=summary,
        step_index=0,
        preview=preview or {},
        diff=diff,
    )


def diff_with(additions: int, deletions: int, path: str = "a.py") -> FileDiff:
    # additions/deletions are derived from the hunk lines, so the fixture has to
    # produce real +/- lines rather than asserting the counts directly.
    lines = [f"+line {i}" for i in range(additions)] + [
        f"-line {i}" for i in range(deletions)
    ]
    return FileDiff(
        path=path,
        hunks=[
            Hunk(
                id="h1",
                old_start=0,
                old_lines=deletions,
                new_start=0,
                new_lines=additions,
                lines=lines,
            )
        ],
    )


# ---- reversibility -----------------------------------------------------------


def test_a_delete_is_irreversible_and_scores_high():
    result = assess(action(ActionType.FILE_DELETE, summary="Delete scratch.tmp"))
    assert result.reversible is False
    assert result.score >= 70


def test_a_file_read_is_the_least_risky_thing_there_is():
    result = assess(action(ActionType.FILE_READ, summary="Read README.md"))
    assert result.reversible is True
    assert result.score <= 15


def test_a_write_is_reversible_because_the_previous_content_is_recoverable():
    result = assess(action(ActionType.FILE_WRITE, diff=diff_with(3, 0)))
    assert result.reversible is True


def test_rewriting_git_history_is_irreversible():
    assert assess(action(ActionType.GIT_HISTORY_REWRITE)).reversible is False


# ---- the always-confirm tier dominates ---------------------------------------


def test_every_always_confirm_action_scores_as_significant():
    # A tier the spec says has no exceptions must never be presented as routine,
    # whatever the size of its diff.
    for action_type in (
        ActionType.FILE_DELETE,
        ActionType.GIT_HISTORY_REWRITE,
        ActionType.SHELL_NETWORK,
        ActionType.DEPENDENCY_NEW,
        ActionType.SECRET_ACCESS,
        ActionType.PATH_OUTSIDE_WORKSPACE,
    ):
        result = assess(action(action_type))
        assert result.score >= 50, f"{action_type} scored too low"
        assert result.always_confirm is True


def test_reaching_the_network_is_called_out_by_name():
    result = assess(action(ActionType.SHELL_NETWORK, summary="curl example.com"))
    assert result.reaches_network is True
    assert any("network" in factor.lower() for factor in result.factors)


def test_leaving_the_workspace_is_called_out_by_name():
    result = assess(action(ActionType.PATH_OUTSIDE_WORKSPACE))
    assert result.leaves_workspace is True
    assert any("workspace" in factor.lower() for factor in result.factors)


def test_touching_secrets_is_called_out_by_name():
    result = assess(action(ActionType.SECRET_ACCESS, summary="Read .env"))
    assert any("secret" in factor.lower() for factor in result.factors)


# ---- magnitude ---------------------------------------------------------------


def test_a_bigger_diff_scores_higher_than_a_smaller_one():
    small = assess(action(ActionType.FILE_WRITE, diff=diff_with(2, 0)))
    large = assess(action(ActionType.FILE_WRITE, diff=diff_with(400, 300)))
    assert large.score > small.score
    assert large.lines_changed == 700


def test_deletions_weigh_more_than_additions():
    """Removing code you did not read is worse than adding code you can read."""
    adding = assess(action(ActionType.FILE_WRITE, diff=diff_with(100, 0)))
    removing = assess(action(ActionType.FILE_WRITE, diff=diff_with(0, 100)))
    assert removing.score > adding.score


def test_a_command_that_runs_on_the_host_scores_above_a_sandboxed_one():
    on_host = assess(
        action(ActionType.SHELL_OTHER, preview={"runs_in": {"isolated": False}})
    )
    sandboxed = assess(
        action(ActionType.SHELL_OTHER, preview={"runs_in": {"isolated": True}})
    )
    assert on_host.score > sandboxed.score


# ---- shape -------------------------------------------------------------------


def test_the_score_is_always_within_bounds():
    huge = assess(action(ActionType.FILE_DELETE, diff=diff_with(9999, 9999)))
    assert 0 <= huge.score <= 100


def test_every_assessment_explains_itself():
    # A score with no reasoning is a number to click past. The factors are the
    # feature; the score is just the summary of them.
    result = assess(action(ActionType.FILE_DELETE, summary="Delete scratch.tmp"))
    assert result.factors
    assert all(isinstance(factor, str) and factor for factor in result.factors)


def test_bands_are_derived_from_the_score():
    assert assess(action(ActionType.FILE_READ)).band == "low"
    assert assess(action(ActionType.FILE_DELETE)).band in ("high", "critical")


def test_it_serialises_to_plain_json():
    payload = assess(action(ActionType.FILE_DELETE)).to_dict()
    for key in (
        "score",
        "band",
        "reversible",
        "always_confirm",
        "reaches_network",
        "leaves_workspace",
        "lines_changed",
        "files_touched",
        "factors",
    ):
        assert key in payload


def test_assessment_is_pure_and_repeatable():
    proposed = action(ActionType.FILE_WRITE, diff=diff_with(10, 4))
    assert assess(proposed).to_dict() == assess(proposed).to_dict()


def test_a_risk_assessment_can_be_built_directly_for_tests():
    result = RiskAssessment(score=42, factors=["because"])
    assert result.band == "medium"
