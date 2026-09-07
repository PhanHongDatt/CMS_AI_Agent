"""Pipeline run state — tracks progress through P1→P11."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from schemas.action import Action
from schemas.confidence import Confidence
from schemas.evidence import Evidence
from schemas.incident import Incident
from schemas.policy import PolicyDecision
from schemas.rca import RCA
from schemas.verification import Verification


class PipelineStage(str, Enum):
    STARTED = "STARTED"
    EVIDENCE_GATHERED = "EVIDENCE_GATHERED"
    RCA_COMPLETE = "RCA_COMPLETE"
    CONFIDENCE_SCORED = "CONFIDENCE_SCORED"
    POLICY_EVALUATED = "POLICY_EVALUATED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    REMEDIATING = "REMEDIATING"
    VERIFYING = "VERIFYING"
    RESOLVED = "RESOLVED"
    DENIED = "DENIED"
    FAILED = "FAILED"


@dataclass
class PipelineRun:
    incident: Incident
    stage: PipelineStage = PipelineStage.STARTED
    evidence: list[Evidence] = field(default_factory=list)
    rca: RCA | None = None
    confidence: Confidence | None = None
    policy_decision: PolicyDecision | None = None
    action: Action | None = None
    verification: Verification | None = None
    error: str | None = None
    approval_request_id: str | None = None
