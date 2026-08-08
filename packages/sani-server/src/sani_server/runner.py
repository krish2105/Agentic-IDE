"""Bridges the core's CommandRunner seam to a session's sandbox.

This is the whole fix for the Phase 1 gap where the agent's shell tool ran on
the host while only the human's terminal was sandboxed. Now both go through the
same sandbox, so switching ``SANI_SANDBOX=docker`` actually moves the agent.
"""

from __future__ import annotations

from pathlib import Path

from sani_core.runners import DEFAULT_TIMEOUT_S, CommandOutcome, CommandRunner

from .sandbox import Sandbox


class SandboxCommandRunner(CommandRunner):
    def __init__(self, sandbox: Sandbox) -> None:
        self.sandbox = sandbox

    @property
    def kind(self) -> str:  # type: ignore[override]
        # "host" for the local sandbox is deliberate: it tells the truth about
        # where the command lands, and the UI shows this before approval.
        return "container" if self.sandbox.kind == "docker" else "host"

    async def run(
        self, command: str, *, cwd: Path, timeout_s: int = DEFAULT_TIMEOUT_S
    ) -> CommandOutcome:
        # ``cwd`` is ignored: the sandbox owns its own working directory, which
        # for Docker is a mount point that does not exist on this side.
        return await self.sandbox.exec(command, timeout_s=timeout_s)

    def describe(self) -> dict:
        described = self.sandbox.describe()
        return {
            "kind": self.kind,
            "sandbox": described["kind"],
            "isolated": described.get("isolated", False),
        }
