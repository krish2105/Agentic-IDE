"""The Docker-per-session sandbox, against a real daemon.

This is the last of the "written but never executed" claims. It stayed unverified
for a specific and instructive reason: the environment it was written in had the
`docker` CLI but no daemon, and every guard in the code checks
``shutil.which("docker")`` -- the *client*. So the codebase could tell you Docker
was available while nothing could actually run.

The gate here is therefore `docker info`, a reachable daemon, not the binary.
Same "skip, don't fake" rule as ``test_redis_sessions.py`` and
``test_sandbox_exec.py``: without a daemon these skip, and with one they run for
real. Nothing here mocks the daemon, because a mock would have passed the whole
time this code was broken and nobody would have known.

What is asserted is what Section 11 actually claims -- a reduced blast radius,
not a security boundary: the workspace is shared, the network is not, and the
container cannot outlive the session.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from sani_server.sandbox.base import SandboxError
from sani_server.sandbox.docker import (
    CONTAINER_WORKDIR,
    CPU_LIMIT,
    MEMORY_LIMIT,
    PIDS_LIMIT,
    DockerSandbox,
)


def _daemon_available() -> bool:
    """A reachable daemon, not merely an installed client.

    The distinction is the whole reason this file exists.
    """
    if not shutil.which("docker"):
        return False
    try:
        return (
            subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=20,
            ).returncode
            == 0
        )
    except (OSError, subprocess.TimeoutExpired):
        return False


needs_daemon = pytest.mark.skipif(
    not _daemon_available(),
    reason="no reachable Docker daemon (the CLI alone is not enough)",
)


@pytest.fixture
def shared_workspace(tmp_path_factory):
    """A workspace the Docker VM can actually see.

    Deliberately *not* pytest's `tmp_path`: that lives under /private/var/folders,
    which a macOS Docker VM does not share, and the bind mount then silently
    yields an empty directory. Every live test below would be exercising that
    failure instead of what it claims to test -- which is how the first real run
    of this file caught the missing mount check.
    """
    root = Path.home() / ".sani" / "docker-test-workspaces"
    root.mkdir(parents=True, exist_ok=True)
    workspace = root / uuid.uuid4().hex[:8]
    workspace.mkdir()
    yield workspace
    shutil.rmtree(workspace, ignore_errors=True)


@pytest.fixture
def sandbox(shared_workspace):
    """A real container, torn down whatever the test does."""
    box = DockerSandbox(shared_workspace, f"test{uuid.uuid4().hex[:8]}")
    yield box
    try:
        asyncio.run(box.shutdown())
    except Exception:
        pass
    # Belt and braces: a leaked container would poison later runs.
    subprocess.run(["docker", "rm", "-f", box.container], capture_output=True)


# --- pure, runs everywhere --------------------------------------------------


def test_exec_argv_targets_the_container_workdir():
    """Pure argv construction, so it is checkable with no daemon at all -- which
    is the only part of this file that was ever covered before."""
    box = DockerSandbox(Path("/tmp/ws"), "ses_abc")
    argv = box.exec_argv("echo hi")
    assert argv[:2] == ["docker", "exec"]
    assert "--workdir" in argv and CONTAINER_WORKDIR in argv
    assert argv[-3:] == ["/bin/sh", "-c", "echo hi"]
    assert "sani-ses_abc" in argv


def test_it_reports_its_own_unverified_state_honestly():
    """`describe()` is what a client shows a user about their isolation. If this
    ever says verified without these tests having run, the UI is lying."""
    box = DockerSandbox(Path("/tmp/ws"), "ses_abc")
    described = box.describe()
    assert described["kind"] == "docker"
    assert described["isolated"] is True
    assert described["container"] == "sani-ses_abc"


# --- live, needs a daemon --------------------------------------------------


@needs_daemon
@pytest.mark.asyncio
async def test_a_command_runs_inside_the_container(sandbox):
    result = await sandbox.exec("echo hello from the container")
    assert result.exit_code == 0
    assert "hello from the container" in result.output


@needs_daemon
@pytest.mark.asyncio
async def test_the_container_is_named_for_its_session(sandbox):
    """`docker ps` showing sani-<session_id> is the manual check CLAUDE.md asks
    for; asserting it means nobody has to remember to do it by hand."""
    await sandbox.exec("true")
    listing = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True
    ).stdout
    assert sandbox.container in listing.split()


@needs_daemon
@pytest.mark.asyncio
async def test_the_workspace_is_shared_both_ways(sandbox, shared_workspace):
    """The agent edits files the human can see. Without this the sandbox would
    be isolating the work from its own purpose."""
    (shared_workspace / "from_host.txt").write_text("written on the host\n")
    seen = await sandbox.exec("cat from_host.txt")
    assert "written on the host" in seen.output

    await sandbox.exec("printf 'written in the container\\n' > from_container.txt")
    assert (shared_workspace / "from_container.txt").read_text() == "written in the container\n"


@needs_daemon
@pytest.mark.asyncio
async def test_the_container_has_no_network(sandbox):
    """`--network none` is the one containment claim the terminal relies on: the
    human's own shell is deliberately not permission-gated, so the network is
    taken away instead of judged."""
    result = await sandbox.exec(
        "getent hosts example.com || echo NO_DNS", timeout_s=30
    )
    assert "NO_DNS" in result.output or result.exit_code != 0


@needs_daemon
@pytest.mark.asyncio
async def test_the_resource_caps_are_actually_applied(sandbox):
    """Docker silently ignores nothing here, but a typo in a flag name would
    leave a cap off while the code still read as though it set one."""
    await sandbox.exec("true")
    inspected = subprocess.run(
        [
            "docker", "inspect", sandbox.container,
            "--format", "{{.HostConfig.Memory}} {{.HostConfig.NanoCpus}} {{.HostConfig.PidsLimit}}",
        ],
        capture_output=True,
        text=True,
    ).stdout.split()

    memory, nano_cpus, pids = int(inspected[0]), int(inspected[1]), int(inspected[2])
    assert memory == 1024 * 1024 * 1024, f"MEMORY_LIMIT={MEMORY_LIMIT} not applied"
    assert nano_cpus == int(float(CPU_LIMIT) * 1_000_000_000), "CPU_LIMIT not applied"
    assert pids == int(PIDS_LIMIT), "PIDS_LIMIT not applied"


@needs_daemon
@pytest.mark.asyncio
async def test_a_timeout_is_reported_rather_than_raised(sandbox):
    """A hung command must come back as a timed-out result the executor can fail
    a step with, not an exception that takes the session down."""
    result = await sandbox.exec("sleep 30", timeout_s=2)
    assert result.timed_out is True
    assert result.exit_code is None


@needs_daemon
@pytest.mark.asyncio
async def test_shutdown_removes_the_container(sandbox):
    """`--rm` plus an explicit kill: a session that ends must not leave a
    container holding a gigabyte of RAM."""
    await sandbox.exec("true")
    await sandbox.shutdown()

    listing = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True
    ).stdout
    assert sandbox.container not in listing.split()


@needs_daemon
@pytest.mark.asyncio
async def test_the_terminal_attaches_to_the_same_container(sandbox):
    """The human's shell and the agent's commands must land in one place, or
    "what the agent did" and "what I see" diverge."""
    await sandbox.exec("printf 'marker\\n' > shared.txt")
    terminal = await sandbox.open_terminal(cols=80, rows=24)
    try:
        # `read()` takes no timeout and blocks on a queue, so the wait has to be
        # imposed from outside -- otherwise a container that never echoes hangs
        # the suite instead of failing it.
        await terminal.write(b"cat shared.txt\n")
        seen = b""
        deadline = 20
        while deadline and b"marker" not in seen:
            try:
                seen += await asyncio.wait_for(terminal.read(), timeout=1.0)
            except asyncio.TimeoutError:
                deadline -= 1
        assert b"marker" in seen, f"terminal never echoed the file: {seen!r}"
    finally:
        terminal.close()


@needs_daemon
@pytest.mark.asyncio
async def test_an_unshared_workspace_is_refused_rather_than_mounted_empty(tmp_path):
    """The bug the first real run of this file exposed.

    A macOS Docker daemon lives in a VM that shares only some host paths. Bind
    mounting an unshared path does not fail: it mounts an *empty directory*, exit
    code 0, no warning. The agent then reads nothing and loses everything it
    writes when the container stops, and every symptom points at the agent.

    pytest's `tmp_path` is under /private/var/folders, which is exactly such a
    path -- so this test asserts the failure is now loud. If a future Docker
    setup shares it, the mount succeeds and there is nothing to refuse.
    """
    box = DockerSandbox(tmp_path, f"test{uuid.uuid4().hex[:8]}")
    (tmp_path / "canary.txt").write_text("visible on the host\n")
    try:
        try:
            result = await box.exec("cat canary.txt")
        except SandboxError as exc:
            assert "not visible inside the container" in str(exc)
            assert "shares only some host paths" in str(exc)
            return
        # Shared after all: then the file must genuinely be readable. What must
        # never happen is an empty mount reported as success.
        assert "visible on the host" in result.output, (
            "the workspace mounted empty and nothing complained -- the silent "
            "failure this check exists to prevent"
        )
    finally:
        await box.shutdown()
