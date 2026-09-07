"""Kubernetes read-only MCP tools.

These tools NEVER modify cluster state. All calls go through the Kubernetes
API with a least-privilege read-only service account.
"""

from datetime import datetime, timezone
from typing import Any

from mcp.base import MCPConnectionError, MCPTimeoutError, ToolKind, ToolResult

_SOURCE = "kubernetes"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ref(namespace: str, resource: str, name: str = "") -> str:
    path = f"{_SOURCE}://{namespace}/{resource}"
    return f"{path}/{name}" if name else path


class KubernetesReadonlyTools:
    """Wraps the Kubernetes Python client for read-only operations.

    Pass `client` as the kubernetes.client.CoreV1Api / AppsV1Api etc.
    For tests, inject a mock client.
    """

    def __init__(self, core_v1: Any, apps_v1: Any, timeout_seconds: float = 10.0) -> None:
        self._core = core_v1
        self._apps = apps_v1
        self._timeout = timeout_seconds

    async def k8s_get_cluster_health(self) -> ToolResult:
        """Return node status summary and component statuses."""
        try:
            nodes = self._core.list_node()
            node_summary = [
                {
                    "name": n.metadata.name,
                    "conditions": [
                        {"type": c.type, "status": c.status}
                        for c in (n.status.conditions or [])
                    ],
                }
                for n in nodes.items
            ]
            return ToolResult(
                tool="k8s_get_cluster_health",
                kind=ToolKind.READ,
                data={"nodes": node_summary, "node_count": len(node_summary)},
                source_reference=_ref("cluster", "nodes"),
                fetched_at=_now(),
            )
        except Exception as e:
            raise MCPConnectionError(f"k8s_get_cluster_health failed: {e}") from e

    async def k8s_get_pod_logs(
        self, namespace: str, pod_name: str, tail_lines: int = 100
    ) -> ToolResult:
        try:
            logs = self._core.read_namespaced_pod_log(
                name=pod_name,
                namespace=namespace,
                tail_lines=tail_lines,
            )
            return ToolResult(
                tool="k8s_get_pod_logs",
                kind=ToolKind.READ,
                data={"logs": logs, "lines": tail_lines},
                source_reference=_ref(namespace, "pods", pod_name) + "/logs",
                fetched_at=_now(),
            )
        except Exception as e:
            raise MCPConnectionError(f"k8s_get_pod_logs failed: {e}") from e

    async def k8s_get_events(
        self, namespace: str, field_selector: str = ""
    ) -> ToolResult:
        try:
            kwargs: dict[str, Any] = {"namespace": namespace}
            if field_selector:
                kwargs["field_selector"] = field_selector
            events = self._core.list_namespaced_event(**kwargs)
            items = [
                {
                    "reason": e.reason,
                    "message": e.message,
                    "type": e.type,
                    "count": e.count,
                    "last_timestamp": str(e.last_timestamp),
                    "involved_object": e.involved_object.name if e.involved_object else None,
                }
                for e in events.items
            ]
            return ToolResult(
                tool="k8s_get_events",
                kind=ToolKind.READ,
                data={"events": items},
                source_reference=_ref(namespace, "events"),
                fetched_at=_now(),
            )
        except Exception as e:
            raise MCPConnectionError(f"k8s_get_events failed: {e}") from e

    async def k8s_describe_resource(
        self, namespace: str, kind: str, name: str
    ) -> ToolResult:
        try:
            kind_lower = kind.lower()
            if kind_lower == "pod":
                obj = self._core.read_namespaced_pod(name=name, namespace=namespace)
            elif kind_lower == "deployment":
                obj = self._apps.read_namespaced_deployment(name=name, namespace=namespace)
            elif kind_lower == "service":
                obj = self._core.read_namespaced_service(name=name, namespace=namespace)
            elif kind_lower == "node":
                obj = self._core.read_node(name=name)
            else:
                raise ValueError(f"Unsupported resource kind: {kind}")

            return ToolResult(
                tool="k8s_describe_resource",
                kind=ToolKind.READ,
                data={"kind": kind, "name": name, "spec": obj.to_dict()},
                source_reference=_ref(namespace, kind_lower + "s", name),
                fetched_at=_now(),
            )
        except ValueError:
            raise
        except Exception as e:
            raise MCPConnectionError(f"k8s_describe_resource failed: {e}") from e

    async def k8s_get_storage_health(self, namespace: str = "default") -> ToolResult:
        try:
            pvcs = self._core.list_namespaced_persistent_volume_claim(namespace=namespace)
            pvc_summary = [
                {"name": pvc.metadata.name, "phase": pvc.status.phase}
                for pvc in pvcs.items
            ]
            return ToolResult(
                tool="k8s_get_storage_health",
                kind=ToolKind.READ,
                data={"pvcs": pvc_summary},
                source_reference=_ref(namespace, "persistentvolumeclaims"),
                fetched_at=_now(),
            )
        except Exception as e:
            raise MCPConnectionError(f"k8s_get_storage_health failed: {e}") from e
