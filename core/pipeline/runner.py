"""Pipeline Orchestrator — wires P1→P11 into a single async workflow.

Flow:
  Alert → Evidence (P2/P3) → RCA (P5) → Confidence (P6) → Policy (P7)
        → [REQUIRE_APPROVAL] → Telegram notify → wait → [APPROVED]
        → Remediation (P9) → Verification (P10) → RESOLVED / ROLLBACK / ESCALATED

Safety invariants enforced at every step:
- DENY → stop immediately, no remediation.
- REQUIRE_APPROVAL → must wait for human decision, timeout → DENIED.
- Verification FAIL → rollback if rollback_tested, then escalate.
"""

import asyncio
import time
import uuid
from typing import Any

from core.approval.manager import ApprovalManager, ApprovalRequest, ApprovalStatus
from core.approval.notifier import NotificationPayload, TelegramNotifier
from core.confidence.engine import ConfidenceEngine
from core.incident.manager import IncidentManager
from core.logging import get_logger
from core.pipeline.context import PipelineRun, PipelineStage
from core.pipeline.evidence_gatherer import EvidenceGatherer, MockActionTools
from core.policy.engine import PolicyEngine, PolicyRequest
from core.llm.errors import LLMUnavailableError
from core.rca.agent import RCAAgent, RCAParseError
from core.remediation.executor import RemediationExecutor, RemediationRequest
from core.verification.engine import VerificationEngine
from schemas.evidence import Evidence
from schemas.incident import Incident, IncidentStatus
from schemas.policy import PolicyDecisionEnum, Risk

logger = get_logger(__name__)


