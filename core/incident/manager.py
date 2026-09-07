"""Incident lifecycle manager.

Owns the state machine for each incident:
  RECEIVED → CORRELATED → INVESTIGATING → RCA_READY → CONFIDENCE_EVALUATED
  → POLICY_EVALUATED → WAITING_APPROVAL → APPROVED/DENIED → EXECUTING
  → VERIFYING → RESOLVED / ROLLBACK / ESCALATED
"""

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from core.incident.correlator import AlertCorrelator, AlertInput, CorrelationResult
from core.logging import get_logger
from core.logging import set_trace_id
from schemas.incident import Domain, Incident, IncidentStatus, Severity

logger = get_logger(__name__)

_SEVERITY_MAP: dict[str, Severity] = {
    "info": Severity.INFO,
    "low": Severity.LOW,
    "warning": Severity.LOW,
    "medium": Severity.MEDIUM,
    "high": Severity.HIGH,
    "critical": Severity.CRITICAL,
    "page": Severity.CRITICAL,
}


class IncidentManager:
    def __init__(
        self,
        correlator: AlertCorrelator,
        dedup_window_seconds: float = 300.0,
    ) -> None:
        self._correlator = correlator
        # incident_id → Incident (in-memory; replace with DB in Phase 9)
        self._incidents: dict[str, Incident] = {}

    def receive_alert(self, alert: AlertInput) -> tuple[Incident, bool]:
        """Process an incoming alert. Returns (incident, is_duplicate)."""
        trace_id = set_trace_id()
        new_id = str(uuid4())

        result = self._correlator.correlate(alert, new_id)

        if result.is_duplicate and result.incident_id:
            existing = self._incidents.get(result.incident_id)
            if existing and existing.status not in (
                IncidentStatus.RESOLVED, IncidentStatus.ESCALATED
            ):
                logger.info(
                    "alert_deduplicated",
                    incident_id=result.incident_id,
                    fingerprint=alert.fingerprint,
                )
                return existing, True

        # Create new incident
        severity = _SEVERITY_MAP.get(alert.severity.lower(), Severity.MEDIUM)
        try:
            domain = Domain(alert.domain)
        except ValueError:
            domain = Domain.INFRASTRUCTURE

        incident = Incident(
            id=new_id,  # type: ignore[arg-type]
            source=alert.source,
            fingerprint=alert.fingerprint,
            domain=domain,
            severity=severity,
            status=IncidentStatus.RECEIVED,
            trace_id=trace_id,
        )
        self._incidents[str(incident.id)] = incident
        self._correlator.associate(str(incident.id), alert)

        logger.info(
            "incident_created",
            incident_id=str(incident.id),
            severity=severity.value,
            domain=domain.value,
            fingerprint=alert.fingerprint,
        )
        return incident, False

    def transition(self, incident_id: str, new_status: IncidentStatus) -> Incident:
        """Advance incident to next status. Returns updated incident."""
        incident = self._get(incident_id)
        updated = incident.model_copy(
            update={"status": new_status, "updated_at": datetime.now(timezone.utc)}
        )
        self._incidents[incident_id] = updated
        logger.info(
            "incident_transition",
            incident_id=incident_id,
            from_status=incident.status.value,
            to_status=new_status.value,
        )
        return updated

    def attach_evidence(self, incident_id: str, evidence_ids: list[str]) -> Incident:
        incident = self._get(incident_id)
        merged = list(set(incident.evidence_ids + evidence_ids))
        updated = incident.model_copy(
            update={"evidence_ids": merged, "updated_at": datetime.now(timezone.utc)}
        )
        self._incidents[incident_id] = updated
        return updated

    def get(self, incident_id: str) -> Incident | None:
        return self._incidents.get(incident_id)

    def get_active(self) -> list[Incident]:
        terminal = {IncidentStatus.RESOLVED, IncidentStatus.ESCALATED, IncidentStatus.DENIED}
        return [i for i in self._incidents.values() if i.status not in terminal]

    def _get(self, incident_id: str) -> Incident:
        incident = self._incidents.get(incident_id)
        if incident is None:
            raise KeyError(f"Incident '{incident_id}' not found")
        return incident
