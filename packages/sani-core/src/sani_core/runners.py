"""Where an agent command actually executes.

The shell tool decides *what* to run and the permission engine decides *whether*
it may. Neither should know *where* it lands -- that is the sandbox's business,
and the sandbox lives in the server, which the core must not import.

So the core owns this seam and ships the honest default: a runner that executes
on the host with no isolation. The server injects a sandbox-backed runner at
session creation, and the tool is none the wiser.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIMEOUT_S = 120
MAX_OUTPUT_CHARS = 100_000


@dataclass(slots=True)
class CommandOutcome:
    exit_code: int | None
    output: str
    timed_out: bool = False

    def to_dict(self) -> dict:
        return {
            "exit_code": self.exit_code,
            "output": self.output,
            "timed_out": self.timed_out,
        }


class CommandRunner(ABC):
    #: Surfaced on `tool.proposed` so the client can say where a command will
    #: run before the user approves it. "host" is a warning, not a detail.
    kind: str = "host"

    @abstractmethod
    async def run(
        self, command: str, *, cwd: Path, timeout_s: int = DEFAULT_TIMEOUT_S
    ) -> CommandOutcome: ...

    def describe(self) -> dict:
        return {"kind": self.kind, "isolated": False}


class LocalCommandRunner(CommandRunner):
    """Runs on the host as the server user. No isolation of any kind."""

    kind = "host"

    async def run(
        self, command: str, *, cwd: Path, timeout_s: int = DEFAULT_TIMEOUT_S
    ) -> CommandOutcome:
        process = await asyncio.create_subprocess_shell(
            command,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout_s)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return CommandOutcome(exit_code=None, output="", timed_out=True)

        return CommandOutcome(
            exit_code=process.returncode,
            output=stdout.decode("utf-8", errors="replace")[:MAX_OUTPUT_CHARS],
        )
