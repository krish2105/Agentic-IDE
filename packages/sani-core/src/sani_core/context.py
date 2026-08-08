"""Context-window accounting.

Phase 0 ships the meter (spec Section 5, "context-window usage meter in the
status bar") and the seam compaction will plug into. Actual compaction is
deliberately not implemented yet -- a stub that silently dropped history would
be worse than an honest no-op, because the failure mode is invisible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

#: Chars-per-token approximation. Good enough for a status-bar meter; replaced
#: with the router's real tokenizer when LiteLLM is the active backend.
CHARS_PER_TOKEN = 4

DEFAULT_WINDOW = 128_000

#: Fraction of the window at which compaction should be considered.
COMPACTION_THRESHOLD = 0.8


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN) if text else 0


@dataclass(slots=True)
class ContextWindow:
    limit: int = DEFAULT_WINDOW
    used: int = 0

    def add(self, text: str) -> int:
        tokens = estimate_tokens(text)
        self.used += tokens
        return tokens

    @property
    def pct(self) -> float:
        return round(self.used / self.limit, 4) if self.limit else 0.0

    @property
    def should_compact(self) -> bool:
        return self.pct >= COMPACTION_THRESHOLD

    def to_dict(self) -> dict:
        return {
            "used_tokens": self.used,
            "limit_tokens": self.limit,
            "pct": self.pct,
            "should_compact": self.should_compact,
            "estimated": True,
        }


class CompactionHook(Protocol):
    """Implemented in a later phase. See spec Section 5."""

    def compact(self, history: list[dict], window: ContextWindow) -> list[dict]: ...


class NoopCompaction:
    def compact(self, history: list[dict], window: ContextWindow) -> list[dict]:
        return history
