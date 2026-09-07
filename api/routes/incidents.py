"""GET /incidents — list and inspect incidents."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import get_incident_manager
from core.incident.manager import IncidentManager

router = APIRouter(prefix="/incidents", tags=["incidents"])


class IncidentOut(BaseModel):
    id: str
    source: str
    fingerprint: str
    domain: str
    severity: str
    status: str
    evidence_ids: list[str]
    trace_id: str
    created_at: str
    updated_at: str


def _serialize(incident) -> IncidentOut:
    return IncidentOut(
        id=str(incident.id),
        source=incident.source,
        fingerprint=incident.fingerprint,
        domain=incident.domain.value,
        severity=incident.severity.value,
        status=incident.status.value,
        evidence_ids=incident.evidence_ids,
        trace_id=incident.trace_id,
        created_at=incident.created_at.isoformat(),
        updated_at=incident.updated_at.isoformat(),
    )


@router.get("", response_model=list[IncidentOut])
async def list_incidents(
    mgr: IncidentManager = Depends(get_incident_manager),
) -> list[IncidentOut]:
    return [_serialize(i) for i in mgr.get_active()]


@router.get("/{incident_id}", response_model=IncidentOut)
async def get_incident(
    incident_id: str,
    mgr: IncidentManager = Depends(get_incident_manager),
) -> IncidentOut:
    incident = mgr.get(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return _serialize(incident)
