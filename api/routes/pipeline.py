"""GET /pipeline — view pipeline run status."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import get_pipeline_runner
from core.pipeline.runner import PipelineRunner

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


class PipelineRunOut(BaseModel):
    incident_id: str
    stage: str
    has_rca: bool
    has_confidence: bool
    confidence_score: float | None
    policy_decision: str | None
    approval_request_id: str | None
    action_status: str | None
    verification_result: str | None
    error: str | None


def _serialize(run) -> PipelineRunOut:
    return PipelineRunOut(
        incident_id=str(run.incident.id),
        stage=run.stage.value,
        has_rca=run.rca is not None,
        has_confidence=run.confidence is not None,
        confidence_score=run.confidence.final_score if run.confidence else None,
        policy_decision=run.policy_decision.decision.value if run.policy_decision else None,
        approval_request_id=run.approval_request_id,
        action_status=run.action.status.value if run.action else None,
        verification_result=run.verification.result.value if run.verification else None,
        error=run.error,
    )


@router.get("", response_model=list[PipelineRunOut])
async def list_runs(
    pipeline: PipelineRunner = Depends(get_pipeline_runner),
) -> list[PipelineRunOut]:
    return [_serialize(r) for r in pipeline.get_all_runs()]


@router.get("/{incident_id}", response_model=PipelineRunOut)
async def get_run(
    incident_id: str,
    pipeline: PipelineRunner = Depends(get_pipeline_runner),
) -> PipelineRunOut:
    run = pipeline.get_run(incident_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Pipeline run not found")
    return _serialize(run)