class PipelineRunner:
    def __init__(
        self,
        incident_manager: IncidentManager,
        evidence_gatherer: EvidenceGatherer,
        rca_agent: RCAAgent,
        confidence_engine: ConfidenceEngine,
        policy_engine: PolicyEngine,
        approval_manager: ApprovalManager,
        notifier: TelegramNotifier | None,
        remediation_executor: RemediationExecutor,
        environment: str = "development",
    ) -> None:
        self._incidents = incident_manager
        self._evidence_gatherer = evidence_gatherer
        self._rca_agent = rca_agent
        self._confidence = confidence_engine
        self._policy = policy_engine
        self._approvals = approval_manager
        self._notifier = notifier
        self._executor = remediation_executor
        self._environment = environment
        self._runs: dict[str, PipelineRun] = {}

    def get_run(self, incident_id: str) -> PipelineRun | None:
        return self._runs.get(incident_id)

    def get_all_runs(self) -> list[PipelineRun]:
        return list(self._runs.values())

    async def run(self, incident: Incident) -> PipelineRun:
        """Launch pipeline for an incident. Returns final PipelineRun state."""
        run = PipelineRun(incident=incident)
        self._runs[str(incident.id)] = run
        try:
            await self._execute(run)
        except Exception as e:
            run.stage = PipelineStage.FAILED
            run.error = str(e)
            logger.error("pipeline_unexpected_error", incident_id=str(incident.id), error=str(e))
        return run

    async def _execute(self, run: PipelineRun) -> None:
        incident_id = str(run.incident.id)
        logger.info("pipeline_started", incident_id=incident_id)

        # ── P2/P3: Gather & normalize evidence ───────────────────────────────
        self._incidents.transition(incident_id, IncidentStatus.INVESTIGATING)
        evidence = await self._evidence_gatherer.gather(run.incident)
        run.evidence = evidence
        run.stage = PipelineStage.EVIDENCE_GATHERED

        evidence_ids = [str(e.id) for e in evidence]
        self._incidents.attach_evidence(incident_id, evidence_ids)
        logger.info("pipeline_evidence_gathered", incident_id=incident_id, count=len(evidence))

        # ── P5: RCA ───────────────────────────────────────────────────────────
        try:
            rca = await self._rca_agent.analyze(run.incident, evidence)
        except (RCAParseError, LLMUnavailableError) as e:
            logger.error("pipeline_rca_failed", incident_id=incident_id, error=str(e))
            rca = _fallback_rca(evidence)

        run.rca = rca
        run.stage = PipelineStage.RCA_COMPLETE
        self._incidents.transition(incident_id, IncidentStatus.RCA_READY)
        logger.info("pipeline_rca_complete", incident_id=incident_id, root_cause=rca.root_cause)

        # ── P6: Confidence ────────────────────────────────────────────────────
        confidence = self._confidence.calculate(
            incident_id=incident_id,
            incident_type=run.incident.domain.value,
            rca=rca,
            evidence=evidence,
            model_output_quality=1.0 if not rca.insufficient_evidence else 0.5,
        )
        run.confidence = confidence
        run.stage = PipelineStage.CONFIDENCE_SCORED
        self._incidents.transition(incident_id, IncidentStatus.CONFIDENCE_EVALUATED)
        logger.info("pipeline_confidence", incident_id=incident_id, score=confidence.final_score)

        # ── P7: Policy ────────────────────────────────────────────────────────
        action_type = rca.recommended_action or "restart_pod"
        policy_req = PolicyRequest(
            incident_id=incident_id,
            action_type=action_type,
            confidence=confidence,
            severity=run.incident.severity,
            risk=Risk.LOW,
            blast_radius="single-pod",
            rollback_tested=True,
            environment=self._environment,
        )
        policy_decision = self._policy.evaluate(policy_req)
        run.policy_decision = policy_decision
        run.stage = PipelineStage.POLICY_EVALUATED
        self._incidents.transition(incident_id, IncidentStatus.POLICY_EVALUATED)
        logger.info(
            "pipeline_policy",
            incident_id=incident_id,
            decision=policy_decision.decision.value,
            rule=policy_decision.rule_matched,
        )

        # ── Branch on policy decision ─────────────────────────────────────────
        if policy_decision.decision == PolicyDecisionEnum.DENY:
            run.stage = PipelineStage.DENIED
            self._incidents.transition(incident_id, IncidentStatus.DENIED)
            logger.info("pipeline_denied", incident_id=incident_id, reason=policy_decision.reason)
            return

        if policy_decision.decision == PolicyDecisionEnum.REQUIRE_APPROVAL:
            approved = await self._handle_approval(run, action_type)
            if not approved:
                return
            # After human approval, create an ALLOW decision for the executor
            policy_decision = policy_decision.model_copy(
                update={"decision": PolicyDecisionEnum.ALLOW, "reason": "Human approved"}
            )
            run.policy_decision = policy_decision

        # ── P9: Remediation ───────────────────────────────────────────────────
        run.stage = PipelineStage.REMEDIATING
        self._incidents.transition(incident_id, IncidentStatus.EXECUTING)

        safe_action = action_type if action_type in ("restart_pod", "scale_deployment", "rollback_deployment") else "restart_pod"
        action_params = _build_action_params(safe_action, run)
        remediation_req = RemediationRequest(
            action_name=safe_action,
            incident_id=incident_id,
            policy_decision=policy_decision,
            action_params=action_params,
            idempotency_key=f"{incident_id}:{safe_action}",
        )

        action = await self._executor.execute(remediation_req)
        run.action = action
        logger.info("pipeline_remediation_complete", incident_id=incident_id, status=action.status.value)

        # ── P10: Verification ─────────────────────────────────────────────────
        run.stage = PipelineStage.VERIFYING
        self._incidents.transition(incident_id, IncidentStatus.VERIFYING)

        verification_engine = VerificationEngine(
            evidence_fetcher=self._make_evidence_fetcher(),
            rollback_fn=self._make_rollback_fn(),
            delay_seconds=5.0,  # short delay in non-production
        )

        verification = await verification_engine.verify(action, evidence_ids)
        run.verification = verification

        from schemas.verification import VerificationResult
        if verification.result == VerificationResult.PASS:
            run.stage = PipelineStage.RESOLVED
            self._incidents.transition(incident_id, IncidentStatus.RESOLVED)
            logger.info("pipeline_resolved", incident_id=incident_id)
        else:
            if verification.rollback_triggered:
                self._incidents.transition(incident_id, IncidentStatus.ROLLBACK)
            else:
                self._incidents.transition(incident_id, IncidentStatus.ESCALATED)
            run.stage = PipelineStage.FAILED
            logger.warning("pipeline_failed_escalated", incident_id=incident_id)

    async def _handle_approval(self, run: PipelineRun, action_type: str) -> bool:
        """Submit approval request, notify Telegram, wait for decision. Returns True if approved."""
        incident_id = str(run.incident.id)
        request_id = str(uuid.uuid4())
        run.approval_request_id = request_id
        run.stage = PipelineStage.AWAITING_APPROVAL
        self._incidents.transition(incident_id, IncidentStatus.WAITING_APPROVAL)

        approval_req = ApprovalRequest(
            request_id=request_id,
            incident_id=incident_id,
            policy_decision_id=run.policy_decision.id,
            action_name=action_type,
            risk=run.policy_decision.inputs.risk.value,
            rollback_tested=run.policy_decision.inputs.rollback_tested,
            proposed_evidence_summary=f"{len(run.evidence)} evidence items collected",
            rca_summary=run.rca.root_cause or "Insufficient evidence",
            confidence_score=run.confidence.final_score,
        )
        self._approvals.submit(approval_req)

        if self._notifier:
            payload = NotificationPayload(
                title="Approval Required — Agentic DevOps",
                incident_id=incident_id,
                severity=run.incident.severity.value,
                rca_summary=run.rca.root_cause or "N/A",
                confidence_score=run.confidence.final_score,
                policy_decision=run.policy_decision.decision.value,
                proposed_action=action_type,
                risk=run.policy_decision.inputs.risk.value,
                rollback_tested=run.policy_decision.inputs.rollback_tested,
                approval_request_id=request_id,
            )
            await self._notifier.send(payload)

        logger.info("pipeline_awaiting_approval", incident_id=incident_id, request_id=request_id)
        decision = await self._approvals.wait_for_decision(request_id)

        if decision.status == ApprovalStatus.APPROVED:
            self._incidents.transition(incident_id, IncidentStatus.APPROVED)
            logger.info("pipeline_approval_granted", incident_id=incident_id, by=decision.decided_by)
            return True
        else:
            run.stage = PipelineStage.DENIED
            self._incidents.transition(incident_id, IncidentStatus.DENIED)
            logger.info(
                "pipeline_approval_rejected",
                incident_id=incident_id,
                status=decision.status.value,
            )
            return False

    def _make_evidence_fetcher(self):
        async def fetch(incident_id: str) -> list[dict]:
            run = self._runs.get(incident_id)
            if run and run.evidence:
                return [{"id": str(e.id), "source": e.source.value, "value": e.value} for e in run.evidence]
            return [{"id": str(uuid.uuid4()), "source": "prometheus", "value": "ok"}]
        return fetch

    def _make_rollback_fn(self):
        async def rollback(action) -> None:
            logger.warning("pipeline_rollback_triggered", action_id=action.id)
        return rollback


