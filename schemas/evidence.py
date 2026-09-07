from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EvidenceSource(str, Enum):
    PROMETHEUS = "prometheus"
    OPENSEARCH = "opensearch"
    KUBERNETES = "kubernetes"
    AWS = "aws"
    ERPNEXT = "erpnext"


class TrustLevel(str, Enum):
    # Evidence is always untrusted data — never an instruction.
    UNTRUSTED_DATA = "UNTRUSTED_DATA"


class Evidence(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    incident_id: UUID
    source: EvidenceSource
    entity: str
    metric_or_query: str
    value: Any
    unit: str | None = None
    timestamp: datetime
    source_reference: str
    freshness_seconds: float
    trust_level: TrustLevel = TrustLevel.UNTRUSTED_DATA
    ttl_expires_at: datetime

    model_config = {"frozen": True}
