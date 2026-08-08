"""Docker-per-session sandbox.

⚠️ Written but not exercised: the development environment this was built in has
the Docker client without a daemon, so the code path below has never run. Treat
it as unverified until someone runs the manual check in CLAUDE.md.

Spec Section 11 is right to call this demo-grade. A resource-capped container
reduces blast radius; it is not a multi-tenant security boundary, and nothing
here should be described as one.
"""

from __future__ import annotations

import asyncio
import os
import shutil

from .base import Sandbox, SandboxError
from .pty_process import PtyTerminal, spawn_pty

IMAGE_ENV_VAR = "SANI_SANDBOX_IMAGE"
DEFAULT_IMAGE = "python:3.11-slim"

CONTAINER_WORKDIR = "/workspace"

#: Deliberately conservative. A runaway agent loop should hit a wall quickly.
MEMORY_LIMIT = "1g"
CPU_LIMIT = "1"
PIDS_LIMIT = "256"

START_TIMEOUT_S = 60


async def _run(*argv: str, timeout: int = 30) -> tuple[int, str]:
    process = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        process.kill()
        raise SandboxError(f"{' '.join(argv[:3])} timed out") from exc
    return process.returncode or 0, stdout.decode("utf-8", errors="replace").strip()


class DockerSandbox(Sandbox):
    kind = "docker"

    def __init__(self, workspace, session_id: str) -> None:
        super().__init__(workspace)
        self.session_id = session_id
        self.container = f"sani-{session_id}"
        self._started = False

    @property
    def image(self) -> str:
        return os.environ.get(IMAGE_ENV_VAR, DEFAULT_IMAGE)

    async def _ensure_container(self) -> None:
        if self._started:
            return
        if not shutil.which("docker"):
            raise SandboxError("SANI_SANDBOX=docker but the docker CLI is not installed")

        code, _ = await _run("docker", "inspect", "--type=container", self.container)
        if code != 0:
            code, output = await _run(
                "docker", "run", "--detach", "--rm",
                "--name", self.container,
                "--volume", f"{self.workspace}:{CONTAINER_WORKDIR}",
                "--workdir", CONTAINER_WORKDIR,
                "--memory", MEMORY_LIMIT,
                "--cpus", CPU_LIMIT,
                "--pids-limit", PIDS_LIMIT,
                # The agent's own network access is gated by the always-confirm
                # tier; the interactive terminal gets none at all.
                "--network", "none",
                self.image,
                "sleep", "infinity",
                timeout=START_TIMEOUT_S,
            )
            if code != 0:
                raise SandboxError(f"could not start sandbox container: {output}")
        self._started = True

    async def open_terminal(self, *, cols: int = 80, rows: int = 24) -> PtyTerminal:
        await self._ensure_container()
        return await spawn_pty(
            [
                "docker", "exec", "--interactive", "--tty",
                "--workdir", CONTAINER_WORKDIR,
                "--env", "TERM=xterm-256color",
                self.container,
                "/bin/sh",
            ],
            cols=cols,
            rows=rows,
        )

    async def shutdown(self) -> None:
        if not self._started:
            return
        self._started = False
        await _run("docker", "kill", self.container)

    def describe(self) -> dict:
        return {
            **super().describe(),
            "container": self.container,
            "image": self.image,
            "isolated": True,
            "verified": False,
        }
