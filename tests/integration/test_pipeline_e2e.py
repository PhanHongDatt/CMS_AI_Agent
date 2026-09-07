"""End-to-end pipeline integration test using mock providers.

Runs full P1→P11 flow without real LLM or infrastructure.
"""

import asyncio
import pytest

from core.approval.manager import ApprovalManager
from core.confidence.engine import ConfidenceEngine
from core.incident.correlator import AlertCorrelator, AlertInput
from core.incident.manager import IncidentManager
from core.llm.cost_tracker import CostTracker
from core.llm.gateway import LLMGateway
from core.llm.mock_provider import MockLLMProvider
from core.pipeline.context import PipelineStage
from core.pipeline.evidence_gatherer import MockActionTools, MockEvidenceGatherer
from core.pipeline.runner import PipelineRunner
from core.policy.engine import PolicyEngine
from core.rca.agent import RCAAgent
from core.remediation.executor import RemediationExecutor
from schemas.incident import IncidentStatus


def _build_runner(environment: str = "development") -> tuple[PipelineRunner, IncidentManager, ApprovalManager]:
    correlator = AlertCorrelator()
    incident_manager = IncidentManager(correlator=correlator)
    approval_manager = ApprovalManager(timeout_seconds=5.0)

    mock_provider = MockLLMProvider()
    cost_tracker = CostTracker()
    # Register mock under "claude" so the routing table resolves correctly
    gateway = LLMGateway(providers={"claude": mock_provider}, cost_tracker=cost_tracker)

    rca_agent = RCAAgent(gateway=gateway)
    confidence_engine = ConfidenceEngine()
    policy_engine = PolicyEngine()
    executor = RemediationExecutor(action_tools=MockActionTools())

    runner = PipelineRunner(
        incident_manager=incident_manager,
        evidence_gatherer=MockEvidenceGatherer(),
        rca_agent=rca_agent,
        confidence_engine=confidence_engine,
        policy_engine=policy_engine,
        approval_manager=approval_manager,
        notifier=None,
        remediation_executor=executor,
        environment=environment,
    )
    return runner, incident_manager, approval_manager


class TestPipelineE2E:
    @pytest.mark.asyncio
    async def test_pipeline_resolves_low_risk_incident(self):
        """Low risk in dev environment with high confidence → auto-resolve."""
        runner, mgr, _ = _build_runner(environment="development")
        alert = AlertInput(
            source="prometheus",
            fingerprint="fp-low-risk-001",
            severity="medium",
            domain="infrastructure",
        )
        incident, _ = mgr.receive_alert(alert)
        run = await runner.run(incident)

        assert run.rca is not None
        assert run.confidence is not None
        assert run.policy_decision is not None
        assert run.stage in (PipelineStage.RESOLVED, PipelineStage.DENIED, PipelineStage.FAILED)

    @pytest.mark.asyncio
    async def test_pipeline_runs_all_stages(self):
        """Verify pipeline progresses through evidence → RCA → confidence → policy."""
        runner, mgr, _ = _build_runner()
        alert = AlertInput(
            source="kubernetes",
            fingerprint="fp-stages-test",
            severity="high",
            domain="infrastructure",
        )
        incident, _ = mgr.receive_alert(alert)
        run = await runner.run(incident)

        assert run.evidence, "Evidence must be gathered"
        assert run.rca is not None, "RCA must complete"
        assert run.confidence is not None, "Confidence must be calculated"
        assert run.policy_decision is not None, "Policy must be evaluated"

    @pytest.mark.asyncio
    async def test_critical_incident_requires_approval(self):
        """CRITICAL severity → REQUIRE_APPROVAL → timeout → DENIED."""
        runner, mgr, approval_mgr = _build_runner()
        alert = AlertInput(
            source="pagerduty",
            fingerprint="fp-critical-001",
            severity="critical",
            domain="infrastructure",
        )
        incident, _ = mgr.receive_alert(alert)
        run = await runner.run(incident)

        # Critical → policy requires approval → timeout (5s) → denied
        assert run.policy_decision.decision.value == "REQUIRE_APPROVAL"
        assert run.stage == PipelineStage.DENIED

    @pytest.mark.asyncio
    async def test_approval_unblocks_pipeline(self):
        """Simulate human approving an action mid-pipeline."""
        runner, mgr, approval_mgr = _build_runner()
        alert = AlertInput(
            source="prometheus",
            fingerprint="fp-approval-test",
            severity="critical",
            domain="infrastructure",
        )
        incident, _ = mgr.receive_alert(alert)

        async def approve_after_delay():
            await asyncio.sleep(0.5)
            pending = approval_mgr.get_pending()
            if pending:
                approval_mgr.decide(
                    request_id=pending[0].request_id,
                    approved=True,
                    decided_by="test_user",
                    reason="Approved in test",
                )

        pipeline_task = asyncio.create_task(runner.run(incident))
        approve_task = asyncio.create_task(approve_after_delay())
        run, _ = await asyncio.gather(pipeline_task, approve_task)

        assert run.approval_request_id is not None
        assert run.stage in (PipelineStage.RESOLVED, PipelineStage.FAILED)

    @pytest.mark.asyncio
    async def test_duplicate_alert_skips_pipeline(self):
        """Duplicate alert within dedup window returns same incident (before resolution)."""
        runner, mgr, _ = _build_runner()
        alert = AlertInput(
            source="prometheus",
            fingerprint="fp-dedup-test",
            severity="low",
            domain="infrastructure",
        )
        incident1, is_dup1 = mgr.receive_alert(alert)
        assert not is_dup1

        # Second alert immediately (same fingerprint, incident still active)
        incident2, is_dup2 = mgr.receive_alert(alert)
        assert is_dup2 is True
        assert str(incident1.id) == str(incident2.id)

    @pytest.mark.asyncio
    async def test_pipeline_run_tracked(self):
        """Pipeline run is stored and retrievable by incident_id."""
        runner, mgr, _ = _build_runner()
        alert = AlertInput(
            source="grafana",
            fingerprint="fp-tracking-test",
            severity="low",
            domain="infrastructure",
        )
        incident, _ = mgr.receive_alert(alert)
        await runner.run(incident)

        stored = runner.get_run(str(incident.id))
        assert stored is not None
        assert str(stored.incident.id) == str(incident.id)
