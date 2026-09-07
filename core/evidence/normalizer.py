"""Normalize MCP ToolResult → Evidence schema."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from mcp.base import ToolResult
from schemas.evidence import Evidence, EvidenceSource, TrustLevel
from core.evidence.sanitizer import sanitize_evidence_value

_FRESHNESS_GOOD_SECONDS = 300      # 5 min
_TTL_HOURS = 24

_SOURCE_MAP: dict[str, EvidenceSource] = {
    "k8s_get_cluster_health": EvidenceSource.KUBERNETES,
    "k8s_get_pod_logs": EvidenceSource.KUBERNETES,
    "k8s_get_events": EvidenceSource.KUBERNETES,
    "k8s_describe_resource": EvidenceSource.KUBERNETES,
    "k8s_get_storage_health": EvidenceSource.KUBERNETES,
    "prometheus_query": EvidenceSource.PROMETHEUS,
    "prometheus_query_range": EvidenceSource.PROMETHEUS,
    "opensearch_query": EvidenceSource.OPENSEARCH,
    "opensearch_get_log_errors": EvidenceSource.OPENSEARCH,
    "aws_get_ec2_health": EvidenceSource.AWS,
    "aws_get_nlb_target_health": EvidenceSource.AWS,
    "aws_check_s3_backups": EvidenceSource.AWS,
}


def normalize_mcp_result(
    result: ToolResult,
    incident_id: UUID,
    entity: str,
    metric_or_query: str,
) -> Evidence:
    """Convert a ToolResult into a validated Evidence record."""
    fetched_at = datetime.fromisoformat(result.fetched_at)
    now = datetime.now(timezone.utc)

    # Make fetched_at timezone-aware if naive
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)

    freshness_seconds = (now - fetched_at).total_seconds()
    ttl_expires_at = now + timedelta(hours=_TTL_HOURS)

    source = _SOURCE_MAP.get(result.tool, EvidenceSource.KUBERNETES)
    sanitized_value = sanitize_evidence_value(result.data)

    return Evidence(
        incident_id=incident_id,
        source=source,
        entity=entity,
        metric_or_query=metric_or_query,
        value=sanitized_value,
        timestamp=fetched_at,
        source_reference=result.source_reference,
        freshness_seconds=max(0.0, freshness_seconds),
        trust_level=TrustLevel.UNTRUSTED_DATA,
        ttl_expires_at=ttl_expires_at,
    )
