"""Evidence gatherer protocol + simulation-mode mock.

Real implementation would call MCP read tools (Kubernetes, Prometheus, etc.).
Mock returns synthetic evidence so the pipeline can run without real infra.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Protocol

from schemas.evidence import Evidence, EvidenceSource, TrustLevel
from schemas.incident import Incident


class EvidenceGatherer(Protocol):
    async def gather(self, incident: Incident) -> list[Evidence]: ...


class MockEvidenceGatherer:
    """Returns synthetic evidence for simulation / testing mode."""

    async def gather(self, incident: Incident) -> list[Evidence]:
        now = datetime.now(timezone.utc)
        ttl = now + timedelta(hours=1)
        return [
            Evidence(
                incident_id=incident.id,
                source=EvidenceSource.KUBERNETES,
                entity="pod/api-server-abc123",
                metric_or_query="pod_status",
                value={"status": "CrashLoopBackOff", "restart_count": 12},
                timestamp=now,
                source_reference="k8s://default/pod/api-server-abc123",
                freshness_seconds=30.0,
                trust_level=TrustLevel.UNTRUSTED_DATA,
                ttl_expires_at=ttl,
            ),
            Evidence(
                incident_id=incident.id,
                source=EvidenceSource.PROMETHEUS,
                entity="pod/api-server-abc123",
                metric_or_query='container_memory_usage_bytes{pod="api-server-abc123"}',
                value=524288000,
                timestamp=now,
                source_reference="prometheus://localhost:9090",
                freshness_seconds=15.0,
                trust_level=TrustLevel.UNTRUSTED_DATA,
                ttl_expires_at=ttl,
            ),
        ]


class MockActionTools:
    """Simulates MCP action tools without touching real infrastructure."""

    async def restart_pod(self, ctx, namespace: str, pod_name: str) -> dict:
        return {"restarted": True, "namespace": namespace, "pod": pod_name}

    async def scale_deployment(self, ctx, namespace: str, deployment: str, replicas: int) -> dict:
        return {"scaled": True, "namespace": namespace, "deployment": deployment, "replicas": replicas}

    async def rollback_deployment(self, ctx, namespace: str, deployment: str) -> dict:
        return {"rolled_back": True, "namespace": namespace, "deployment": deployment}
