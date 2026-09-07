"""Gate G6: Confidence Engine tests — all deterministic."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from core.confidence.engine import ConfidenceEngine
from schemas.confidence import Confidence
from schemas.evidence import Evidence, EvidenceSource, TrustLevel
from schemas.rca import RCA


def _ev(
    source: EvidenceSource = EvidenceSource.PROMETHEUS,
    freshness: float = 30.0,
    value=1.0,
    entity: str = "api",
    metric: str = "up",
) -> Evidence:
    now = datetime.now(timezone.utc)
    return Evidence(
        incident_id=uuid.uuid4(),
        source=source,
        entity=entity,
        metric_or_query=metric,
        value=value,
        timestamp=now,
        source_reference="prometheus://localhost:9090",
        freshness_seconds=freshness,
        ttl_expires_at=now + timedelta(hours=24),
    )


def _rca(insufficient: bool = False) -> RCA:
    return RCA(
        root_cause=None if insufficient else "OOM",
        evidence_ids=[],
        affected_components=["api"],
        insufficient_evidence=insufficient,
        model="claude-sonnet-4-6",
        prompt_version="v1.0",
    )


class TestConfidenceEngine:
    def test_score_in_range(self):
        engine = ConfidenceEngine()
        ev = _ev(freshness=30.0)
        c = engine.calculate("inc-1", "infrastructure", _rca(), [ev])
        assert 0.0 <= c.final_score <= 1.0

    def test_fresh_evidence_higher_quality_than_stale(self):
        engine = ConfidenceEngine()
        fresh_ev = _ev(freshness=10.0)
        stale_ev = _ev(freshness=5000.0)
        c_fresh = engine.calculate("inc-1", "infrastructure", _rca(), [fresh_ev])
        c_stale = engine.calculate("inc-2", "infrastructure", _rca(), [stale_ev])
        assert c_fresh.sub_scores.evidence_quality > c_stale.sub_scores.evidence_quality

    def test_no_evidence_returns_low_quality(self):
        engine = ConfidenceEngine()
        c = engine.calculate("inc-1", "infrastructure", _rca(), [])
        assert c.sub_scores.evidence_quality == 0.0
        assert c.sub_scores.evidence_completeness == 0.0

    def test_missing_expected_source_lowers_completeness(self):
        engine = ConfidenceEngine()
        # infrastructure expects K8s + Prometheus; only Prometheus present
        ev = _ev(source=EvidenceSource.PROMETHEUS)
        c = engine.calculate("inc-1", "infrastructure", _rca(), [ev])
        assert c.sub_scores.evidence_completeness == 0.5  # 1 of 2 sources

    def test_all_expected_sources_full_completeness(self):
        engine = ConfidenceEngine()
        ev1 = _ev(source=EvidenceSource.PROMETHEUS)
        ev2 = _ev(source=EvidenceSource.KUBERNETES)
        c = engine.calculate("inc-1", "infrastructure", _rca(), [ev1, ev2])
        assert c.sub_scores.evidence_completeness == 1.0

    def test_conflicting_evidence_lowers_consistency(self):
        engine = ConfidenceEngine()
        ev1 = _ev(source=EvidenceSource.PROMETHEUS, value=10.0, entity="api", metric="cpu")
        ev2 = _ev(source=EvidenceSource.PROMETHEUS, value=80.0, entity="api", metric="cpu")
        c = engine.calculate("inc-1", "infrastructure", _rca(), [ev1, ev2])
        assert c.sub_scores.evidence_consistency < 1.0

    def test_consistent_evidence_full_consistency(self):
        engine = ConfidenceEngine()
        ev = _ev(source=EvidenceSource.PROMETHEUS, value=95.0, entity="api", metric="cpu")
        c = engine.calculate("inc-1", "infrastructure", _rca(), [ev])
        assert c.sub_scores.evidence_consistency == 1.0

    def test_rca_agreement_neutral_before_calibration(self):
        engine = ConfidenceEngine()
        c = engine.calculate("inc-1", "infrastructure", _rca(), [_ev()])
        assert c.sub_scores.rca_agreement == 0.7

    def test_cold_start_historical_prior(self):
        engine = ConfidenceEngine()
        c = engine.calculate("inc-1", "infrastructure", _rca(), [_ev()])
        assert c.sub_scores.historical_success == 0.6

    def test_historical_success_updates_after_20_outcomes(self):
        engine = ConfidenceEngine()
        for _ in range(20):
            engine.record_outcome("infrastructure", True)
        c = engine.calculate("inc-1", "infrastructure", _rca(), [_ev()])
        assert c.sub_scores.historical_success > 0.6  # EMA of all True

    def test_cold_start_does_not_dominate_score(self):
        """Spec: cold-start historical prior must not dominate the score."""
        engine = ConfidenceEngine()
        c = engine.calculate("inc-1", "infrastructure", _rca(), [_ev(freshness=10.0)])
        # historical_success weight is 0.10, so it contributes at most 0.06
        contribution = c.weights.historical_success * c.sub_scores.historical_success
        assert contribution < 0.10

    def test_model_output_quality_0_5_on_retry(self):
        engine = ConfidenceEngine()
        c_good = engine.calculate("inc-1", "infra", _rca(), [_ev()], model_output_quality=1.0)
        c_retry = engine.calculate("inc-2", "infra", _rca(), [_ev()], model_output_quality=0.5)
        assert c_retry.sub_scores.model_output_quality == 0.5
        assert c_good.sub_scores.model_output_quality > c_retry.sub_scores.model_output_quality

    def test_reproducible_for_identical_inputs(self):
        """Spec: reproducible calculation for identical inputs."""
        engine = ConfidenceEngine()
        ev = _ev(freshness=100.0)
        c1 = engine.calculate("inc-X", "infrastructure", _rca(), [ev])
        c2 = engine.calculate("inc-X", "infrastructure", _rca(), [ev])
        assert c1.final_score == c2.final_score
        assert c1.sub_scores == c2.sub_scores
