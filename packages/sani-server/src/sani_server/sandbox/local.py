"""Local PTY sandbox -- the development default.

Named "sandbox" for interface symmetry only: this provides no isolation
whatsoever. It runs a shell as the server user, in the session workspace. That
is appropriate for local single-user development and for nothing else, which is
the same reason Phase 0 has no auth.
"""

from __future__ import annotations

import os
import shutil

from .base import Sandbox
from .pty_process import PtyTerminal, spawn_pty

SHELL_ENV_VAR = "SANI_TERMINAL_SHELL"


def _pick_shell() -> str:
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
            # A stable prompt keeps the end-to-end terminal assertions readable.
            "PS1": "sani:\\W$ ",
        }
    )
    # The server's own virtualenv should not leak into the user's shell.
    env.pop("VIRTUAL_ENV", None)
    return env


class LocalSandbox(Sandbox):
    kind = "local"

    async def open_terminal(self, *, cols: int = 80, rows: int = 24) -> PtyTerminal:
        shell = _pick_shell()
        argv = [shell, "-i"] if shell.endswith("bash") else [shell]
        return await spawn_pty(
            argv,
            cwd=str(self.workspace),
            env=terminal_env(str(self.workspace)),
            cols=cols,
            rows=rows,
        )

    def describe(self) -> dict:
        return {**super().describe(), "shell": _pick_shell(), "isolated": False}
