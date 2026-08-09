"""Sandbox interface for the interactive terminal.

Spec Section 11 calls Docker-per-session "demo-grade, not production-hardened",
and that is the honest framing: a resource-capped container is a blast-radius
reduction, not a multi-tenant security boundary.

Three implementations ship: a local PTY in the session workspace, a Docker
container per session, and a macOS Seatbelt (``sandbox-exec``) profile that
needs no daemon. Same three methods, chosen by ``SANI_SANDBOX``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from sani_core.runners import CommandOutcome


class SandboxError(Exception):
    pass


class TerminalSession(ABC):
    """One PTY. Reads and writes are raw bytes; xterm.js handles the rest."""

    @abstractmethod
    async def read(self) -> bytes:
        """Next chunk of output. Returns b"" when the process has exited."""

    @abstractmethod
    async def write(self, data: bytes) -> None: ...

    @abstractmethod
    def resize(self, cols: int, rows: int) -> None: ...

    @abstractmethod
    def close(self) -> None:
        """Synchronous by design -- see ``PtyTerminal.close``."""

    @property
    @abstractmethod
    def alive(self) -> bool: ...


class Sandbox(ABC):
    #: Reported to the client so the status bar can say where commands run.
    kind: str = "unknown"

    def __init__(self, workspace: Path) -> None:
        self.workspace = Path(workspace).resolve()

    @abstractmethod
    async def open_terminal(self, *, cols: int = 80, rows: int = 24) -> TerminalSession: ...

    @abstractmethod
    async def exec(self, command: str, *, timeout_s: int = 120) -> CommandOutcome:
        """Run one non-interactive command. This is the agent's shell path."""

    async def shutdown(self) -> None:
        """Release anything the sandbox holds. Safe to call more than once."""

    def describe(self) -> dict:
        return {"kind": self.kind, "workspace": str(self.workspace)}
