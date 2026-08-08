"""Deterministic scripted model -- the default backend.

Phase 0's gate is "the WebSocket stream and approval endpoint are tested end to
end" (spec Section 14). That claim only means something if the test is
reproducible, so the default backend replays a fixed script instead of calling
a free-tier provider whose output and availability both vary.

Set ``SANI_MODEL_BACKEND=litellm`` for real inference.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ..plan import Plan, PlanStep
from .base import DeltaSink, ModelAdapter

#: Exercises all three interesting paths in one run: an auto-approved read, an
#: auto-approved write that generates a diff, and an always-confirm delete.
DEFAULT_DEMO_SCRIPT: list[dict[str, Any]] = [
    {
        "description": "Read the project README for context",
        "tool": "file_editor",
        "params": {"op": "read", "path": "README.md"},
    },
    {
        "description": "Write the greeting module",
        "tool": "file_editor",
        "params": {
            "op": "write",
            "path": "greeting.py",
            "content": 'def greet(name: str) -> str:\n    return f"Hello, {name}!"\n',
        },
    },
    {
        "description": "Remove the obsolete scratch file",
        "tool": "file_editor",
        "params": {"op": "delete", "path": "scratch.tmp"},
    },
]

DEFAULT_RATIONALE = (
    "Reading the README first for repository conventions, then adding the "
    "module, then clearing the scratch file left over from the previous run."
)

#: Small pause between streamed chunks so clients exercise real incremental
#: rendering rather than receiving one batched frame.
CHUNK_DELAY_S = 0.0


class ScriptedModel(ModelAdapter):
    model_name = "scripted"

    def __init__(
        self,
        script: list[dict[str, Any]] | None = None,
        *,
        rationale: str = DEFAULT_RATIONALE,
        chunk_delay_s: float = CHUNK_DELAY_S,
    ) -> None:
        self.script = script if script is not None else DEFAULT_DEMO_SCRIPT
        self.rationale = rationale
        self.chunk_delay_s = chunk_delay_s

    async def plan(self, task: str, workspace: Path, emit_delta: DeltaSink) -> Plan:
        for word in self.rationale.split(" "):
            await emit_delta(word + " ")
            if self.chunk_delay_s:
                await asyncio.sleep(self.chunk_delay_s)

        steps = [
            PlanStep(
                index=i,
                description=entry["description"],
                tool=entry["tool"],
                params=dict(entry.get("params", {})),
            )
            for i, entry in enumerate(self.script)
        ]
        return Plan(task=task, steps=steps, rationale=self.rationale)
