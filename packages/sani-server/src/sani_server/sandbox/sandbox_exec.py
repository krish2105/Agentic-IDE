"""macOS Seatbelt (``sandbox-exec``) sandbox -- no Docker daemon required.

``sandbox-exec`` is deprecated by Apple but still shipped and functional: it
runs a command under a kernel-enforced Seatbelt profile instead of a
container. That buys filesystem and network confinement with no daemon, no
image pull, and no per-session process -- at the cost of what a container
gives for free. Seatbelt has no notion of a memory, CPU, or process-count
ceiling, so a runaway agent loop is walled off from the network and from the
rest of the filesystem, but not resource-capped. Same honest framing as
``docker.py``: a blast-radius reduction, not a multi-tenant security boundary,
and now also not a resource limiter.

The profile denies all filesystem writes and all network access by default,
then re-opens writes to exactly two places: the session workspace, and a
scratch directory created per sandbox and exported as ``TMPDIR`` so ordinary
tools (``python -c``, ``mktemp``, compilers) have somewhere to put temp files
without punching a hole to the user's real temp directory. Reads and process
execution are left at the system default -- restricting those is what turns a
working shell into one that cannot even resolve ``/bin/sh`` (Seatbelt profiles
that pair ``(deny default)`` with ``(import "bsd.sb")`` were tried first and
that is exactly what happened).

Darwin only. Both the platform and the ``sandbox-exec`` binary are checked
lazily, on first use, so constructing this sandbox on Linux does not fail
until a session actually tries to run something -- the same laziness
``DockerSandbox`` uses for the ``docker`` CLI.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

from sani_core.runners import MAX_OUTPUT_CHARS, CommandOutcome

from .base import Sandbox, SandboxError
from .local import pick_shell, terminal_env
from .pty_process import PtyTerminal, spawn_pty

SANDBOX_EXEC_BIN = "/usr/bin/sandbox-exec"

START_TIMEOUT_S = 120


def _escape(path: str) -> str:
    """Escape a path for embedding in an SBPL string literal."""
    return path.replace("\\", "\\\\").replace('"', '\\"')


def build_profile(workspace: Path, scratch_dir: Path) -> str:
    """The Seatbelt profile text. Pure, so it is testable without macOS.

    ``(allow default)`` first, then a blanket ``(deny file-write* (subpath "/"))``,
    then two narrow ``(allow file-write* ...)`` carve-outs -- later rules win in
    SBPL, so this reads as "everything, except writes, except writes to these
    two places."
    """
    workspace_literal = _escape(str(workspace))
    scratch_literal = _escape(str(scratch_dir))
    return (
        "(version 1)\n"
        "(allow default)\n"
        "(deny network*)\n"
        '(deny file-write* (subpath "/"))\n'
        "(allow file-write*\n"
        f'  (subpath "{workspace_literal}")\n'
        f'  (subpath "{scratch_literal}")\n'
        '  (subpath "/dev")\n'
        ")\n"
    )


def exec_argv(profile_path: Path, argv: list[str]) -> list[str]:
    """Argv to run ``argv`` under the given profile file. Pure, like
    ``DockerSandbox.exec_argv`` -- testable without touching the kernel."""
    return [SANDBOX_EXEC_BIN, "-f", str(profile_path), *argv]


class SandboxExecSandbox(Sandbox):
    kind = "sandbox-exec"

    def __init__(self, workspace, session_id: str) -> None:
        super().__init__(workspace)
        self.session_id = session_id
        self._scratch_dir: Path | None = None
        self._profile_path: Path | None = None

    @property
    def scratch_dir(self) -> Path | None:
        """The per-sandbox ``TMPDIR``. ``None`` until the first command runs."""
        return self._scratch_dir

    async def _ensure_ready(self) -> None:
        if self._scratch_dir is not None:
            return
        if sys.platform != "darwin":
            raise SandboxError("SANI_SANDBOX=sandbox-exec requires macOS")
        if not shutil.which(SANDBOX_EXEC_BIN):
            raise SandboxError(
                f"SANI_SANDBOX=sandbox-exec but {SANDBOX_EXEC_BIN} is not present"
            )

        # Resolved (symlinks followed) because Seatbelt matches the real path,
        # not the one mktemp handed back -- /tmp itself is a symlink to
        # /private/tmp on macOS, and an unresolved subpath rule silently never
        # matches.
        scratch = Path(
            tempfile.mkdtemp(prefix=f"sani-sbx-{self.session_id}-")
        ).resolve()
        profile_fd, profile_name = tempfile.mkstemp(
            prefix=f"sani-sbx-{self.session_id}-", suffix=".sb"
        )
        profile_path = Path(profile_name)
        try:
            with open(profile_fd, "w") as handle:
                handle.write(build_profile(self.workspace, scratch))
        except BaseException:
            profile_path.unlink(missing_ok=True)
            shutil.rmtree(scratch, ignore_errors=True)
            raise

        self._scratch_dir = scratch
        self._profile_path = profile_path

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["TMPDIR"] = str(self._scratch_dir)
        return env

    async def exec(self, command: str, *, timeout_s: int = 120) -> CommandOutcome:
        await self._ensure_ready()
        argv = exec_argv(self._profile_path, ["/bin/sh", "-c", command])
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(self.workspace),
            env=self._env(),
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

    async def open_terminal(self, *, cols: int = 80, rows: int = 24) -> PtyTerminal:
        await self._ensure_ready()
        shell = pick_shell()
        shell_argv = [shell, "-i"] if shell.endswith("bash") else [shell]
        argv = exec_argv(self._profile_path, shell_argv)
        env = terminal_env(str(self.workspace))
        env["TMPDIR"] = str(self._scratch_dir)
        return await spawn_pty(
            argv, cwd=str(self.workspace), env=env, cols=cols, rows=rows
        )

    async def shutdown(self) -> None:
        if self._profile_path is not None:
            self._profile_path.unlink(missing_ok=True)
            self._profile_path = None
        if self._scratch_dir is not None:
            shutil.rmtree(self._scratch_dir, ignore_errors=True)
            self._scratch_dir = None

    def describe(self) -> dict:
        return {
            **super().describe(),
            "isolated": True,
            "network": "none",
            "resource_limits": False,
            "scratch_dir": str(self._scratch_dir) if self._scratch_dir else None,
        }
