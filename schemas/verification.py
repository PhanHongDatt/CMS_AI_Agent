from enum import Enum
from typing import Any

from pydantic import BaseModel


class VerificationResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class Verification(BaseModel):
    action_id: str
    evidence_before_ids: list[str]
    evidence_after_ids: list[str]
    comparison: dict[str, Any]
    result: VerificationResult
    rollback_triggered: bool

    model_config = {"frozen": True}
