"""Gate G10: Verification + Rollback tests."""

import asyncio
import uuid
from unittest.mock import AsyncMock

import pytest

from core.verification.engine import VerificationEngine
from schemas.action import Action, ActionStatus
from schemas.policy import Risk
from schemas.verification import VerificationResult


def _action(rollback_tested: bool = True) -> Action:
    return Action(
        id=str(uuid.uuid4()),
        incident_id="inc-1",
        policy_decision_id="pd-1",
        name="restart_pod",
        risk=Risk.LOW,
        rollback_supported=True,
        rollback_tested=rollback_tested,
        pre_state_snapshot={"pod": "api-pod"},
        status=ActionStatus.SUCCESS,
    )


def _make_engine(after_evidence: list, rollback_fn=None, delay: float = 0.0) -> VerificationEngine:
    async def fetcher(incident_id: str) -> list:
        return after_evidence

    return VerificationEngine(
        evidence_fetcher=fetcher,
        rollback_fn=rollback_fn or AsyncMock(),
        delay_seconds=delay,
    )


class TestVerificationEngine:
    @pytest.mark.asyncio
    async def test_pass_when_after_evidence_present(self):
        engine = _make_engine(after_evidence=[{"id": "ev-after", "status": "ok"}])
        action = _action()
        v = await engine.verify(action, ["ev-before"])
        assert v.result == VerificationResult.PASS
        assert not v.rollback_triggered

    @pytest.mark.asyncio
    async def test_fail_when_no_after_evidence(self):
        rollback = AsyncMock()
        engine = _make_engine(after_evidence=[], rollback_fn=rollback)
        action = _action(rollback_tested=True)
        v = await engine.verify(action, ["ev-before"])
        assert v.result == VerificationResult.FAIL
        assert v.rollback_triggered
        rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_rollback_when_not_tested(self):
        rollback = AsyncMock()
        engine = _make_engine(after_evidence=[], rollback_fn=rollback)
        action = _action(rollback_tested=False)
        v = await engine.verify(action, ["ev-before"])
        assert v.result == VerificationResult.FAIL
        assert not v.rollback_triggered
        rollback.assert_not_called()

    @pytest.mark.asyncio
    async def test_max_rollback_attempts_respected(self):
        """Spec: maximum rollback attempts = 1."""
        rollback = AsyncMock()
        engine = _make_engine(after_evidence=[], rollback_fn=rollback)
        action = _action(rollback_tested=True)
        # First verify → rollback triggered
        v1 = await engine.verify(action, ["ev-before"])
        assert v1.rollback_triggered
        # Second verify same action → no more rollback (limit reached)
        v2 = await engine.verify(action, ["ev-before"])
        assert not v2.rollback_triggered
        assert rollback.call_count == 1

    @pytest.mark.asyncio
    async def test_verification_records_before_and_after_ids(self):
        engine = _make_engine(after_evidence=[{"id": "ev-after-1"}])
        action = _action()
        v = await engine.verify(action, ["ev-before-1", "ev-before-2"])
        assert "ev-before-1" in v.evidence_before_ids
        assert "ev-before-2" in v.evidence_before_ids
        assert "ev-after-1" in v.evidence_after_ids

    @pytest.mark.asyncio
    async def test_rollback_failure_does_not_raise(self):
        async def bad_rollback(action):
            raise RuntimeError("rollback infra error")

        engine = _make_engine(after_evidence=[], rollback_fn=bad_rollback)
        action = _action(rollback_tested=True)
        # Should not propagate rollback error
        v = await engine.verify(action, ["ev-before"])
        assert v.result == VerificationResult.FAIL
