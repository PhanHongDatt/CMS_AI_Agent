from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Severity(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Domain(str, Enum):
    INFRASTRUCTURE = "infrastructure"
    BUSINESS = "business"


class IncidentStatus(str, Enum):
    RECEIVED = "RECEIVED"
    CORRELATED = "CORRELATED"
    INVESTIGATING = "INVESTIGATING"
    RCA_READY = "RCA_READY"
    CONFIDENCE_EVALUATED = "CONFIDENCE_EVALUATED"
    POLICY_EVALUATED = "POLICY_EVALUATED"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    RESOLVED = "RESOLVED"
    ROLLBACK = "ROLLBACK"
    ESCALATED = "ESCALATED"


class Incident(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    source: str
    fingerprint: str
    domain: Domain
    severity: Severity
    status: IncidentStatus = IncidentStatus.RECEIVED
    evidence_ids: list[str] = Field(default_factory=list)
    rca_id: str | None = None
    confidence_id: str | None = None
    policy_decision_id: str | None = None
    action_ids: list[str] = Field(default_factory=list)
    trace_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"frozen": True}
