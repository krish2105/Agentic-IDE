"""Sandbox selection.

``SANI_SANDBOX=local`` (default) or ``docker``. The Docker path is unverified;
see the module docstring in ``docker.py``.
"""

from __future__ import annotations

import os
from pathlib import Path

from .base import Sandbox, SandboxError, TerminalSession
from .local import LocalSandbox

SANDBOX_ENV_VAR = "SANI_SANDBOX"


def build_sandbox(workspace: Path, session_id: str, kind: str | None = None) -> Sandbox:
    resolved = (kind or os.environ.get(SANDBOX_ENV_VAR, "local")).lower()

    if resolved == "local":
        return LocalSandbox(workspace)
    if resolved == "docker":
        from .docker import DockerSandbox

        return DockerSandbox(workspace, session_id)
    raise SandboxError(f"unknown sandbox {resolved!r} (expected 'local' or 'docker')")


__all__ = [
    "SANDBOX_ENV_VAR",
    "LocalSandbox",
    "Sandbox",
    "SandboxError",
    "TerminalSession",
    "build_sandbox",
]
