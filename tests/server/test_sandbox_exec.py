"""The macOS Seatbelt sandbox: confinement without a Docker daemon.

Profile generation and argv construction are pure and run on every platform,
same reasoning as ``test_docker_exec_argv_is_correct`` -- the part that is
testable without touching the kernel should not be skipped just because the
part that needs the kernel has to be. The live tests below that actually
enter the sandbox are gated on Darwin plus the binary, same pattern as
``test_redis_sessions.py`` gates on ``redis-server``.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
from sani_server.runner import SandboxCommandRunner
from sani_server.sandbox import build_sandbox
from sani_server.sandbox.sandbox_exec import (
    SANDBOX_EXEC_BIN,
    SandboxExecSandbox,
    build_profile,
    exec_argv,
)

darwin_only = pytest.mark.skipif(
    sys.platform != "darwin" or not shutil.which(SANDBOX_EXEC_BIN),
    reason="sandbox-exec is macOS-only",
)


# ---- pure: profile and argv construction -------------------------------------


def test_the_profile_denies_writes_outside_workspace_and_scratch():
    profile = build_profile(Path("/Users/dev/project"), Path("/tmp/sani-sbx-abc"))

    assert "(deny network*)" in profile
    assert '(deny file-write* (subpath "/"))' in profile
    assert '(subpath "/Users/dev/project")' in profile
    assert '(subpath "/tmp/sani-sbx-abc")' in profile
    # allow-default must come before the deny/allow pair: SBPL is
    # last-rule-wins, so a "deny default" preamble would need bsd.sb-style
    # exec/read grants this profile deliberately does not maintain.
    assert profile.index("(allow default)") < profile.index("(deny network*)")


def test_the_profile_escapes_quotes_in_paths():
    profile = build_profile(Path('/Users/dev/weird"name'), Path("/tmp/scratch"))
    assert '/Users/dev/weird\\"name' in profile


def test_exec_argv_is_correct():
    """The one part of the sandbox-exec path testable without macOS."""
    argv = exec_argv(Path("/tmp/sani.sb"), ["/bin/sh", "-c", "pytest -q && echo done"])

    assert argv == [
        SANDBOX_EXEC_BIN,
        "-f",
        "/tmp/sani.sb",
        "/bin/sh",
        "-c",
        "pytest -q && echo done",
    ]


def test_build_sandbox_selects_it_by_kind(tmp_path):
    sandbox = build_sandbox(tmp_path, "ses_x", "sandbox-exec")
    assert isinstance(sandbox, SandboxExecSandbox)


def test_the_sandbox_exec_runner_reports_containment(tmp_path):
    """Construction never touches the platform check -- only exec() does, same
    as DockerSandbox never touches the docker CLI until it runs something."""
    runner = SandboxCommandRunner(build_sandbox(tmp_path, "ses_x", "sandbox-exec"))
    assert runner.kind == "host"  # same kernel, same filesystem for reads
    assert runner.describe() == {
        "kind": "host",
        "sandbox": "sandbox-exec",
        "isolated": True,
    }


# ---- live: needs Darwin and the sandbox-exec binary --------------------------


@darwin_only
async def test_a_command_runs_and_its_output_comes_back(tmp_path):
    sandbox = SandboxExecSandbox(tmp_path, "ses_live")
    try:
        outcome = await sandbox.exec("echo sandbox-exec-path-works")
        assert outcome.exit_code == 0
        assert "sandbox-exec-path-works" in outcome.output
    finally:
        await sandbox.shutdown()


@darwin_only
async def test_writes_inside_the_workspace_succeed(tmp_path):
    sandbox = SandboxExecSandbox(tmp_path, "ses_live")
    try:
        outcome = await sandbox.exec("echo hello > written.txt && cat written.txt")
        assert outcome.exit_code == 0
        assert "hello" in outcome.output
        assert (tmp_path / "written.txt").read_text().strip() == "hello"
    finally:
        await sandbox.shutdown()


@darwin_only
async def test_writes_outside_the_workspace_and_scratch_are_denied(tmp_path, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside-the-sandbox")
    sandbox = SandboxExecSandbox(tmp_path, "ses_live")
    try:
        outcome = await sandbox.exec(f"echo leaked > {outside}/leak.txt")
        assert outcome.exit_code != 0
        assert not (outside / "leak.txt").exists()
    finally:
        await sandbox.shutdown()


@darwin_only
async def test_network_access_is_denied(tmp_path):
    sandbox = SandboxExecSandbox(tmp_path, "ses_live")
    try:
        outcome = await sandbox.exec("curl -sS --max-time 3 https://example.com")
        assert outcome.exit_code != 0
    finally:
        await sandbox.shutdown()


@darwin_only
async def test_scratch_space_is_writable_for_ordinary_temp_file_use(tmp_path):
    """TMPDIR is redirected into the per-sandbox scratch dir so tools that need
    a temp file (compilers, `python -c` with tempfile, pip's cache) work
    without a hole punched to the user's real temp directory."""
    sandbox = SandboxExecSandbox(tmp_path, "ses_live")
    try:
        outcome = await sandbox.exec(
            "python3 -c \"import tempfile; "
            "f = tempfile.NamedTemporaryFile(delete=False); "
            "f.write(b'ok'); f.close(); print(f.name)\""
        )
        assert outcome.exit_code == 0
        assert str(sandbox.scratch_dir) in outcome.output
    finally:
        await sandbox.shutdown()


@darwin_only
async def test_shutdown_removes_the_scratch_dir_and_profile(tmp_path):
    sandbox = SandboxExecSandbox(tmp_path, "ses_live")
    await sandbox.exec("true")
    scratch, profile = sandbox.scratch_dir, sandbox._profile_path

    await sandbox.shutdown()

    assert not scratch.exists()
    assert not profile.exists()
    # Idempotent, same guarantee the base class documents.
    await sandbox.shutdown()


@darwin_only
async def test_a_timeout_is_reported_not_raised(tmp_path):
    sandbox = SandboxExecSandbox(tmp_path, "ses_live")
    try:
        outcome = await sandbox.exec("sleep 5", timeout_s=1)
        assert outcome.timed_out is True
    finally:
        await sandbox.shutdown()
