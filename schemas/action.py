from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel

from schemas.policy import Risk


class ActionStatus(str, Enum):
    PENDING = "PENDING"
    EXECUTING = "EXECUTING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"


class Action(BaseModel):
    id: str
    incident_id: str
    policy_decision_id: str
    name: str
    risk: Risk
    rollback_supported: bool
    rollback_tested: bool
    pre_state_snapshot: dict[str, Any]
    status: ActionStatus = ActionStatus.PENDING
    executed_at: datetime | None = None

    model_config = {"frozen": True}
