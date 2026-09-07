"""POST /webhook/alertmanager — receive alerts from Prometheus Alertmanager."""

import hashlib
import hmac
import os

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from api.deps import get_incident_manager, get_pipeline_runner
from core.incident.correlator import AlertInput
from core.incident.manager import IncidentManager
from core.logging import get_logger
from core.pipeline.runner import PipelineRunner

router = APIRouter(prefix="/webhook", tags=["webhook"])
logger = get_logger(__name__)


class AlertmanagerAlert(BaseModel):
    status: str = "firing"
    labels: dict = {}
    annotations: dict = {}
    generatorURL: str = ""
    fingerprint: str = ""


class AlertmanagerPayload(BaseModel):
    version: str = "4"
    groupKey: str = ""
    status: str = "firing"
    receiver: str = ""
    groupLabels: dict = {}
    commonLabels: dict = {}
    commonAnnotations: dict = {}
    alerts: list[AlertmanagerAlert] = []


def _verify_signature(body: bytes, signature: str | None) -> bool:
    """Verify HMAC-SHA256 signature if WEBHOOK_SECRET is configured."""
    secret = os.getenv("WEBHOOK_SECRET", "")
    if not secret:
        return True
    if not signature:
        return False
    mac = hmac.new(secret.encode(), body, hashlib.sha256)
    expected = "sha256=" + mac.hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/alertmanager")
async def alertmanager_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    mgr: IncidentManager = Depends(get_incident_manager),
    pipeline: PipelineRunner = Depends(get_pipeline_runner),
    x_webhook_signature: str | None = Header(default=None),
) -> dict:
    body = await request.body()
    if not _verify_signature(body, x_webhook_signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload = AlertmanagerPayload.model_validate_json(body)

    created = []
    for alert in payload.alerts:
        if alert.status != "firing":
            continue

        fingerprint = alert.fingerprint or _derive_fingerprint(alert.labels)
        severity = alert.labels.get("severity", "medium")
        source = alert.labels.get("job", "alertmanager")
        domain = "infrastructure"

        alert_input = AlertInput(
            source=source,
            fingerprint=fingerprint,
            severity=severity,
            domain=domain,
            labels=alert.labels,
            annotations=alert.annotations,
        )
        incident, is_dup = mgr.receive_alert(alert_input)

        if not is_dup:
            background_tasks.add_task(pipeline.run, incident)
            created.append(str(incident.id))
            logger.info(
                "alertmanager_alert_received",
                fingerprint=fingerprint,
                severity=severity,
                incident_id=str(incident.id),
            )

    return {"received": len(payload.alerts), "incidents_created": len(created), "ids": created}


def _derive_fingerprint(labels: dict) -> str:
    key = "|".join(f"{k}={v}" for k, v in sorted(labels.items()))
    return hashlib.md5(key.encode()).hexdigest()
