"""Confidence Engine — fully deterministic, no LLM calls.

Sub-score rules (from spec Section 5.4):

evidence_quality:      freshness score; 1.0 under 5 min, linear to 0 at 60 min.
evidence_completeness: available / expected sources for incident type.
evidence_consistency:  deterministic conflict detection (never LLM-scored).
rca_agreement:         neutral 0.7 until multi-run RCA exists.
model_output_quality:  1.0 first-pass valid JSON, 0.5 after parse retry, 0 after repeated failure.
historical_success:    cold-start prior 0.6; EMA after >=20 verified outcomes per type.
"""

import uuid
from datetime import datetime, timezone
from typing import Sequence

from schemas.confidence import Confidence, ConfidenceSubScores, ConfidenceWeights
from schemas.evidence import Evidence, EvidenceSource
from schemas.rca import RCA

_CALIBRATION_VERSION = "v1.0"

# Freshness thresholds
_FRESH_SECONDS = 300.0    # 1.0 score below this
_STALE_SECONDS = 3600.0   # 0.0 score above this

# Expected sources per incident type (completeness)
_EXPECTED_SOURCES: dict[str, set[EvidenceSource]] = {
    "infrastructure": {EvidenceSource.KUBERNETES, EvidenceSource.PROMETHEUS},
    "business": {EvidenceSource.ERPNEXT},
    "default": {EvidenceSource.PROMETHEUS},
}

# Cold-start EMA prior
_HISTORICAL_COLD_START = 0.6


class ConfidenceEngine:
    """Calculate deterministic confidence score for an RCA."""

    def __init__(self) -> None:
        # incident_type → list of bool outcomes (True=resolved-correctly)
        self._outcomes: dict[str, list[bool]] = {}

    def calculate(
        self,
        incident_id: str,
        incident_type: str,  # "infrastructure" | "business"
        rca: RCA,
        evidence: Sequence[Evidence],
        model_output_quality: float = 1.0,
    ) -> Confidence:
        sub = ConfidenceSubScores(
            evidence_quality=self._evidence_quality(evidence),
            evidence_completeness=self._evidence_completeness(incident_type, evidence),
            evidence_consistency=self._evidence_consistency(evidence),
            rca_agreement=self._rca_agreement(),
            model_output_quality=max(0.0, min(1.0, model_output_quality)),
            historical_success=self._historical_success(incident_type),
        )
        weights = ConfidenceWeights()
        final = round(
            weights.evidence_quality * sub.evidence_quality
            + weights.evidence_completeness * sub.evidence_completeness
            + weights.evidence_consistency * sub.evidence_consistency
            + weights.rca_agreement * sub.rca_agreement
            + weights.model_output_quality * sub.model_output_quality
            + weights.historical_success * sub.historical_success,
            4,
        )
        return Confidence(
            id=str(uuid.uuid4()),
            incident_id=incident_id,
            sub_scores=sub,
            weights=weights,
            final_score=final,
            calibration_version=_CALIBRATION_VERSION,
        )

    def record_outcome(self, incident_type: str, resolved_correctly: bool) -> None:
        """Feed verified outcome into EMA for historical_success calibration."""
        self._outcomes.setdefault(incident_type, []).append(resolved_correctly)

    # --- sub-score implementations ---

    def _evidence_quality(self, evidence: Sequence[Evidence]) -> float:
        if not evidence:
            return 0.0
        scores = [self._freshness_score(e.freshness_seconds) for e in evidence]
        return sum(scores) / len(scores)

    def _freshness_score(self, freshness_seconds: float) -> float:
        if freshness_seconds <= _FRESH_SECONDS:
            return 1.0
        if freshness_seconds >= _STALE_SECONDS:
            return 0.0
        span = _STALE_SECONDS - _FRESH_SECONDS
        return 1.0 - (freshness_seconds - _FRESH_SECONDS) / span

    def _evidence_completeness(
        self, incident_type: str, evidence: Sequence[Evidence]
    ) -> float:
        expected = _EXPECTED_SOURCES.get(incident_type, _EXPECTED_SOURCES["default"])
        if not expected:
            return 1.0
        available = {e.source for e in evidence}
        return len(available & expected) / len(expected)

    def _evidence_consistency(self, evidence: Sequence[Evidence]) -> float:
        """Deterministic conflict detection.

        Conflict: two evidence items from the same source and entity report
        contradictory numeric values (both > 0 but differ by > 50%).
        """
        # Group numeric values by (source, entity, metric)
        groups: dict[tuple, list[float]] = {}
        for e in evidence:
            if isinstance(e.value, (int, float)):
                key = (e.source, e.entity, e.metric_or_query)
                groups.setdefault(key, []).append(float(e.value))

        for values in groups.values():
            if len(values) >= 2:
                mn, mx = min(values), max(values)
                if mn > 0 and mx / mn > 2.0:
                    return 0.5  # conflict detected

        return 1.0

    def _rca_agreement(self) -> float:
        # Neutral 0.7 until multi-run RCA implemented
        return 0.7

    def _historical_success(self, incident_type: str) -> float:
        outcomes = self._outcomes.get(incident_type, [])
        if len(outcomes) < 20:
            return _HISTORICAL_COLD_START
        # EMA with alpha=0.1
        ema = float(outcomes[0])
        for outcome in outcomes[1:]:
            ema = 0.1 * float(outcome) + 0.9 * ema
        return round(ema, 4)
