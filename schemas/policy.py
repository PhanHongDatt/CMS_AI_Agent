from enum import Enum

from pydantic import BaseModel, Field

from schemas.incident import Severity


class Risk(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class PolicyDecisionEnum(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


class PolicyInputs(BaseModel):
    confidence: float = Field(ge=0.0, le=1.0)
    severity: Severity
    risk: Risk
    blast_radius: str
    rollback_tested: bool
    environment: str

    model_config = {"frozen": True}


class PolicyDecision(BaseModel):
    id: str
    incident_id: str
    decision: PolicyDecisionEnum
    reason: str
    inputs: PolicyInputs
    rule_matched: str

    model_config = {"frozen": True}
