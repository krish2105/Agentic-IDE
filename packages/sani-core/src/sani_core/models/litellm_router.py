"""LiteLLM-backed planner: Groq, Gemini, Cerebras, Ollama (spec Section 3).

Not exercised in CI. It depends on free-tier quota and non-deterministic model
output, so it sits behind ``SANI_MODEL_BACKEND=litellm`` and is verified by the
manual smoke run documented in CLAUDE.md.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from ..plan import Plan, PlanStep
from .base import DeltaSink, ModelAdapter, ModelError

DEFAULT_MODEL = "groq/llama-3.3-70b-versatile"

PLANNER_SYSTEM_PROMPT = """\
You are the planner for Sani' Studio, a coding agent. Produce a short plan for \
the user's task and nothing else.

Respond with JSON only, in this exact shape:
{"rationale": "<one or two sentences>",
 "steps": [{"description": "...", "tool": "file_editor", "params": {...}}]}

Available tools and their params:
- file_editor: {"op": "read"|"write"|"delete", "path": "<relative path>", \
"content": "<full file contents, write only>"}
- shell: {"command": "<command line>"}

Rules: paths are relative to the workspace root. Keep the plan to at most 8 \
steps. Do not include commentary outside the JSON.
"""

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> dict[str, Any]:
    match = _JSON_BLOCK_RE.search(text)
    if not match:
        raise ModelError(f"planner returned no JSON object: {text[:400]}")
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ModelError(f"planner returned malformed JSON: {exc}") from exc


class LiteLLMModel(ModelAdapter):
    def __init__(self, model: str | None = None) -> None:
        self.model_name = model or os.environ.get("SANI_MODEL", DEFAULT_MODEL)

    async def plan(self, task: str, workspace: Path, emit_delta: DeltaSink) -> Plan:
        try:
            import litellm
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise ModelError(
                "SANI_MODEL_BACKEND=litellm requires the litellm extra: "
                "uv sync --extra litellm"
            ) from exc

        messages = [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": f"Workspace: {workspace}\n\nTask: {task}"},
        ]

        chunks: list[str] = []
        try:
            stream = await litellm.acompletion(
                model=self.model_name, messages=messages, stream=True, temperature=0
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content or ""
                if delta:
                    chunks.append(delta)
                    await emit_delta(delta)
        except Exception as exc:  # pragma: no cover - network dependent
            raise ModelError(f"{self.model_name} planning call failed: {exc}") from exc

        parsed = _extract_json("".join(chunks))
        steps = [
            PlanStep(
                index=i,
                description=str(entry.get("description", f"step {i}")),
                tool=str(entry.get("tool", "shell")),
                params=dict(entry.get("params", {})),
            )
            for i, entry in enumerate(parsed.get("steps", []))
        ]
        if not steps:
            raise ModelError("planner returned an empty plan")

        return Plan(task=task, steps=steps, rationale=str(parsed.get("rationale", "")))
