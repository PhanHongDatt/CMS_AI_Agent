"""Alert correlation and deduplication.

Rules:
- Same fingerprint within dedup_window → same incident.
- Different fingerprints → separate incidents.
- Repeated alert on unresolved incident → extend the same lifecycle.
- Only correlated if same domain (infrastructure vs business).
"""

import hashlib
import time
from dataclasses import dataclass, field


@dataclass
class AlertInput:
    source: str
    fingerprint: str
    domain: str          # "infrastructure" | "business"
    severity: str
    labels: dict[str, str] = field(default_factory=dict)
    annotations: dict[str, str] = field(default_factory=dict)
    received_at: float = field(default_factory=time.time)


@dataclass
class CorrelationResult:
    incident_id: str | None   # None = new incident needed
    is_duplicate: bool
    fingerprint: str


class AlertCorrelator:
    """In-memory correlator. Replace with Redis-backed in production."""

    def __init__(self, dedup_window_seconds: float = 300.0) -> None:
        self._dedup_window = dedup_window_seconds
        # fingerprint → (incident_id, last_seen_at, domain)
        self._active: dict[str, tuple[str, float, str]] = {}

    def correlate(self, alert: AlertInput, incident_id_for_new: str) -> CorrelationResult:
        """Return existing incident_id if within dedup window, else signal new."""
        now = time.time()
        self._evict_stale(now)

        key = self._correlation_key(alert)

        if key in self._active:
            existing_id, last_seen, domain = self._active[key]
            if domain == alert.domain:
                # Refresh last_seen
                self._active[key] = (existing_id, now, domain)
                return CorrelationResult(
                    incident_id=existing_id,
                    is_duplicate=True,
                    fingerprint=alert.fingerprint,
                )

        # New incident
        self._active[key] = (incident_id_for_new, now, alert.domain)
        return CorrelationResult(
            incident_id=None,
            is_duplicate=False,
            fingerprint=alert.fingerprint,
        )

    def associate(self, incident_id: str, alert: AlertInput) -> None:
        """Mark an existing incident as the owner of this alert's fingerprint."""
        key = self._correlation_key(alert)
        self._active[key] = (incident_id, time.time(), alert.domain)

    def active_count(self) -> int:
        self._evict_stale(time.time())
        return len(self._active)

    def _correlation_key(self, alert: AlertInput) -> str:
        return f"{alert.domain}:{alert.fingerprint}"

    def _evict_stale(self, now: float) -> None:
        expired = [
            k for k, (_, last_seen, _) in self._active.items()
            if now - last_seen > self._dedup_window
        ]
        for k in expired:
            del self._active[k]
