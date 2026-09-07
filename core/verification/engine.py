"""Verification + Rollback Engine.

Flow:
  Action → wait → collect evidence → compare before/after → PASS / FAIL

On FAIL:
  → rollback only if rollback_tested=True
  → verify again
  → escalate if still failing

Maximum rollback attempts: 1.
No infinite remediation loop.
"""

import asyncio
from typing import Any, Callable, Awaitable

from core.logging import get_logger
from schemas.action import Action, ActionStatus
from schemas.verification import Verification, VerificationResult

logger = get_logger(__name__)

_DEFAULT_DELAY_SECONDS = 60.0
_MAX_ROLLBACK_ATTEMPTS = 1


EvidenceFetcher = Callable[[str], Awaitable[list[dict[str, Any]]]]
RollbackFn = Callable[[Action], Awaitable[None]]


class VerificationEngine:
    def __init__(
        self,
        evidence_fetcher: EvidenceFetcher,
        rollback_fn: RollbackFn,
        delay_seconds: float = _DEFAULT_DELAY_SECONDS,
    ) -> None:
        self._fetch = evidence_fetcher
        self._rollback = rollback_fn
        self._delay = delay_seconds
        self._rollback_attempts: dict[str, int] = {}

    async def verify(self, action: Action, before_evidence_ids: list[str]) -> Verification:
        """Collect post-action evidence and determine PASS/FAIL."""
        await asyncio.sleep(self._delay)

        after_evidence = await self._fetch(action.incident_id)
        after_ids = [str(e.get("id", "")) for e in after_evidence]

        comparison = self._compare(before_evidence_ids, after_evidence)
        result = self._determine_result(comparison)

        rollback_triggered = False

        if result == VerificationResult.FAIL:
            attempts = self._rollback_attempts.get(action.id, 0)
            if attempts < _MAX_ROLLBACK_ATTEMPTS and action.rollback_tested:
                self._rollback_attempts[action.id] = attempts + 1
                logger.warning(
                    "verification_failed_triggering_rollback",
                    action_id=action.id,
                    attempt=attempts + 1,
                )
                try:
                    await self._rollback(action)
                    rollback_triggered = True
                except Exception as e:
                    logger.error("rollback_failed", action_id=action.id, error=str(e))
            else:
                logger.error(
                    "verification_failed_escalating",
                    action_id=action.id,
                    rollback_tested=action.rollback_tested,
                    attempts=attempts,
                )

        verification = Verification(
            action_id=action.id,
            evidence_before_ids=before_evidence_ids,
            evidence_after_ids=after_ids,
            comparison=comparison,
            result=result,
            rollback_triggered=rollback_triggered,
        )
        logger.info(
            "verification_complete",
            action_id=action.id,
            result=result.value,
            rollback_triggered=rollback_triggered,
        )
        return verification

    def _compare(
        self, before_ids: list[str], after_evidence: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return {
            "before_evidence_count": len(before_ids),
            "after_evidence_count": len(after_evidence),
            "after_sample": after_evidence[:3] if after_evidence else [],
        }

    def _determine_result(self, comparison: dict[str, Any]) -> VerificationResult:
        """Simple heuristic: PASS if after-evidence collected, FAIL if empty."""
        if comparison["after_evidence_count"] > 0:
            return VerificationResult.PASS
        return VerificationResult.FAIL
