from __future__ import annotations

import pytest
from sani_core.permissions import (
    ALWAYS_CONFIRM,
    AUTO_FROM_START,
    TRUST_PROMOTION_THRESHOLD,
    ActionType,
    PermissionLocked,
    TrustLadder,
    evaluate,
)


def test_a_fresh_ladder_covers_every_action_type():
    ladder = TrustLadder()
    assert set(ladder.tiers) == set(ActionType)


@pytest.mark.parametrize("action_type", sorted(AUTO_FROM_START, key=lambda a: a.value))
def test_low_risk_actions_are_autonomous_from_the_first_step(action_type):
    assert evaluate(action_type, TrustLadder()).requires_approval is False


def test_untrusted_actions_start_gated_and_report_progress():
    ladder = TrustLadder()
    decision = evaluate(ActionType.SHELL_OTHER, ladder)
    assert decision.requires_approval is True
    assert f"0/{TRUST_PROMOTION_THRESHOLD}" in decision.reason


def test_the_ladder_promotes_at_the_threshold_and_not_before():
    ladder = TrustLadder()
    for _ in range(TRUST_PROMOTION_THRESHOLD - 1):
        ladder.record_manual_approval(ActionType.SHELL_OTHER)
        assert evaluate(ActionType.SHELL_OTHER, ladder).requires_approval is True

    ladder.record_manual_approval(ActionType.SHELL_OTHER)
    assert evaluate(ActionType.SHELL_OTHER, ladder).requires_approval is False


def test_one_rejection_revokes_earned_autonomy():
    ladder = TrustLadder()
    for _ in range(TRUST_PROMOTION_THRESHOLD):
        ladder.record_manual_approval(ActionType.SHELL_OTHER)
    assert ladder.tier(ActionType.SHELL_OTHER).auto_approve is True

    ladder.record_rejection(ActionType.SHELL_OTHER)
    assert ladder.tier(ActionType.SHELL_OTHER).auto_approve is False
    assert ladder.tier(ActionType.SHELL_OTHER).consecutive_approvals == 0
    assert evaluate(ActionType.SHELL_OTHER, ladder).requires_approval is True


def test_trust_is_tracked_per_action_type_not_globally():
    ladder = TrustLadder()
    for _ in range(TRUST_PROMOTION_THRESHOLD):
        ladder.record_manual_approval(ActionType.SHELL_OTHER)

    assert evaluate(ActionType.SHELL_OTHER, ladder).requires_approval is False
    # A sibling type learned nothing from that streak.
    assert ladder.tier(ActionType.DEPENDENCY_LOCKED).consecutive_approvals == 0


def test_set_auto_approve_refuses_locked_tiers_but_allows_turning_them_off():
    ladder = TrustLadder()
    with pytest.raises(PermissionLocked):
        ladder.set_auto_approve(ActionType.FILE_DELETE, True)

    # Explicitly disabling an already-blocked tier is a harmless no-op.
    ladder.set_auto_approve(ActionType.FILE_DELETE, False)
    assert evaluate(ActionType.FILE_DELETE, ladder).requires_approval is True


def test_disabling_a_tier_also_clears_its_streak():
    ladder = TrustLadder()
    ladder.record_manual_approval(ActionType.SHELL_OTHER)
    ladder.set_auto_approve(ActionType.SHELL_OTHER, False)
    assert ladder.tier(ActionType.SHELL_OTHER).consecutive_approvals == 0


def test_serialised_tiers_never_advertise_a_locked_tier_as_automatic():
    ladder = TrustLadder()
    ladder.tiers[ActionType.SHELL_NETWORK].auto_approve = True  # corrupt it directly
    assert ladder.to_dict()["shell.network"]["auto_approve"] is False
    assert ladder.to_dict()["shell.network"]["always_confirm"] is True


def test_the_two_tiers_are_disjoint_and_cover_the_spec():
    assert not (ALWAYS_CONFIRM & AUTO_FROM_START)
    assert len(ALWAYS_CONFIRM) == 7  # Section 5's six, plus browser navigation
