"""Docker-per-session sandbox.

Verified against a real daemon -- ``tests/server/test_docker_sandbox.py`` starts
actual containers whenever one is reachable, and skips otherwise. It was
unverified for a long time for an instructive reason: every guard here checks
``shutil.which("docker")``, the *client*, so the code could report Docker as
available while nothing could run. The tests gate on ``docker info`` instead.

The first real run found a silent failure that no amount of reading would have
shown: on macOS the daemon lives in a VM sharing only some host paths, and a bind
mount of an unshared path mounts an *empty directory* rather than failing. See
``_verify_mount``.

Spec Section 11 is right to call this demo-grade. A resource-capped container
reduces blast radius; it is not a multi-tenant security boundary, and nothing
here should be described as one.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import shutil
import uuid
from pathlib import Path

from sani_core.runners import MAX_OUTPUT_CHARS, CommandOutcome

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
        await self._verify_mount()

    async def _verify_mount(self) -> None:
        """Confirm the workspace is actually visible inside the container.

        On macOS the daemon runs inside a VM that shares only some host paths,
        and a bind mount of an unshared path does not fail -- it silently
        produces an *empty directory*, exit code 0, no warning. The agent then
        reads nothing, writes into the VM, and loses the work when the container
        stops. Every symptom points at the agent rather than at a mount.

        A sentinel is the only reliable check: an empty workspace is legitimately
        empty, so comparing listings cannot tell the two apart. It is written to
        the workspace we are about to hand an agent, and removed immediately.
        """
        sentinel = f".sani-mount-check-{uuid.uuid4().hex[:8]}"
        probe = Path(self.workspace) / sentinel
        try:
            probe.write_text("mount check\n")
        except OSError as exc:
            raise SandboxError(f"workspace {self.workspace} is not writable: {exc}") from exc

        try:
            code, _ = await _run(*self.exec_argv(f"test -f {shlex.quote(sentinel)}"))
        finally:
            probe.unlink(missing_ok=True)

        if code != 0:
            raise SandboxError(
                f"the workspace {self.workspace} is not visible inside the container. "
                "The Docker daemon runs in a VM that shares only some host paths, and a "
                "bind mount of an unshared path silently mounts an empty directory rather "
                "than failing -- so the agent would read nothing and lose everything it "
                "wrote. Move the workspace somewhere the VM shares (your home directory "
                "is shared by default), or add the path to the VM's mounts: "
                "`colima start --mount $PWD:w` for colima, or Settings -> Resources -> "
                "File sharing in Docker Desktop."
            )

    def exec_argv(self, command: str) -> list[str]:
        """Argv for a non-interactive command. Pure, so it is testable without
        a daemon -- which matters, because nothing else here can be."""
        return [
            "docker", "exec",
            "--workdir", CONTAINER_WORKDIR,
            self.container,
            "/bin/sh", "-c", command,
        ]

    async def exec(self, command: str, *, timeout_s: int = 120) -> CommandOutcome:
        await self._ensure_container()
        try:
            code, output = await _run(*self.exec_argv(command), timeout=timeout_s)
        except SandboxError as exc:
            if "timed out" in str(exc):
                return CommandOutcome(exit_code=None, output="", timed_out=True)
            raise
        return CommandOutcome(exit_code=code, output=output[:MAX_OUTPUT_CHARS])

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
            "verified": True,
        }
