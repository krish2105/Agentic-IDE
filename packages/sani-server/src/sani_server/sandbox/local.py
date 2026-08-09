"""Local PTY sandbox -- the development default.

Named "sandbox" for interface symmetry only: this provides no isolation
whatsoever. It runs a shell as the server user, in the session workspace. That
is appropriate for local single-user development and for nothing else, which is
the same reason Phase 0 has no auth.
"""

from __future__ import annotations

import os
import shutil

from sani_core.runners import CommandOutcome, LocalCommandRunner

from .base import Sandbox
from .pty_process import PtyTerminal, spawn_pty

SHELL_ENV_VAR = "SANI_TERMINAL_SHELL"


def pick_shell() -> str:
    """Which interactive shell to launch. Shared with the sandbox-exec sandbox,
    which runs the same shell under a Seatbelt profile rather than a container."""
    configured = os.environ.get(SHELL_ENV_VAR)
    if configured:
        return configured
    for candidate in ("/bin/bash", "/bin/sh"):
        if shutil.which(candidate):
            return candidate
    return "/bin/sh"


def terminal_env(workspace: str) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "TERM": "xterm-256color",
            "COLORTERM": "truecolor",
            "PWD": workspace,
            # Only takes effect for shells that do not load an rc file; an
            # interactive bash will overwrite it from /etc/bash.bashrc.
            "PS1": "sani:\\W$ ",
        }
    )
    # The server's own virtualenv should not leak into the user's shell.
    env.pop("VIRTUAL_ENV", None)
    return env


class LocalSandbox(Sandbox):
    kind = "local"

    def __init__(self, workspace) -> None:
        super().__init__(workspace)
        self._runner = LocalCommandRunner()

    async def exec(self, command: str, *, timeout_s: int = 120) -> CommandOutcome:
        return await self._runner.run(command, cwd=self.workspace, timeout_s=timeout_s)

    async def open_terminal(self, *, cols: int = 80, rows: int = 24) -> PtyTerminal:
        shell = pick_shell()
        argv = [shell, "-i"] if shell.endswith("bash") else [shell]
        return await spawn_pty(
            argv,
            cwd=str(self.workspace),
            env=terminal_env(str(self.workspace)),
            cols=cols,
            rows=rows,
        )

    def describe(self) -> dict:
        return {**super().describe(), "shell": pick_shell(), "isolated": False}
