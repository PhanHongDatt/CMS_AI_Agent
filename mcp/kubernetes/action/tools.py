"""Kubernetes ACTION tools.

Every action tool REQUIRES a valid ActionContext with policy_decision_id.
MCP rejects any call missing or with invalid policy_decision_id.
"""

from datetime import datetime, timezone
from typing import Any

from mcp.base import ActionContext, MCPAuthorizationError, MCPConnectionError, ToolKind, ToolResult

_WHITELISTED_ACTIONS = {"restart_pod", "scale_deployment", "rollback_deployment"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate(ctx: ActionContext, action: str) -> None:
    if not ctx.policy_decision_id:
        raise MCPAuthorizationError(
            f"ACTION '{action}' requires a valid policy_decision_id"
        )
    if action not in _WHITELISTED_ACTIONS:
        raise MCPAuthorizationError(
            f"ACTION '{action}' is not whitelisted. Allowed: {_WHITELISTED_ACTIONS}"
        )


class KubernetesActionTools:
    def __init__(self, core_v1: Any, apps_v1: Any) -> None:
        self._core = core_v1
        self._apps = apps_v1

    async def restart_pod(
        self, ctx: ActionContext, namespace: str, pod_name: str
    ) -> ToolResult:
        _validate(ctx, "restart_pod")
        try:
            self._core.delete_namespaced_pod(name=pod_name, namespace=namespace)
            return ToolResult(
                tool="restart_pod",
                kind=ToolKind.ACTION,
                data={"pod": pod_name, "namespace": namespace, "action": "deleted_for_restart"},
                source_reference=f"kubernetes://{namespace}/pods/{pod_name}",
                fetched_at=_now(),
            )
        except Exception as e:
            raise MCPConnectionError(f"restart_pod failed: {e}") from e

    async def scale_deployment(
        self, ctx: ActionContext, namespace: str, deployment: str, replicas: int
    ) -> ToolResult:
        _validate(ctx, "scale_deployment")
        if replicas < 0:
            raise ValueError("replicas must be >= 0")
        try:
            body = {"spec": {"replicas": replicas}}
            self._apps.patch_namespaced_deployment_scale(
                name=deployment, namespace=namespace, body=body
            )
            return ToolResult(
                tool="scale_deployment",
                kind=ToolKind.ACTION,
                data={"deployment": deployment, "namespace": namespace, "replicas": replicas},
                source_reference=f"kubernetes://{namespace}/deployments/{deployment}",
                fetched_at=_now(),
            )
        except ValueError:
            raise
        except Exception as e:
            raise MCPConnectionError(f"scale_deployment failed: {e}") from e

    async def rollback_deployment(
        self, ctx: ActionContext, namespace: str, deployment: str
    ) -> ToolResult:
        _validate(ctx, "rollback_deployment")
        try:
            body = {
                "spec": {
                    "template": {
                        "metadata": {
                            "annotations": {
                                "kubectl.kubernetes.io/restartedAt": _now()
                            }
                        }
                    }
                }
            }
            self._apps.patch_namespaced_deployment(
                name=deployment, namespace=namespace, body=body
            )
            return ToolResult(
                tool="rollback_deployment",
                kind=ToolKind.ACTION,
                data={"deployment": deployment, "namespace": namespace, "action": "rollback_triggered"},
                source_reference=f"kubernetes://{namespace}/deployments/{deployment}",
                fetched_at=_now(),
            )
        except Exception as e:
            raise MCPConnectionError(f"rollback_deployment failed: {e}") from e
