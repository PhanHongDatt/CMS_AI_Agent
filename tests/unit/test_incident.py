"""Gate G4: Alert correlation + Incident Manager tests."""

import time
import uuid

import pytest

from core.incident.correlator import AlertCorrelator, AlertInput
from core.incident.manager import IncidentManager
from schemas.incident import Domain, IncidentStatus, Severity


def _alert(fingerprint: str = "fp-001", domain: str = "infrastructure", severity: str = "high") -> AlertInput:
    return AlertInput(
        source="alertmanager",
        fingerprint=fingerprint,
        domain=domain,
        severity=severity,
    )


class TestAlertCorrelator:
    def test_first_alert_returns_new(self):
        c = AlertCorrelator(dedup_window_seconds=300)
        result = c.correlate(_alert("fp-001"), "inc-new")
        assert not result.is_duplicate
        assert result.incident_id is None

    def test_duplicate_within_window_returns_existing(self):
        c = AlertCorrelator(dedup_window_seconds=300)
        c.correlate(_alert("fp-001"), "inc-A")
        c.associate("inc-A", _alert("fp-001"))
        result = c.correlate(_alert("fp-001"), "inc-new")
        assert result.is_duplicate
        assert result.incident_id == "inc-A"

    def test_different_fingerprints_create_separate_incidents(self):
        c = AlertCorrelator(dedup_window_seconds=300)
        r1 = c.correlate(_alert("fp-001"), "inc-A")
        c.associate("inc-A", _alert("fp-001"))
        r2 = c.correlate(_alert("fp-002"), "inc-B")
        assert not r2.is_duplicate
        assert r2.incident_id is None

    def test_different_domains_not_correlated(self):
        c = AlertCorrelator(dedup_window_seconds=300)
        c.correlate(_alert("fp-shared", "infrastructure"), "inc-A")
        c.associate("inc-A", _alert("fp-shared", "infrastructure"))
        r = c.correlate(_alert("fp-shared", "business"), "inc-B")
        assert not r.is_duplicate

    def test_stale_entry_evicted(self):
        c = AlertCorrelator(dedup_window_seconds=0.05)
        c.correlate(_alert("fp-001"), "inc-A")
        c.associate("inc-A", _alert("fp-001"))
        time.sleep(0.1)
        result = c.correlate(_alert("fp-001"), "inc-new")
        assert not result.is_duplicate  # stale → treated as new


class TestIncidentManager:
    def _manager(self) -> IncidentManager:
        return IncidentManager(AlertCorrelator(dedup_window_seconds=300))

    def test_creates_incident_on_first_alert(self):
        mgr = self._manager()
        inc, is_dup = mgr.receive_alert(_alert())
        assert not is_dup
        assert inc.status == IncidentStatus.RECEIVED
        assert inc.domain == Domain.INFRASTRUCTURE

    def test_deduplicates_same_alert(self):
        mgr = self._manager()
        inc1, _ = mgr.receive_alert(_alert("fp-dup"))
        inc2, is_dup = mgr.receive_alert(_alert("fp-dup"))
        assert is_dup
        assert str(inc1.id) == str(inc2.id)

    def test_50_identical_alerts_create_1_incident(self):
        mgr = self._manager()
        incidents = []
        for _ in range(50):
            inc, _ = mgr.receive_alert(_alert("fp-mass"))
            incidents.append(str(inc.id))
        assert len(set(incidents)) == 1

    def test_different_fingerprints_create_separate_incidents(self):
        mgr = self._manager()
        inc1, _ = mgr.receive_alert(_alert("fp-A"))
        inc2, _ = mgr.receive_alert(_alert("fp-B"))
        assert str(inc1.id) != str(inc2.id)

    def test_transition_updates_status(self):
        mgr = self._manager()
        inc, _ = mgr.receive_alert(_alert())
        updated = mgr.transition(str(inc.id), IncidentStatus.INVESTIGATING)
        assert updated.status == IncidentStatus.INVESTIGATING

    def test_transition_nonexistent_raises(self):
        mgr = self._manager()
        with pytest.raises(KeyError):
            mgr.transition("nonexistent-id", IncidentStatus.RESOLVED)

    def test_attach_evidence(self):
        mgr = self._manager()
        inc, _ = mgr.receive_alert(_alert())
        updated = mgr.attach_evidence(str(inc.id), ["ev-1", "ev-2"])
        assert "ev-1" in updated.evidence_ids
        assert "ev-2" in updated.evidence_ids

    def test_attach_evidence_deduplicates(self):
        mgr = self._manager()
        inc, _ = mgr.receive_alert(_alert())
        mgr.attach_evidence(str(inc.id), ["ev-1"])
        updated = mgr.attach_evidence(str(inc.id), ["ev-1", "ev-2"])
        assert updated.evidence_ids.count("ev-1") == 1

    def test_get_active_excludes_resolved(self):
        mgr = self._manager()
        inc, _ = mgr.receive_alert(_alert("fp-A"))
        mgr.transition(str(inc.id), IncidentStatus.RESOLVED)
        inc2, _ = mgr.receive_alert(_alert("fp-B"))
        active = mgr.get_active()
        ids = [str(i.id) for i in active]
        assert str(inc.id) not in ids
        assert str(inc2.id) in ids

    def test_repeated_alert_on_unresolved_same_lifecycle(self):
        """Spec: Repeated alert on unresolved incident → same lifecycle."""
        mgr = self._manager()
        inc, _ = mgr.receive_alert(_alert("fp-X"))
        mgr.transition(str(inc.id), IncidentStatus.INVESTIGATING)
        inc2, is_dup = mgr.receive_alert(_alert("fp-X"))
        assert is_dup
        assert str(inc2.id) == str(inc.id)

    def test_severity_mapping(self):
        mgr = self._manager()
        inc, _ = mgr.receive_alert(_alert(severity="critical"))
        assert inc.severity == Severity.CRITICAL

        inc2, _ = mgr.receive_alert(_alert("fp-info", severity="info"))
        assert inc2.severity == Severity.INFO
