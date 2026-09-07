"""Evidence context builder — assembles Evidence into an LLM-safe prompt block."""

from datetime import datetime, timezone

from schemas.evidence import Evidence, TrustLevel
from core.evidence.sanitizer import wrap_evidence_for_prompt

_STALE_THRESHOLD_SECONDS = 3600  # 1 hour


class EvidenceContextBuilder:
    """Builds a structured, prompt-injection-safe evidence context string."""

    def __init__(self, max_items: int = 20) -> None:
        self._max_items = max_items

    def build(self, evidence_list: list[Evidence]) -> str:
        valid = [e for e in evidence_list if self._is_valid(e)]
        if not valid:
            return wrap_evidence_for_prompt("No valid evidence available.")
        limited = valid[: self._max_items]
        lines = [self._format_item(i, e) for i, e in enumerate(limited, 1)]
        raw = "\n\n".join(lines)
        return wrap_evidence_for_prompt(raw)

    def _is_valid(self, e: Evidence) -> bool:
        now = datetime.now(timezone.utc)
        ttl = e.ttl_expires_at
        if ttl.tzinfo is None:
            ttl = ttl.replace(tzinfo=timezone.utc)
        return ttl > now

    def _format_item(self, index: int, e: Evidence) -> str:
        stale_warning = ""
        if e.freshness_seconds > _STALE_THRESHOLD_SECONDS:
            stale_warning = f" [WARNING: stale — {e.freshness_seconds:.0f}s old]"
        return (
            f"[{index}] source={e.source.value} entity={e.entity}\n"
            f"    query={e.metric_or_query}\n"
            f"    value={e.value}\n"
            f"    freshness={e.freshness_seconds:.1f}s{stale_warning}\n"
            f"    ref={e.source_reference}\n"
            f"    trust={TrustLevel.UNTRUSTED_DATA.value}"
        )
