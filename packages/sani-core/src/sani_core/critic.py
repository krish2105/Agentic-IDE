"""The self-critique pass.

The documented top failure of 2026 agentic coding is not obviously-bad output.
It is output that *looks* right: plausible code carrying a subtle error, arriving
through a review flow that shows a diff and asks "ok?". Reviewers approve it
because nothing on screen argues otherwise.

So something should argue otherwise. Before a diff reaches the human, a second
pass reviews the agent's own output against the task and attaches a verdict.

Three constraints:

1. **Advisory, never a gate.** A critique cannot approve, reject, or delay
   anything. It is input to a human decision. ``permissions.evaluate()`` remains
   the only chokepoint, and a glowing verdict must never make an
   always-confirm action feel safe to wave through.
2. **Off by default.** It costs a second inference per diff, and that cost shows
   up in the meter the user is watching. Opt in.
3. **Deterministic fallback.** ``ScriptedCritic`` keeps the test suite
   reproducible with no API key, the same reason the scripted planner exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from .actions import ProposedAction

#: How much the critic believes the change does what the task asked.
Verdict = Literal["looks-right", "concerns", "likely-wrong"]


@dataclass(slots=True)
class Critique:
    verdict: Verdict = "looks-right"
    #: 0-1. Deliberately separate from the verdict: "likely wrong, but I am not
    #: sure" and "likely wrong, and I am certain" are different messages.
    confidence: float = 0.5
    concerns: list[str] = field(default_factory=list)
    reviewed_by: str | None = None

    @property
    def clean(self) -> bool:
        return self.verdict == "looks-right" and not self.concerns

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "confidence": round(self.confidence, 3),
            "concerns": list(self.concerns),
            "reviewed_by": self.reviewed_by,
            "clean": self.clean,
        }


class Critic(Protocol):
    name: str

    async def review(self, action: ProposedAction, task: str) -> Critique: ...


class NullCritic:
    """The default. Reviews nothing and says so."""

    name = "none"

    async def review(self, action: ProposedAction, task: str) -> Critique:
        return Critique(verdict="looks-right", confidence=0.0, reviewed_by=None)


class ScriptedCritic:
    """A deterministic critic for tests and demos.

    It does not understand code. It applies a handful of structural checks that
    are true regardless of language, which is enough to prove the wiring without
    making the suite depend on a model's mood.
    """

    name = "scripted"

    async def review(self, action: ProposedAction, task: str) -> Critique:
        concerns: list[str] = []

        diff = action.diff
        if diff is not None:
            # A change that only removes code, when the task asked to add
            # something, is the shape of the ConsoleLauncher failure: a model
            # regenerating a file it never fully saw.
            if diff.deletions > 0 and diff.additions == 0:
                concerns.append(
                    "This change only removes lines. If the task asked for an addition, "
                    "the file may have been regenerated from an incomplete view of it."
                )
            # Wholesale replacement of a substantial file deserves a second look
            # for the same reason.
            if diff.deletions > 40 and diff.additions < diff.deletions / 2:
                concerns.append(
                    f"{diff.deletions} lines removed against {diff.additions} added — "
                    "check this is a rewrite you asked for and not lost content."
                )

        command = (action.preview or {}).get("command")
        if isinstance(command, str) and any(
            token in command for token in ("$(", "`", "<(")
        ):
            concerns.append(
                "The command uses substitution, so what it actually runs is not "
                "visible in the text above."
            )

        if not concerns:
            return Critique(verdict="looks-right", confidence=0.6, reviewed_by=self.name)

        return Critique(
            verdict="concerns" if len(concerns) == 1 else "likely-wrong",
            confidence=0.7,
            concerns=concerns,
            reviewed_by=self.name,
        )


def build_critic(kind: str | None = None) -> Critic:
    """``none`` (default) or ``scripted``.

    A model-backed critic plugs in here behind the same protocol; it is not
    wired yet because it is quota-dependent and would make the suite
    non-reproducible, which is the same reason the litellm planner sits behind
    a flag.
    """
    resolved = (kind or "none").lower()
    if resolved in ("none", "off", ""):
        return NullCritic()
    if resolved == "scripted":
        return ScriptedCritic()
    raise ValueError(f"unknown critic {resolved!r} (expected 'none' or 'scripted')")
