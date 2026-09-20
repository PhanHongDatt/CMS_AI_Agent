"""Evidence gatherer protocol + simulation-mode mock.

Real implementation would call MCP read tools (Kubernetes, Prometheus, etc.).
Mock returns synthetic evidence so the pipeline can run without real infra.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from core.logging import get_logger
from schemas.evidence import Evidence, EvidenceSource, TrustLevel
from schemas.incident import Incident

_log = get_logger(__name__)


class EvidenceGatherer(Protocol):
    async def gather(self, incident: Incident) -> list[Evidence]: ...


class MockEvidenceGatherer:
    """Returns synthetic evidence for simulation / testing mode."""

    async def gather(self, incident: Incident) -> list[Evidence]:
        now = datetime.now(UTC)
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

    async def restart_pod(self, ctx: Any, namespace: str, pod_name: str) -> dict[str, object]:
        return {"restarted": True, "namespace": namespace, "pod": pod_name}

    async def scale_deployment(
        self, ctx: Any, namespace: str, deployment: str, replicas: int
    ) -> dict[str, object]:
        return {
            "scaled": True,
            "namespace": namespace,
            "deployment": deployment,
            "replicas": replicas,
        }

    async def rollback_deployment(
        self, ctx: Any, namespace: str, deployment: str
    ) -> dict[str, object]:
        return {"rolled_back": True, "namespace": namespace, "deployment": deployment}


class RealK8sEvidenceGatherer:
    """Thu thập evidence THẬT từ cluster qua mcp/kubernetes/readonly/tools.py.

    CHỈ ĐỌC (get/list/watch) — dùng ClusterRole "ai-agent" (RBAC read-only cho
    phần này, xem helm-charts/ai-agent/templates/rbac.yaml). KHÔNG thực thi
    remediation thật ở đây; ACTION tools vẫn cố ý dùng MockActionTools (xem
    api/deps.py) cho tới khi core/pipeline/runner.py hết hardcode
    risk=Risk.LOW/rollback_tested=True — nếu không, Policy Engine có thể tự
    ALLOW remediation (bỏ qua duyệt Telegram) khi confidence>=0.80.
    """

    def __init__(self, core_v1: Any, apps_v1: Any, namespaces: list[str]) -> None:
        from mcp.kubernetes.readonly.tools import KubernetesReadonlyTools

        self._tools = KubernetesReadonlyTools(core_v1=core_v1, apps_v1=apps_v1)
        self._namespaces = namespaces

    async def gather(self, incident: Incident) -> list[Evidence]:
        now = datetime.now(UTC)
        ttl = now + timedelta(hours=1)
        evidence: list[Evidence] = []

        try:
            health = await self._tools.k8s_get_cluster_health()
            evidence.append(
                Evidence(
                    incident_id=incident.id,
                    source=EvidenceSource.KUBERNETES,
                    entity="cluster/nodes",
                    metric_or_query="node_health",
                    value=health.data,
                    timestamp=now,
                    source_reference=health.source_reference,
                    freshness_seconds=1.0,
                    trust_level=TrustLevel.UNTRUSTED_DATA,
                    ttl_expires_at=ttl,
                )
            )
        except Exception as e:  # noqa: BLE001 — evidence gathering không được crash pipeline
            _log.warning("real_evidence_cluster_health_failed", error=str(e))

        for ns in self._namespaces:
            try:
                events = await self._tools.k8s_get_events(namespace=ns)
                evidence.append(
                    Evidence(
                        incident_id=incident.id,
                        source=EvidenceSource.KUBERNETES,
                        entity=f"namespace/{ns}",
                        metric_or_query="recent_events",
                        value=events.data,
                        timestamp=now,
                        source_reference=events.source_reference,
                        freshness_seconds=1.0,
                        trust_level=TrustLevel.UNTRUSTED_DATA,
                        ttl_expires_at=ttl,
                    )
                )
            except Exception as e:  # noqa: BLE001
                _log.warning("real_evidence_events_failed", namespace=ns, error=str(e))

        return evidence
