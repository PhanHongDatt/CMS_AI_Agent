"""GET /approvals/pending, POST /approvals/{id}/decide."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import get_approval_manager
from core.approval.manager import ApprovalManager

router = APIRouter(prefix="/approvals", tags=["approvals"])


class ApprovalRequestOut(BaseModel):
    request_id: str
    incident_id: str
    policy_decision_id: str
    action_name: str
    risk: str
    rollback_tested: bool
    rca_summary: str
    confidence_score: float
    created_at: float


class DecideRequest(BaseModel):
    approved: bool
    decided_by: str
    reason: str | None = None


class DecisionOut(BaseModel):
    request_id: str
    incident_id: str
    status: str
    decided_by: str | None
    decided_at: float
    reason: str | None


@router.get("/pending", response_model=list[ApprovalRequestOut])
async def list_pending(
    mgr: ApprovalManager = Depends(get_approval_manager),
) -> list[ApprovalRequestOut]:
    return [
        ApprovalRequestOut(
            request_id=r.request_id,
            incident_id=r.incident_id,
            policy_decision_id=r.policy_decision_id,
            action_name=r.action_name,
            risk=r.risk,
            rollback_tested=r.rollback_tested,
            rca_summary=r.rca_summary,
            confidence_score=r.confidence_score,
            created_at=r.created_at,
        )
        for r in mgr.get_pending()
    ]


@router.post("/{request_id}/decide", response_model=DecisionOut)
async def decide(
    request_id: str,
    body: DecideRequest,
    mgr: ApprovalManager = Depends(get_approval_manager),
) -> DecisionOut:
    decision = mgr.decide(
        request_id=request_id,
        approved=body.approved,
        decided_by=body.decided_by,
        reason=body.reason,
    )
    return DecisionOut(
        request_id=decision.request_id,
        incident_id=decision.incident_id,
        status=decision.status.value,
        decided_by=decision.decided_by,
        decided_at=decision.decided_at,
        reason=decision.reason,
    )


@router.get("/{request_id}", response_model=DecisionOut | None)
async def get_decision(
    request_id: str,
    mgr: ApprovalManager = Depends(get_approval_manager),
) -> DecisionOut | None:
    d = mgr.get_decision(request_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    return DecisionOut(
        request_id=d.request_id,
        incident_id=d.incident_id,
        status=d.status.value,
        decided_by=d.decided_by,
        decided_at=d.decided_at,
        reason=d.reason,
    )
