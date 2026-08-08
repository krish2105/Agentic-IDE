"""The always-confirm tier must be unbypassable.

Spec Section 10 calls this safety-critical and says to treat it as such. These
tests attack the tier from three directions: through the API, through a
maximally-permissive trust ladder, and through the classifier.
"""

from __future__ import annotations

import pytest
from sani_core.permissions import (
    ALWAYS_CONFIRM,
    AUTO_FROM_START,
    ActionType,
    TrustLadder,
    evaluate,
)

from .helpers import assert_parked, first, read_until, start_session

#: One plan step per always-confirm action type, and the type it must classify
#: as. If a future refactor lets any of these through, one of these fails.
ALWAYS_CONFIRM_CASES = [
    (
        "file.delete",
        {"tool": "file_editor", "params": {"op": "delete", "path": "scratch.tmp"}},
    ),
    (
        "path.outside_workspace",
        {"tool": "file_editor", "params": {"op": "write", "path": "../escaped.txt",
                                           "content": "nope"}},
    ),
    (
        "secret.access",
        {"tool": "file_editor", "params": {"op": "write", "path": ".env",
                                           "content": "API_KEY=leaked"}},
    ),
    (
        "shell.network",
        {"tool": "shell", "params": {"command": "curl https://example.com"}},
    ),
    (
        "dependency.new",
        {"tool": "shell", "params": {"command": "pip install requests"}},
    ),
    (
        "git.history_rewrite",
        {"tool": "shell", "params": {"command": "git push --force origin main"}},
    ),
]

#: Everything the API will let a client auto-approve. The always-confirm types
#: are deliberately absent -- setting them is itself an error, tested below.
MAX_AUTONOMY = {a.value: True for a in ActionType if a not in ALWAYS_CONFIRM}


def test_always_confirm_set_matches_the_spec():
    assert {a.value for a in ALWAYS_CONFIRM} == {
        "file.delete",
        "git.history_rewrite",
        "shell.network",
        "dependency.new",
        "secret.access",
        "path.outside_workspace",
    }
    assert not (ALWAYS_CONFIRM & AUTO_FROM_START), "no action can be in both tiers"


@pytest.mark.parametrize("expected_type,step", ALWAYS_CONFIRM_CASES, ids=[c[0] for c in ALWAYS_CONFIRM_CASES])
def test_always_confirm_action_blocks_at_maximum_autonomy(
    client, manager, workspace, expected_type, step
):
    """Every trust tier the API can enable is on, and it still stops."""
    script = [{"description": f"attempt {expected_type}", **step}]
    session_id = start_session(client, workspace, script, trust_overrides=MAX_AUTONOMY)

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        events = read_until(ws, "approval.required")
        approval = first(events, "approval.required")["data"]
        assert approval["action"]["action_type"] == expected_type
        assert "always-confirm" in approval["decision"]["reason"]

        # Nothing executed and nothing will until a human decides.
        assert_parked(manager, session_id)

    assert (workspace / "scratch.tmp").exists()
    assert not (workspace / ".env").exists()
    assert not (workspace.parent / "escaped.txt").exists()

    client.post(f"/session/{session_id}/kill")


@pytest.mark.parametrize("action_type", sorted(ALWAYS_CONFIRM, key=lambda a: a.value))
def test_engine_ignores_a_corrupted_ladder(action_type):
    """Defence in depth: even a ladder mutated past the API still gates.

    ``set_auto_approve`` refuses these, so this reaches around it and writes the
    flag directly -- simulating a bug, a bad deserialisation, or a future store
    that rehydrates untrusted state.
    """
    ladder = TrustLadder()
    ladder.tiers[action_type].auto_approve = True
    ladder.tiers[action_type].consecutive_approvals = 9999

    decision = evaluate(action_type, ladder)
    assert decision.requires_approval is True
    assert "always-confirm" in decision.reason


@pytest.mark.parametrize("action_type", sorted(ALWAYS_CONFIRM, key=lambda a: a.value))
def test_repeated_approvals_never_promote_an_always_confirm_type(action_type):
    ladder = TrustLadder()
    for _ in range(50):
        ladder.record_manual_approval(action_type)

    assert ladder.tier(action_type).auto_approve is False
    assert evaluate(action_type, ladder).requires_approval is True
    assert ladder.tier(action_type).to_dict()["auto_approve"] is False


def test_api_refuses_to_auto_approve_a_locked_tier(client, workspace):
    session_id = start_session(client, workspace, [])

    response = client.patch(
        f"/session/{session_id}/trust",
        json={"action_type": "file.delete", "auto_approve": True},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "permission_locked"

    tiers = client.get(f"/session/{session_id}/trust").json()["tiers"]
    assert tiers["file.delete"]["auto_approve"] is False
    assert tiers["file.delete"]["always_confirm"] is True


def test_creating_a_session_cannot_unlock_a_tier_either(client, workspace):
    response = client.post(
        "/session",
        json={
            "task": "sneak past the gate",
            "workspace": str(workspace),
            "script": [],
            "trust_overrides": {"shell.network": True},
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "permission_locked"


def test_symlink_out_of_the_workspace_is_caught(client, manager, workspace, tmp_path):
    """resolve() follows the link, so the escape is classified, not executed."""
    outside = tmp_path.parent / "outside_target.txt"
    outside.write_text("original\n")
    (workspace / "innocent.txt").symlink_to(outside)

    script = [
        {
            "description": "write through a symlink",
            "tool": "file_editor",
            "params": {"op": "write", "path": "innocent.txt", "content": "overwritten\n"},
        }
    ]
    session_id = start_session(client, workspace, script, trust_overrides=MAX_AUTONOMY)

    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        events = read_until(ws, "approval.required")
        approval = first(events, "approval.required")["data"]
        assert approval["action"]["action_type"] == "path.outside_workspace"
        assert_parked(manager, session_id)

    assert outside.read_text() == "original\n"
    client.post(f"/session/{session_id}/kill")
