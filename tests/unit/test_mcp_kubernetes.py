"""Gate G2: Kubernetes MCP read-only contract tests."""

from unittest.mock import MagicMock, AsyncMock
import pytest

from mcp.base import ActionContext, MCPAuthorizationError, ToolKind
from mcp.kubernetes.readonly.tools import KubernetesReadonlyTools
from mcp.kubernetes.action.tools import KubernetesActionTools


def _mock_node(name: str, ready: bool = True) -> MagicMock:
    node = MagicMock()
    node.metadata.name = name
    cond = MagicMock()
    cond.type = "Ready"
    cond.status = "True" if ready else "False"
    node.status.conditions = [cond]
    return node


def _mock_core(nodes=None, logs="log output", events=None, pod=None, pvcs=None):
    core = MagicMock()
    node_list = MagicMock()
    node_list.items = nodes or [_mock_node("node-1")]
    core.list_node.return_value = node_list
    core.read_namespaced_pod_log.return_value = logs

    event_list = MagicMock()
    ev = MagicMock()
    ev.reason = "BackOff"
    ev.message = "Back-off restarting failed container"
    ev.type = "Warning"
    ev.count = 5
    ev.last_timestamp = "2026-08-28T10:00:00Z"
    ev.involved_object.name = "api-pod"
    event_list.items = events or [ev]
    core.list_namespaced_event.return_value = event_list

    pod_obj = MagicMock()
    pod_obj.to_dict.return_value = {"metadata": {"name": "api-pod"}}
    core.read_namespaced_pod.return_value = pod if pod else pod_obj

    pvc_list = MagicMock()
    pvc = MagicMock()
    pvc.metadata.name = "data-pvc"
    pvc.status.phase = "Bound"
    pvc_list.items = pvcs or [pvc]
    core.list_namespaced_persistent_volume_claim.return_value = pvc_list
    return core


def _mock_apps(deployment=None):
    apps = MagicMock()
    dep = MagicMock()
    dep.to_dict.return_value = {"metadata": {"name": "api"}}
    apps.read_namespaced_deployment.return_value = deployment or dep
    return apps


class TestKubernetesReadonly:
    @pytest.mark.asyncio
    async def test_get_cluster_health_returns_nodes(self):
        tools = KubernetesReadonlyTools(_mock_core(), _mock_apps())
        result = await tools.k8s_get_cluster_health()
        assert result.kind == ToolKind.READ
        assert "nodes" in result.data
        assert result.data["node_count"] == 1

    @pytest.mark.asyncio
    async def test_get_pod_logs_returns_logs(self):
        tools = KubernetesReadonlyTools(_mock_core(logs="error: OOM"), _mock_apps())
        result = await tools.k8s_get_pod_logs("default", "api-pod-xyz")
        assert result.kind == ToolKind.READ
        assert "OOM" in result.data["logs"]

    @pytest.mark.asyncio
    async def test_get_events_returns_events(self):
        tools = KubernetesReadonlyTools(_mock_core(), _mock_apps())
        result = await tools.k8s_get_events("default")
        assert result.kind == ToolKind.READ
        assert len(result.data["events"]) >= 1
        assert result.data["events"][0]["reason"] == "BackOff"

    @pytest.mark.asyncio
    async def test_describe_pod(self):
        tools = KubernetesReadonlyTools(_mock_core(), _mock_apps())
        result = await tools.k8s_describe_resource("default", "pod", "api-pod")
        assert result.kind == ToolKind.READ
        assert result.data["kind"] == "pod"

    @pytest.mark.asyncio
    async def test_describe_deployment(self):
        tools = KubernetesReadonlyTools(_mock_core(), _mock_apps())
        result = await tools.k8s_describe_resource("default", "deployment", "api")
        assert result.data["kind"] == "deployment"

    @pytest.mark.asyncio
    async def test_describe_unsupported_kind_raises(self):
        tools = KubernetesReadonlyTools(_mock_core(), _mock_apps())
        with pytest.raises(ValueError, match="Unsupported"):
            await tools.k8s_describe_resource("default", "cronjob", "my-job")

    @pytest.mark.asyncio
    async def test_get_storage_health(self):
        tools = KubernetesReadonlyTools(_mock_core(), _mock_apps())
        result = await tools.k8s_get_storage_health("default")
        assert result.kind == ToolKind.READ
        assert result.data["pvcs"][0]["phase"] == "Bound"

    @pytest.mark.asyncio
    async def test_result_has_source_reference_and_timestamp(self):
        tools = KubernetesReadonlyTools(_mock_core(), _mock_apps())
        result = await tools.k8s_get_cluster_health()
        assert result.source_reference.startswith("kubernetes://")
        assert result.fetched_at  # ISO8601 string


class TestKubernetesAction:
    def _valid_ctx(self) -> ActionContext:
        return ActionContext(
            policy_decision_id="pd-001",
            incident_id="inc-001",
            trace_id="tr-001",
        )

    @pytest.mark.asyncio
    async def test_restart_pod_requires_policy_id(self):
        tools = KubernetesActionTools(_mock_core(), _mock_apps())
        ctx = ActionContext(policy_decision_id="", incident_id="inc-1", trace_id="tr-1")
        with pytest.raises(MCPAuthorizationError, match="policy_decision_id"):
            await tools.restart_pod(ctx, "default", "api-pod")

    @pytest.mark.asyncio
    async def test_restart_pod_with_valid_ctx(self):
        tools = KubernetesActionTools(_mock_core(), _mock_apps())
        result = await tools.restart_pod(self._valid_ctx(), "default", "api-pod")
        assert result.kind == ToolKind.ACTION
        assert result.data["action"] == "deleted_for_restart"

    @pytest.mark.asyncio
    async def test_scale_deployment_with_valid_ctx(self):
        tools = KubernetesActionTools(_mock_core(), _mock_apps())
        result = await tools.scale_deployment(self._valid_ctx(), "default", "api", 3)
        assert result.data["replicas"] == 3

    @pytest.mark.asyncio
    async def test_scale_deployment_negative_replicas_raises(self):
        tools = KubernetesActionTools(_mock_core(), _mock_apps())
        with pytest.raises(ValueError):
            await tools.scale_deployment(self._valid_ctx(), "default", "api", -1)

    @pytest.mark.asyncio
    async def test_non_whitelisted_action_rejected(self):
        """MCP must reject any action not in whitelist."""
        tools = KubernetesActionTools(_mock_core(), _mock_apps())
        ctx = self._valid_ctx()
        # Simulate calling a non-whitelisted action via _validate directly
        from mcp.kubernetes.action.tools import _validate
        with pytest.raises(MCPAuthorizationError, match="not whitelisted"):
            _validate(ctx, "kubectl_exec")
