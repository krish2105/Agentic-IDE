"""Model backends. Scripted by default; LiteLLM behind an env flag."""

from __future__ import annotations

import os
from typing import Any

from .base import DeltaSink, ModelAdapter, ModelError
from .scripted import DEFAULT_DEMO_SCRIPT, ScriptedModel

BACKEND_ENV_VAR = "SANI_MODEL_BACKEND"


def build_model(
    backend: str | None = None, *, script: list[dict[str, Any]] | None = None
) -> ModelAdapter:
    """Resolve the active planner.

    ``script`` only applies to the scripted backend; it is how tests and the
    demo drive a specific plan without touching a provider.
    """
    resolved = (backend or os.environ.get(BACKEND_ENV_VAR, "scripted")).lower()

    if resolved == "scripted":
        return ScriptedModel(script=script)
    if resolved == "litellm":
        from .litellm_router import LiteLLMModel

        return LiteLLMModel()
    raise ModelError(f"unknown model backend {resolved!r} (expected 'scripted' or 'litellm')")


__all__ = [
    "BACKEND_ENV_VAR",
    "DEFAULT_DEMO_SCRIPT",
    "DeltaSink",
    "ModelAdapter",
    "ModelError",
    "ScriptedModel",
    "build_model",
]
