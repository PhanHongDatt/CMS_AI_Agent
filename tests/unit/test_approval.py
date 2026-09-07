"""Gate G8: Approval manager tests."""

import asyncio
import uuid

import pytest

from core.approval.manager import ApprovalDecision, ApprovalManager, ApprovalRequest, ApprovalStatus


def _req(request_id: str | None = None, incident_id: str = "inc-1") -> ApprovalRequest:
    return ApprovalRequest(
        request_id=request_id or str(uuid.uuid4()),
        incident_id=incident_id,
        policy_decision_id="pd-1",
        action_name="restart_pod",
        risk="LOW",
        rollback_tested=True,
        proposed_evidence_summary="CPU 95%, OOM events",
        rca_summary="Container OOMKilled",
        confidence_score=0.85,
    )


class TestApprovalManager:
    def test_submit_registers_request(self):
        mgr = ApprovalManager()
        req = _req()
        mgr.submit(req)
        assert req in mgr.get_pending()

    def test_decide_approve(self):
        mgr = ApprovalManager()
        req = _req()
        mgr.submit(req)
        decision = mgr.decide(req.request_id, approved=True, decided_by="ops-user")
        assert decision.status == ApprovalStatus.APPROVED
        assert decision.decided_by == "ops-user"

    def test_decide_reject(self):
        mgr = ApprovalManager()
        req = _req()
        mgr.submit(req)
        decision = mgr.decide(req.request_id, approved=False, decided_by="ops-user", reason="Too risky")
        assert decision.status == ApprovalStatus.REJECTED
        assert decision.reason == "Too risky"

    def test_duplicate_approval_is_idempotent(self):
        """Spec: duplicate approval protection."""
        mgr = ApprovalManager()
        req = _req()
        mgr.submit(req)
        d1 = mgr.decide(req.request_id, approved=True, decided_by="user-A")
        d2 = mgr.decide(req.request_id, approved=False, decided_by="user-B")
        # Second call ignored — first decision stands
        assert d1.status == ApprovalStatus.APPROVED
        assert d2.status == ApprovalStatus.APPROVED

    def test_decided_request_removed_from_pending(self):
        mgr = ApprovalManager()
        req = _req()
        mgr.submit(req)
        mgr.decide(req.request_id, approved=True, decided_by="user")
        assert req not in mgr.get_pending()

    def test_get_decision(self):
        mgr = ApprovalManager()
        req = _req()
        mgr.submit(req)
        mgr.decide(req.request_id, approved=True, decided_by="user")
        d = mgr.get_decision(req.request_id)
        assert d is not None
        assert d.status == ApprovalStatus.APPROVED

    @pytest.mark.asyncio
    async def test_wait_for_decision_approved(self):
        mgr = ApprovalManager(timeout_seconds=5.0)
        req = _req()
        mgr.submit(req)

        async def approve_later():
            await asyncio.sleep(0.05)
            mgr.decide(req.request_id, approved=True, decided_by="auto-test")

        asyncio.create_task(approve_later())
        decision = await mgr.wait_for_decision(req.request_id)
        assert decision.status == ApprovalStatus.APPROVED

    @pytest.mark.asyncio
    async def test_wait_for_decision_timeout(self):
        """Spec: timeout → TIMEOUT status."""
        mgr = ApprovalManager(timeout_seconds=0.05)
        req = _req()
        mgr.submit(req)
        decision = await mgr.wait_for_decision(req.request_id)
        assert decision.status == ApprovalStatus.TIMEOUT

    @pytest.mark.asyncio
    async def test_wait_returns_immediately_if_already_decided(self):
        mgr = ApprovalManager()
        req = _req()
        mgr.submit(req)
        mgr.decide(req.request_id, approved=True, decided_by="user")
        decision = await mgr.wait_for_decision(req.request_id)
        assert decision.status == ApprovalStatus.APPROVED

    def test_audit_trail_exists_for_every_decision(self):
        mgr = ApprovalManager()
        req = _req()
        mgr.submit(req)
        mgr.decide(req.request_id, approved=True, decided_by="user")
        d = mgr.get_decision(req.request_id)
        assert d is not None
        assert d.decided_at > 0
        assert d.decided_by is not None