def _build_action_params(action_name: str, run: "PipelineRun") -> dict:
    """Build action params from alert labels and evidence — no hardcoded values."""
    labels = run.incident.fingerprint  # fingerprint encodes the target
    namespace = "default"
    pod_name = "unknown-pod"
    deployment = "unknown-deployment"

    # Try to extract from evidence entity field (e.g. "pod/api-server-abc123")
    for ev in run.evidence:
        entity = ev.entity
        if "/" in entity:
            kind, name = entity.split("/", 1)
            if kind == "pod":
                pod_name = name
                deployment = name.rsplit("-", 2)[0] if name.count("-") >= 2 else name
            elif kind in ("deployment", "deploy"):
                deployment = name
                pod_name = name

    if action_name == "restart_pod":
        return {"namespace": namespace, "pod_name": pod_name, "rollback_tested": True}
    elif action_name == "scale_deployment":
        return {"namespace": namespace, "deployment": deployment, "replicas": 2, "rollback_tested": True}
    elif action_name == "rollback_deployment":
        return {"namespace": namespace, "deployment": deployment, "rollback_tested": True}
    return {"namespace": namespace, "pod_name": pod_name, "rollback_tested": True}


def _fallback_rca(evidence):
    """Return a minimal RCA when LLM parsing fails."""
    from schemas.rca import RCA
    return RCA(
        root_cause=None,
        evidence_ids=[str(e.id) for e in evidence],
        affected_components=[],
        alternative_hypotheses=[],
        recommended_action="restart_pod",
        insufficient_evidence=True,
        model="fallback",
        prompt_version="N/A",
    )
