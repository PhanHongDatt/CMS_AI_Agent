"""Gate G7: Policy Engine tests — full decision matrix."""

import uuid

import pytest

from core.policy.engine import PolicyEngine, PolicyRequest
from schemas.confidence import Confidence, ConfidenceSubScores, ConfidenceWeights
from schemas.incident import Severity
from schemas.policy import PolicyDecisionEnum, Risk


def _confidence(score: float) -> Confidence:
    """Build a valid Confidence with matching final_score.

    Setting all sub-scores to `score` yields final = score * sum(weights) = score * 1.0 = score.
    """
    w = ConfidenceWeights()
    sub = ConfidenceSubScores(
        evidence_quality=score,
        evidence_completeness=score,
        evidence_consistency=score,
        rca_agreement=score,
        model_output_quality=score,
        historical_success=score,
    )
    return Confidence(
        id=str(uuid.uuid4()),
        incident_id="inc-1",
        sub_scores=sub,
        weights=w,
        final_score=score,
        calibration_version="v1.0",
    )


def _req(
    severity: Severity = Severity.HIGH,
    risk: Risk = Risk.LOW,
    rollback_tested: bool = True,
    environment: str = "staging",
    confidence_score: float = 0.85,
    action_type: str = "restart_pod",
) -> PolicyRequest:
    return PolicyRequest(
        incident_id="inc-1",
        action_type=action_type,
        confidence=_confidence(confidence_score),
        severity=severity,
        risk=risk,
        blast_radius="single-pod",
        rollback_tested=rollback_tested,
        environment=environment,
    )


class TestPolicyEngine:
    def test_critical_severity_requires_approval(self):
        engine = PolicyEngine()
        pd = engine.evaluate(_req(severity=Severity.CRITICAL))
        assert pd.decision == PolicyDecisionEnum.REQUIRE_APPROVAL
        assert pd.rule_matched == "CRITICAL_SEVERITY"

    def test_high_risk_requires_approval_regardless_of_confidence(self):
        """Spec mandatory: confidence=0.92 + risk=HIGH → REQUIRE_APPROVAL."""
        engine = PolicyEngine()
        pd = engine.evaluate(_req(risk=Risk.HIGH, confidence_score=0.92))
        assert pd.decision == PolicyDecisionEnum.REQUIRE_APPROVAL
        assert pd.rule_matched == "HIGH_RISK"

    def test_high_confidence_never_auto_approves_high_risk(self):
        """Spec invariant: confidence > 0.80 alone NEVER grants AUTO for HIGH risk."""
        engine = PolicyEngine()
        pd = engine.evaluate(_req(risk=Risk.HIGH, confidence_score=0.99))
        assert pd.decision != PolicyDecisionEnum.ALLOW

    def test_production_medium_risk_requires_approval(self):
        engine = PolicyEngine()
        pd = engine.evaluate(_req(risk=Risk.MEDIUM, environment="production"))
        assert pd.decision == PolicyDecisionEnum.REQUIRE_APPROVAL
        assert pd.rule_matched == "PROD_MEDIUM_RISK"

    def test_rollback_not_tested_requires_approval(self):
        engine = PolicyEngine()
        pd = engine.evaluate(_req(rollback_tested=False))
        assert pd.decision == PolicyDecisionEnum.REQUIRE_APPROVAL
        assert pd.rule_matched == "ROLLBACK_NOT_TESTED"

    def test_low_confidence_denied(self):
        engine = PolicyEngine()
        pd = engine.evaluate(_req(confidence_score=0.50))
        assert pd.decision == PolicyDecisionEnum.DENY
        assert pd.rule_matched == "LOW_CONFIDENCE_DENY"

    def test_moderate_confidence_requires_approval(self):
        engine = PolicyEngine()
        pd = engine.evaluate(_req(confidence_score=0.70))
        assert pd.decision == PolicyDecisionEnum.REQUIRE_APPROVAL
        assert pd.rule_matched == "MODERATE_CONFIDENCE_APPROVAL"

    def test_high_confidence_low_risk_auto_allowed(self):
        engine = PolicyEngine()
        pd = engine.evaluate(
            _req(
                severity=Severity.HIGH,
                risk=Risk.LOW,
                rollback_tested=True,
                environment="staging",
                confidence_score=0.85,
            )
        )
        assert pd.decision == PolicyDecisionEnum.ALLOW
        assert pd.rule_matched == "HIGH_CONFIDENCE_LOW_RISK_AUTO"

    def test_policy_decision_includes_all_inputs(self):
        engine = PolicyEngine()
        pd = engine.evaluate(_req())
        assert pd.inputs.risk in Risk
        assert pd.inputs.severity in Severity
        assert pd.inputs.rollback_tested is True

    def test_policy_decision_has_id_and_reason(self):
        engine = PolicyEngine()
        pd = engine.evaluate(_req())
        assert pd.id
        assert pd.reason

    def test_default_deny_when_no_rule_matches(self):
        """Unknown combination → DEFAULT_DENY."""
        engine = PolicyEngine()
        # MEDIUM risk, staging, high confidence, rollback tested
        pd = engine.evaluate(
            _req(risk=Risk.MEDIUM, environment="staging", confidence_score=0.85)
        )
        # MEDIUM in staging is not covered by prod rule → falls to DEFAULT_DENY
        assert pd.decision == PolicyDecisionEnum.DENY
        assert pd.rule_matched == "DEFAULT_DENY"
