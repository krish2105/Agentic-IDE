"""Model adapter interface.

Planning is the only model call Phase 0 makes. Keeping the surface this narrow
means the scripted backend used in tests and the LiteLLM backend used in demos
are genuinely interchangeable, rather than the fake being a loose approximation
of the real thing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from pathlib import Path

from ..plan import Plan

#: Called with each token of the model's reasoning as it arrives.
DeltaSink = Callable[[str], Awaitable[None]]


class ModelError(Exception):
    pass


class ModelAdapter(ABC):
    #: Reported on `context.usage` events so the status bar can name the model.
    model_name: str = "unknown"

    @abstractmethod
    async def plan(self, task: str, workspace: Path, emit_delta: DeltaSink) -> Plan:
        """Produce a plan, streaming reasoning through ``emit_delta`` as it goes."""
