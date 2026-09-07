"""Gate G11: Gradual Autonomy tests."""

import pytest

from core.autonomy.level import AutonomyLevel, AutonomyRegistry


def _registry_with_outcomes(action: str, n_true: int, n_false: int = 0) -> AutonomyRegistry:
    reg = AutonomyRegistry()
    for _ in range(n_true):
        reg.record_outcome(action, True)
    for _ in range(n_false):
        reg.record_outcome(action, False)
    return reg


class TestAutonomyLevel:
    def test_default_level_is_l1_recommend(self):
        reg = AutonomyRegistry()
        assert reg.get_level("restart_pod") == AutonomyLevel.L1_RECOMMEND

    def test_cannot_promote_without_prerequisites(self):
        reg = AutonomyRegistry()
        result = reg.request_promotion("restart_pod", AutonomyLevel.L3_LOW_RISK_AUTO)
        assert not result
        assert reg.get_level("restart_pod") <= AutonomyLevel.L2_HUMAN_APPROVAL

    def test_cannot_promote_with_insufficient_outcomes(self):
        reg = _registry_with_outcomes("restart_pod", n_true=10)
        reg.set_rollback_tested("restart_pod", True)
        reg.approve_manual_review("restart_pod")
        result = reg.request_promotion("restart_pod", AutonomyLevel.L3_LOW_RISK_AUTO)
        assert not result  # < 20 outcomes

    def test_cannot_promote_without_rollback_tested(self):
        reg = _registry_with_outcomes("restart_pod", n_true=20)
        reg.approve_manual_review("restart_pod")
        result = reg.request_promotion("restart_pod", AutonomyLevel.L3_LOW_RISK_AUTO)
        assert not result

    def test_cannot_promote_without_manual_review(self):
        reg = _registry_with_outcomes("restart_pod", n_true=20)
        reg.set_rollback_tested("restart_pod", True)
        result = reg.request_promotion("restart_pod", AutonomyLevel.L3_LOW_RISK_AUTO)
        assert not result

    def test_promotes_to_l3_when_all_prerequisites_met(self):
        reg = _registry_with_outcomes("restart_pod", n_true=20)
        reg.set_rollback_tested("restart_pod", True)
        reg.approve_manual_review("restart_pod")
        result = reg.request_promotion("restart_pod", AutonomyLevel.L3_LOW_RISK_AUTO)
        assert result
        assert reg.get_level("restart_pod") == AutonomyLevel.L3_LOW_RISK_AUTO

    def test_low_success_rate_blocks_l3(self):
        reg = _registry_with_outcomes("restart_pod", n_true=10, n_false=15)
        reg.set_rollback_tested("restart_pod", True)
        reg.approve_manual_review("restart_pod")
        result = reg.request_promotion("restart_pod", AutonomyLevel.L3_LOW_RISK_AUTO)
        assert not result  # success_rate < 0.80

    def test_autonomy_is_per_action_type_not_global(self):
        """Spec: promote per action type, not globally."""
        reg = _registry_with_outcomes("restart_pod", n_true=20)
        reg.set_rollback_tested("restart_pod", True)
        reg.approve_manual_review("restart_pod")
        reg.request_promotion("restart_pod", AutonomyLevel.L3_LOW_RISK_AUTO)

        # scale_deployment has no outcomes — should stay at L1
        assert reg.get_level("scale_deployment") == AutonomyLevel.L1_RECOMMEND

    def test_no_jump_directly_to_l4_without_prerequisites(self):
        """Spec: do not jump directly to L4."""
        reg = AutonomyRegistry()
        result = reg.request_promotion("restart_pod", AutonomyLevel.L4_CONTROLLED_AUTONOMOUS)
        assert not result

    def test_get_summary_includes_all_metrics(self):
        reg = _registry_with_outcomes("restart_pod", n_true=5)
        reg.set_rollback_tested("restart_pod", True)
        summary = reg.get_summary()
        assert "restart_pod" in summary
        assert summary["restart_pod"]["outcomes"] == 5
        assert summary["restart_pod"]["rollback_tested"] is True

    def test_demotion_when_prerequisites_lost(self):
        """If prerequisites no longer met, effective level drops automatically."""
        reg = _registry_with_outcomes("restart_pod", n_true=20)
        reg.set_rollback_tested("restart_pod", True)
        reg.approve_manual_review("restart_pod")
        reg.request_promotion("restart_pod", AutonomyLevel.L3_LOW_RISK_AUTO)
        assert reg.get_level("restart_pod") == AutonomyLevel.L3_LOW_RISK_AUTO
        # Remove rollback_tested — should demote
        reg.set_rollback_tested("restart_pod", False)
        assert reg.get_level("restart_pod") <= AutonomyLevel.L2_HUMAN_APPROVAL
