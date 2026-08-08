"""The agent's shell must execute through the session sandbox.

Phase 1 shipped a sandbox that only covered the human's terminal, so switching
to Docker moved the person and left the agent on the host. These tests exist so
that gap cannot silently reopen: they assert the wiring, not just the output.
"""

from __future__ import annotations

import pytest
from sani_core.runners import CommandOutcome, CommandRunner, LocalCommandRunner
from sani_core.tools import build_tools
from sani_core.tools.shell import ShellTool
from sani_server.runner import SandboxCommandRunner
from sani_server.sandbox import build_sandbox
from sani_server.sandbox.docker import CONTAINER_WORKDIR, DockerSandbox

from .helpers import first, read_until, start_session


class RecordingRunner(CommandRunner):
    kind = "recording"

    def __init__(self) -> None:
        self.commands: list[str] = []

    async def run(self, command, *, cwd, timeout_s=120):
        self.commands.append(command)
        return CommandOutcome(exit_code=0, output=f"ran {command}")

    def describe(self) -> dict:
        return {"kind": self.kind, "isolated": True}


# ---- core seam --------------------------------------------------------------


async def test_the_shell_tool_delegates_instead_of_spawning(tmp_path):
    from sani_core.plan import PlanStep

    runner = RecordingRunner()
    tool = ShellTool(tmp_path, runner=runner)
    step = PlanStep(index=0, description="x", tool="shell", params={"command": "echo hi"})

    action = tool.propose(step)
    result = tool.result(action, await tool.execute(action))

    assert runner.commands == ["echo hi"]
    assert result.ok is True
    assert result.data["runs_in"] == "recording"


def test_the_proposal_says_where_the_command_will_run(tmp_path):
    """Shown before approval: host and container are different decisions."""
    from sani_core.plan import PlanStep

    step = PlanStep(index=0, description="x", tool="shell", params={"command": "ls"})

    on_host = ShellTool(tmp_path).propose(step)
    assert on_host.preview["runs_in"] == {"kind": "host", "isolated": False}

    sandboxed = ShellTool(tmp_path, runner=RecordingRunner()).propose(step)
    assert sandboxed.preview["runs_in"]["isolated"] is True


def test_the_default_runner_is_the_honest_one(tmp_path):
    """No runner injected means the host, and it must not pretend otherwise."""
    tool = ShellTool(tmp_path)
    assert isinstance(tool.runner, LocalCommandRunner)
    assert tool.runner.describe() == {"kind": "host", "isolated": False}


def test_build_tools_passes_the_runner_to_every_adapter(tmp_path):
    runner = RecordingRunner()
    tools = build_tools(["file_editor", "shell"], tmp_path, runner=runner)
    assert tools["shell"].runner is runner
    # The file editor takes one for uniform construction and simply ignores it.
    assert tools["file_editor"].runner is runner


async def test_a_timeout_is_reported_not_raised(tmp_path):
    tool = ShellTool(tmp_path, timeout_s=1)
    from sani_core.plan import PlanStep

    action = tool.propose(
        PlanStep(index=0, description="x", tool="shell", params={"command": "sleep 5"})
    )
    result = tool.result(action, await tool.execute(action))
    assert result.ok is False
    assert result.data["timed_out"] is True


# ---- server wiring ----------------------------------------------------------


async def test_sessions_wire_the_shell_tool_to_their_sandbox(manager, workspace):
    record = manager.create(task="t", workspace=str(workspace), script=[])
    runner = record.executor.tools["shell"].runner

    assert isinstance(runner, SandboxCommandRunner)
    assert runner.sandbox is record.sandbox
    await manager.kill(record.session.id)


def test_the_local_sandbox_runner_admits_it_is_the_host(tmp_path):
    runner = SandboxCommandRunner(build_sandbox(tmp_path, "ses_x", "local"))
    assert runner.kind == "host"
    assert runner.describe() == {"kind": "host", "sandbox": "local", "isolated": False}


def test_the_docker_sandbox_runner_reports_containment(tmp_path):
    runner = SandboxCommandRunner(build_sandbox(tmp_path, "ses_x", "docker"))
    assert runner.kind == "container"
    assert runner.describe()["isolated"] is True


def test_docker_exec_argv_is_correct(tmp_path):
    """The one part of the Docker path testable without a daemon."""
    sandbox = DockerSandbox(tmp_path, "ses_abc")
    argv = sandbox.exec_argv("pytest -q && echo done")

    assert argv[:2] == ["docker", "exec"]
    assert "sani-ses_abc" in argv
    assert argv[argv.index("--workdir") + 1] == CONTAINER_WORKDIR
    # The command is one argv element, so the shell inside the container parses
    # it -- not the host shell, and not docker's own argument splitting.
    assert argv[-3:] == ["/bin/sh", "-c", "pytest -q && echo done"]


async def test_a_real_command_still_runs_and_returns_output(manager, workspace):
    record = manager.create(task="t", workspace=str(workspace), script=[])
    outcome = await record.sandbox.exec("echo sandbox-path-works")
    assert outcome.exit_code == 0
    assert "sandbox-path-works" in outcome.output
    await manager.kill(record.session.id)


def test_end_to_end_a_planned_command_runs_through_the_sandbox(client, workspace):
    script = [
        {
            "description": "print the marker",
            "tool": "shell",
            "params": {"command": "echo routed-through-sandbox"},
        }
    ]
    session_id = start_session(
        client, workspace, script, trust_overrides={"shell.other": True}
    )

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        events = read_until(ws, "session.complete")

    proposed = first(events, "tool.proposed")["data"]["action"]
    assert proposed["preview"]["runs_in"]["sandbox"] == "local"

    result = first(events, "tool.result")["data"]["result"]
    assert result["ok"] is True
    assert "routed-through-sandbox" in result["output"]
    assert result["data"]["runs_in"] == "host"


def test_the_always_confirm_tier_still_gates_sandboxed_commands(client, workspace):
    """Sandboxing changes where a command runs, never whether it is allowed."""
    script = [
        {
            "description": "reach the network",
            "tool": "shell",
            "params": {"command": "curl https://example.com"},
        }
    ]
    session_id = start_session(
        client, workspace, script, trust_overrides={"shell.other": True}
    )

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        events = read_until(ws, "approval.required")

    approval = first(events, "approval.required")["data"]
    assert approval["action"]["action_type"] == "shell.network"
    client.post(f"/session/{session_id}/kill")
