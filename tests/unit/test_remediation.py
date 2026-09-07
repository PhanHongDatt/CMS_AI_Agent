"""Gate G9: Controlled Remediation tests."""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.remediation.executor import RemediationExecutor, RemediationRequest
from schemas.action import ActionStatus
from schemas.confidence import Confidence, ConfidenceSubScores, ConfidenceWeights
from schemas.incident import Severity
from schemas.policy import PolicyDecision, PolicyDecisionEnum, PolicyInputs, Risk


def _policy(decision: PolicyDecisionEnum = PolicyDecisionEnum.ALLOW) -> PolicyDecision:
    return PolicyDecision(
        id=str(uuid.uuid4()),
        incident_id="inc-1",
        decision=decision,
        reason="test",
        inputs=PolicyInputs(
            confidence=0.85,
            severity=Severity.HIGH,
            risk=Risk.LOW,
            blast_radius="single-pod",
            rollback_tested=True,
            environment="staging",
        ),
        rule_matched="HIGH_CONFIDENCE_LOW_RISK_AUTO",
    )


def _req(
    action: str = "restart_pod",
    decision: PolicyDecisionEnum = PolicyDecisionEnum.ALLOW,
    key: str | None = None,
    params: dict | None = None,
) -> RemediationRequest:
    return RemediationRequest(
        action_name=action,
        incident_id="inc-1",
        policy_decision=_policy(decision),
        action_params=params or {"namespace": "default", "pod_name": "api-pod", "rollback_tested": True},
        idempotency_key=key or str(uuid.uuid4()),
    )


def _mock_tools() -> MagicMock:
    tools = MagicMock()
    tools.restart_pod = AsyncMock(return_value=MagicMock())
    tools.scale_deployment = AsyncMock(return_value=MagicMock())
    tools.rollback_deployment = AsyncMock(return_value=MagicMock())
    return tools


class TestRemediationExecutor:
    @pytest.mark.asyncio
    async def test_successful_restart_pod(self):
        tools = _mock_tools()
        executor = RemediationExecutor(tools)
        action = await executor.execute(_req("restart_pod"))
        assert action.status == ActionStatus.SUCCESS
        tools.restart_pod.assert_called_once()

    @pytest.mark.asyncio
    async def test_successful_scale_deployment(self):
        tools = _mock_tools()
        executor = RemediationExecutor(tools)
        action = await executor.execute(_req(
            "scale_deployment",
            params={"namespace": "default", "deployment": "api", "replicas": 3, "rollback_tested": True},
        ))
        assert action.status == ActionStatus.SUCCESS
        tools.scale_deployment.assert_called_once()

    @pytest.mark.asyncio
    async def test_forbidden_action_raises(self):
        executor = RemediationExecutor(_mock_tools())
        with pytest.raises(PermissionError, match="forbidden"):
            await executor.execute(_req("kubectl_exec"))

    @pytest.mark.asyncio
    async def test_non_whitelisted_action_raises(self):
        executor = RemediationExecutor(_mock_tools())
        with pytest.raises(PermissionError, match="not whitelisted"):
            await executor.execute(_req("delete_all_resources"))

    @pytest.mark.asyncio
    async def test_non_allow_policy_raises(self):
        executor = RemediationExecutor(_mock_tools())
        with pytest.raises(PermissionError, match="REQUIRE_APPROVAL"):
            await executor.execute(_req(decision=PolicyDecisionEnum.REQUIRE_APPROVAL))

    @pytest.mark.asyncio
    async def test_idempotency_prevents_duplicate_execution(self):
        tools = _mock_tools()
        executor = RemediationExecutor(tools)
        key = "idem-key-001"
        await executor.execute(_req(key=key))
        await executor.execute(_req(key=key))
        # Tool called only once despite two executor.execute() calls
        tools.restart_pod.assert_called_once()

    @pytest.mark.asyncio
    async def test_concurrent_same_entity_serialized(self):
        call_order = []
        async def slow_restart(ctx, ns, pod):
            call_order.append("start")
            await asyncio.sleep(0.05)
            call_order.append("end")

        tools = _mock_tools()
        tools.restart_pod = slow_restart
        executor = RemediationExecutor(tools)

        t1 = asyncio.create_task(executor.execute(_req(key="k1")))
        t2 = asyncio.create_task(executor.execute(_req(key="k2")))
        await asyncio.gather(t1, t2)
        # Due to lock, one must complete before the other starts
        assert call_order == ["start", "end", "start", "end"]

    @pytest.mark.asyncio
    async def test_action_timeout_returns_timeout_status(self):
        async def slow(*args, **kwargs):
            await asyncio.sleep(10)

        tools = _mock_tools()
        tools.restart_pod = slow
        executor = RemediationExecutor(tools)
        action = await executor.execute(_req(key="timeout-key"), )
        # Set very short timeout
        req = RemediationRequest(
            action_name="restart_pod",
            incident_id="inc-1",
            policy_decision=_policy(),
            action_params={"namespace": "default", "pod_name": "api", "rollback_tested": True},
            idempotency_key="timeout-test",
            timeout_seconds=0.01,
        )
        action2 = await executor.execute(req)
        assert action2.status == ActionStatus.TIMEOUT

    @pytest.mark.asyncio
    async def test_pre_state_snapshot_recorded(self):
        tools = _mock_tools()
        executor = RemediationExecutor(tools)
        action = await executor.execute(_req())
        assert action.pre_state_snapshot is not None
        assert "action" in action.pre_state_snapshot
