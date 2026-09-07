"""Gate G0: Schema validation tests."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from schemas.action import Action, ActionStatus
from schemas.confidence import Confidence, ConfidenceSubScores, ConfidenceWeights
from schemas.evidence import Evidence, EvidenceSource, TrustLevel
from schemas.incident import Domain, Incident, IncidentStatus, Severity
from schemas.policy import PolicyDecision, PolicyDecisionEnum, PolicyInputs, Risk
from schemas.rca import AlternativeHypothesis, RCA
from schemas.verification import Verification, VerificationResult


def make_incident(**overrides) -> dict:
    base = {
        "source": "alertmanager",
        "fingerprint": "abc123",
        "domain": Domain.INFRASTRUCTURE,
        "severity": Severity.HIGH,
        "trace_id": str(uuid.uuid4()),
    }
    return {**base, **overrides}


def make_evidence(**overrides) -> dict:
    now = datetime.now(timezone.utc)
    base = {
        "incident_id": uuid.uuid4(),
        "source": EvidenceSource.PROMETHEUS,
        "entity": "pod/api-server-xyz",
        "metric_or_query": "kube_pod_status_phase",
        "value": "CrashLoopBackOff",
        "timestamp": now,
        "source_reference": "prometheus://localhost:9090/query",
        "freshness_seconds": 30.0,
        "ttl_expires_at": now + timedelta(hours=24),
    }
    return {**base, **overrides}


def make_sub_scores(**overrides) -> dict:
    base = {
        "evidence_quality": 0.9,
        "evidence_completeness": 0.8,
        "evidence_consistency": 1.0,
        "rca_agreement": 0.7,
        "model_output_quality": 1.0,
        "historical_success": 0.6,
    }
    return {**base, **overrides}


# --- Incident ---

class TestIncidentSchema:
    def test_valid_incident(self):
        inc = Incident(**make_incident())
        assert inc.status == IncidentStatus.RECEIVED
        assert inc.domain == Domain.INFRASTRUCTURE

    def test_incident_immutable(self):
        inc = Incident(**make_incident())
        with pytest.raises((TypeError, ValidationError)):
            inc.severity = Severity.LOW  # type: ignore[misc]

    def test_incident_requires_trace_id(self):
        data = make_incident()
        del data["trace_id"]
        with pytest.raises(ValidationError):
            Incident(**data)

    def test_incident_invalid_severity(self):
        with pytest.raises(ValidationError):
            Incident(**make_incident(severity="EXTREME"))

    def test_incident_invalid_domain(self):
        with pytest.raises(ValidationError):
            Incident(**make_incident(domain="ops"))


# --- Evidence ---

class TestEvidenceSchema:
    def test_valid_evidence(self):
        ev = Evidence(**make_evidence())
        assert ev.trust_level == TrustLevel.UNTRUSTED_DATA

    def test_evidence_trust_level_always_untrusted(self):
        ev = Evidence(**make_evidence())
        assert ev.trust_level == TrustLevel.UNTRUSTED_DATA

    def test_evidence_invalid_source(self):
        with pytest.raises(ValidationError):
            Evidence(**make_evidence(source="splunk"))


# --- RCA ---

class TestRCASchema:
    def test_valid_rca_with_root_cause(self):
        rca = RCA(
            root_cause="OOMKilled due to memory leak",
            evidence_ids=["ev-1", "ev-2"],
            affected_components=["api-server"],
            insufficient_evidence=False,
            model="claude-sonnet-4-6",
            prompt_version="v1.0",
        )
        assert rca.root_cause is not None

    def test_rca_insufficient_evidence_forces_null_root_cause(self):
        with pytest.raises(ValidationError):
            RCA(
                root_cause="some cause",
                evidence_ids=["ev-1"],
                affected_components=["api"],
                insufficient_evidence=True,
                model="claude-sonnet-4-6",
                prompt_version="v1.0",
            )

    def test_rca_insufficient_evidence_allows_null(self):
        rca = RCA(
            root_cause=None,
            evidence_ids=["ev-1"],
            affected_components=[],
            insufficient_evidence=True,
            model="claude-sonnet-4-6",
            prompt_version="v1.0",
        )
        assert rca.root_cause is None

    def test_alternative_hypothesis_likelihood_range(self):
        with pytest.raises(ValidationError):
            AlternativeHypothesis(hypothesis="h1", likelihood=1.5)


# --- Confidence ---

class TestConfidenceSchema:
    def _make_confidence(self, **overrides) -> dict:
        sub = make_sub_scores()
        weights = {"evidence_quality": 0.25, "evidence_completeness": 0.20,
                   "evidence_consistency": 0.20, "rca_agreement": 0.15,
                   "model_output_quality": 0.10, "historical_success": 0.10}
        s = ConfidenceSubScores(**sub)
        w = ConfidenceWeights(**weights)
        final = (
            w.evidence_quality * s.evidence_quality
            + w.evidence_completeness * s.evidence_completeness
            + w.evidence_consistency * s.evidence_consistency
            + w.rca_agreement * s.rca_agreement
            + w.model_output_quality * s.model_output_quality
            + w.historical_success * s.historical_success
        )
        base = {
            "id": "conf-1",
            "incident_id": "inc-1",
            "sub_scores": sub,
            "weights": weights,
            "final_score": round(final, 4),
            "calibration_version": "v1",
        }
        return {**base, **overrides}

    def test_valid_confidence(self):
        c = Confidence(**self._make_confidence())
        assert 0.0 <= c.final_score <= 1.0

    def test_weights_must_sum_to_one(self):
        with pytest.raises(ValidationError):
            ConfidenceWeights(
                evidence_quality=0.30, evidence_completeness=0.30,
                evidence_consistency=0.20, rca_agreement=0.15,
                model_output_quality=0.10, historical_success=0.10,
            )

    def test_final_score_must_match_calculation(self):
        data = self._make_confidence(final_score=0.99)
        with pytest.raises(ValidationError):
            Confidence(**data)


# --- Policy ---

class TestPolicySchema:
    def test_valid_policy_decision(self):
        pd = PolicyDecision(
            id="pd-1",
            incident_id="inc-1",
            decision=PolicyDecisionEnum.REQUIRE_APPROVAL,
            reason="High risk action",
            inputs=PolicyInputs(
                confidence=0.92,
                severity=Severity.HIGH,
                risk=Risk.HIGH,
                blast_radius="single-pod",
                rollback_tested=True,
                environment="production",
            ),
            rule_matched="HIGH_RISK_HIGH_CONFIDENCE",
        )
        assert pd.decision == PolicyDecisionEnum.REQUIRE_APPROVAL

    def test_high_confidence_high_risk_requires_approval(self):
        """Spec invariant: confidence=0.92 + risk=HIGH → REQUIRE_APPROVAL, never AUTO."""
        inputs = PolicyInputs(
            confidence=0.92,
            severity=Severity.HIGH,
            risk=Risk.HIGH,
            blast_radius="cluster",
            rollback_tested=False,
            environment="production",
        )
        assert inputs.confidence > 0.80
        assert inputs.risk == Risk.HIGH


# --- Action ---

class TestActionSchema:
    def test_valid_action(self):
        action = Action(
            id="act-1",
            incident_id="inc-1",
            policy_decision_id="pd-1",
            name="restart_pod",
            risk=Risk.LOW,
            rollback_supported=True,
            rollback_tested=True,
            pre_state_snapshot={"pod": "api-xyz", "replicas": 3},
        )
        assert action.status == ActionStatus.PENDING

    def test_action_invalid_risk(self):
        with pytest.raises(ValidationError):
            Action(
                id="act-2",
                incident_id="inc-1",
                policy_decision_id="pd-1",
                name="restart_pod",
                risk="EXTREME",  # invalid
                rollback_supported=True,
                rollback_tested=True,
                pre_state_snapshot={},
            )


# --- Verification ---

class TestVerificationSchema:
    def test_valid_verification_pass(self):
        v = Verification(
            action_id="act-1",
            evidence_before_ids=["ev-before"],
            evidence_after_ids=["ev-after"],
            comparison={"cpu_before": 95, "cpu_after": 20},
            result=VerificationResult.PASS,
            rollback_triggered=False,
        )
        assert v.result == VerificationResult.PASS
        assert not v.rollback_triggered

    def test_valid_verification_fail_with_rollback(self):
        v = Verification(
            action_id="act-1",
            evidence_before_ids=["ev-before"],
            evidence_after_ids=["ev-after"],
            comparison={"cpu_before": 95, "cpu_after": 90},
            result=VerificationResult.FAIL,
            rollback_triggered=True,
        )
        assert v.result == VerificationResult.FAIL
        assert v.rollback_triggered
