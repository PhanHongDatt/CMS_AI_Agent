"""POST /alerts — submit alert and trigger pipeline as background task."""

import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel

from api.deps import get_incident_manager, get_pipeline_runner
from core.incident.correlator import AlertInput
from core.incident.manager import IncidentManager
from core.pipeline.runner import PipelineRunner

router = APIRouter(prefix="/alerts", tags=["alerts"])


class AlertRequest(BaseModel):
    source: str
    fingerprint: str
    severity: str
    domain: str = "infrastructure"
    labels: dict = {}
    annotations: dict = {}


class AlertResponse(BaseModel):
    incident_id: str
    is_duplicate: bool
    status: str
    severity: str
    pipeline_triggered: bool


@router.post("", response_model=AlertResponse, status_code=201)
async def submit_alert(
    body: AlertRequest,
    background_tasks: BackgroundTasks,
    mgr: IncidentManager = Depends(get_incident_manager),
    pipeline: PipelineRunner = Depends(get_pipeline_runner),
) -> AlertResponse:
    alert = AlertInput(
        source=body.source,
        fingerprint=body.fingerprint,
        severity=body.severity,
        domain=body.domain,
        labels=body.labels,
        annotations=body.annotations,
    )
    incident, is_dup = mgr.receive_alert(alert)

    pipeline_triggered = False
    if not is_dup:
        background_tasks.add_task(pipeline.run, incident)
        pipeline_triggered = True

    return AlertResponse(
        incident_id=str(incident.id),
        is_duplicate=is_dup,
        status=incident.status.value,
        severity=incident.severity.value,
        pipeline_triggered=pipeline_triggered,
    )
