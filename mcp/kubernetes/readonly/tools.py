"""Kubernetes read-only MCP tools.

These tools NEVER modify cluster state. All calls go through the Kubernetes
API with a least-privilege read-only service account.
"""

import asyncio
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

    IMPORTANT: kubernetes-python's client is SYNCHRONOUS (blocking urllib3
    calls). Every call is dispatched via asyncio.to_thread so it never blocks
    the FastAPI/uvicorn event loop (a blocked loop makes /health unresponsive
    → kubelet kills the pod on liveness-probe failure). `_request_timeout` is
    also passed to bound the underlying socket call — without it, a silently
    dropped connection (e.g. NetworkPolicy DROP, not REJECT) hangs forever
    instead of failing fast.
    """

    def __init__(self, core_v1: Any, apps_v1: Any, timeout_seconds: float = 10.0) -> None:
        self._core = core_v1
        self._apps = apps_v1
        self._timeout = timeout_seconds

    async def _call(self, fn, /, *args, **kwargs):
        kwargs.setdefault("_request_timeout", self._timeout)
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(fn, *args, **kwargs), timeout=self._timeout + 2
            )
        except TimeoutError as e:
            raise MCPTimeoutError(f"{fn.__name__} timed out after {self._timeout}s") from e

    async def k8s_get_cluster_health(self) -> ToolResult:
        """Return node status summary and component statuses."""
        try:
            nodes = await self._call(self._core.list_node)
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
        except MCPTimeoutError:
            raise
        except Exception as e:
            raise MCPConnectionError(f"k8s_get_cluster_health failed: {e}") from e

    async def k8s_list_pods(self, namespace: str) -> ToolResult:
        """List pods in a namespace with status/restart summary."""
        try:
            pods = await self._call(self._core.list_namespaced_pod, namespace=namespace)
            pod_summary = [
                {
                    "name": p.metadata.name,
                    "phase": p.status.phase,
                    "ready": sum(1 for c in (p.status.container_statuses or []) if c.ready),
                    "containers": len(p.status.container_statuses or []),
                    "restarts": sum(c.restart_count for c in (p.status.container_statuses or [])),
                    "node": p.spec.node_name,
                }
                for p in pods.items
            ]
            return ToolResult(
                tool="k8s_list_pods",
                kind=ToolKind.READ,
                data={"pods": pod_summary, "pod_count": len(pod_summary)},
                source_reference=_ref(namespace, "pods"),
                fetched_at=_now(),
            )
        except MCPTimeoutError:
            raise
        except Exception as e:
            raise MCPConnectionError(f"k8s_list_pods failed: {e}") from e

    async def k8s_get_pod_logs(
        self, namespace: str, pod_name: str, tail_lines: int = 100
    ) -> ToolResult:
        try:
            logs = await self._call(
                self._core.read_namespaced_pod_log,
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
        except MCPTimeoutError:
            raise
        except Exception as e:
            raise MCPConnectionError(f"k8s_get_pod_logs failed: {e}") from e

    async def k8s_get_events(
        self, namespace: str, field_selector: str = ""
    ) -> ToolResult:
        try:
            kwargs: dict[str, Any] = {"namespace": namespace}
            if field_selector:
                kwargs["field_selector"] = field_selector
            events = await self._call(self._core.list_namespaced_event, **kwargs)
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
        except MCPTimeoutError:
            raise
        except Exception as e:
            raise MCPConnectionError(f"k8s_get_events failed: {e}") from e

    async def k8s_describe_resource(
        self, namespace: str, kind: str, name: str
    ) -> ToolResult:
        try:
            kind_lower = kind.lower()
            if kind_lower == "pod":
                obj = await self._call(self._core.read_namespaced_pod, name=name, namespace=namespace)
            elif kind_lower == "deployment":
                obj = await self._call(
                    self._apps.read_namespaced_deployment, name=name, namespace=namespace
                )
            elif kind_lower == "service":
                obj = await self._call(
                    self._core.read_namespaced_service, name=name, namespace=namespace
                )
            elif kind_lower == "node":
                obj = await self._call(self._core.read_node, name=name)
            else:
                raise ValueError(f"Unsupported resource kind: {kind}")

            return ToolResult(
                tool="k8s_describe_resource",
                kind=ToolKind.READ,
                data={"kind": kind, "name": name, "spec": obj.to_dict()},
                source_reference=_ref(namespace, kind_lower + "s", name),
                fetched_at=_now(),
            )
        except (ValueError, MCPTimeoutError):
            raise
        except Exception as e:
            raise MCPConnectionError(f"k8s_describe_resource failed: {e}") from e

    async def k8s_get_storage_health(self, namespace: str = "default") -> ToolResult:
        try:
            pvcs = await self._call(
                self._core.list_namespaced_persistent_volume_claim, namespace=namespace
            )
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
        except MCPTimeoutError:
            raise
        except Exception as e:
            raise MCPConnectionError(f"k8s_get_storage_health failed: {e}") from e
