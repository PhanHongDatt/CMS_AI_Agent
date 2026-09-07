"""Human approval manager.

Autonomy default: L1 Recommend (REQUIRE_APPROVAL for everything non-trivially risky).

States: PENDING → APPROVED / REJECTED / TIMEOUT
Invariants:
- Each approval request has exactly one outcome.
- Duplicate approval protection: second call on same request_id is idempotent.
- Timeout → escalate.
- Audit event generated for every decision.
"""

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.logging import get_logger

logger = get_logger(__name__)


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    TIMEOUT = "TIMEOUT"


@dataclass
class ApprovalRequest:
    request_id: str
    incident_id: str
    policy_decision_id: str
    action_name: str
    risk: str
    rollback_tested: bool
    proposed_evidence_summary: str
    rca_summary: str
    confidence_score: float
    created_at: float = field(default_factory=time.time)


@dataclass
class ApprovalDecision:
    request_id: str
    incident_id: str
    status: ApprovalStatus
    decided_by: str | None
    decided_at: float
    reason: str | None = None


class ApprovalManager:
    def __init__(self, timeout_seconds: float = 300.0) -> None:
        self._timeout = timeout_seconds
        self._pending: dict[str, ApprovalRequest] = {}
        self._decisions: dict[str, ApprovalDecision] = {}
        # Futures awaited by wait_for_decision()
        self._futures: dict[str, asyncio.Future[ApprovalDecision]] = {}

    def submit(self, request: ApprovalRequest) -> None:
        """Register a new approval request. Idempotent on duplicate request_id."""
        if request.request_id in self._decisions:
            logger.info("approval_already_decided", request_id=request.request_id)
            return
        if request.request_id in self._pending:
            logger.info("approval_already_pending", request_id=request.request_id)
            return
        self._pending[request.request_id] = request
        logger.info(
            "approval_submitted",
            request_id=request.request_id,
            incident_id=request.incident_id,
            action=request.action_name,
            risk=request.risk,
        )

    def decide(self, request_id: str, approved: bool, decided_by: str, reason: str | None = None) -> ApprovalDecision:
        """Record a human decision. Idempotent — duplicate calls return existing decision."""
        if request_id in self._decisions:
            logger.info("approval_duplicate_ignored", request_id=request_id)
            return self._decisions[request_id]

        status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
        decision = ApprovalDecision(
            request_id=request_id,
            incident_id=self._pending.get(request_id, ApprovalRequest(
                request_id=request_id, incident_id="unknown",
                policy_decision_id="", action_name="", risk="",
                rollback_tested=False, proposed_evidence_summary="",
                rca_summary="", confidence_score=0.0
            )).incident_id,
            status=status,
            decided_by=decided_by,
            decided_at=time.time(),
            reason=reason,
        )
        self._decisions[request_id] = decision
        self._pending.pop(request_id, None)

        logger.info(
            "approval_decided",
            request_id=request_id,
            status=status.value,
            decided_by=decided_by,
        )

        # Resolve any waiting future
        future = self._futures.pop(request_id, None)
        if future and not future.done():
            future.set_result(decision)

        return decision

    async def wait_for_decision(self, request_id: str) -> ApprovalDecision:
        """Wait for a decision or timeout."""
        if request_id in self._decisions:
            return self._decisions[request_id]

        loop = asyncio.get_running_loop()
        future: asyncio.Future[ApprovalDecision] = loop.create_future()
        self._futures[request_id] = future

        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout=self._timeout)
        except asyncio.TimeoutError:
            self._futures.pop(request_id, None)
            if not future.done():
                future.cancel()
            pending = self._pending.pop(request_id, None)
            decision = ApprovalDecision(
                request_id=request_id,
                incident_id=pending.incident_id if pending else "unknown",
                status=ApprovalStatus.TIMEOUT,
                decided_by=None,
                decided_at=time.time(),
                reason=f"Timed out after {self._timeout}s — escalating",
            )
            self._decisions[request_id] = decision
            logger.warning(
                "approval_timeout",
                request_id=request_id,
                timeout_seconds=self._timeout,
            )
            return decision

    def get_pending(self) -> list[ApprovalRequest]:
        return list(self._pending.values())

    def get_decision(self, request_id: str) -> ApprovalDecision | None:
        return self._decisions.get(request_id)
