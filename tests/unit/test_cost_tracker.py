"""Gate G1: Cost tracker tests."""

import pytest

from core.llm.cost_tracker import CostTracker
from core.llm.errors import LLMBudgetExceededError


class TestCostTracker:
    def test_initial_state(self):
        ct = CostTracker(cost_limit_per_incident=1.0, cost_limit_daily=20.0)
        assert ct.get_daily_cost() == 0.0
        assert ct.get_incident_cost("inc-1") == 0.0

    def test_records_cost(self):
        ct = CostTracker()
        ct.record("inc-1", 0.05, 500, 1000)
        assert abs(ct.get_incident_cost("inc-1") - 0.05) < 1e-9
        assert abs(ct.get_daily_cost() - 0.05) < 1e-9

    def test_raises_when_incident_budget_exceeded(self):
        ct = CostTracker(cost_limit_per_incident=0.10)
        ct.record("inc-1", 0.09, 100, 200)
        with pytest.raises(LLMBudgetExceededError, match="Per-incident budget"):
            ct.check_budget("inc-1", estimated_cost=0.05)

    def test_raises_when_daily_budget_exceeded(self):
        ct = CostTracker(cost_limit_daily=1.00)
        ct.record(None, 0.98, 1000, 2000)
        with pytest.raises(LLMBudgetExceededError, match="Daily budget"):
            ct.check_budget(None, estimated_cost=0.05)

    def test_check_budget_ok_within_limits(self):
        ct = CostTracker(cost_limit_per_incident=1.0, cost_limit_daily=20.0)
        ct.record("inc-1", 0.50, 500, 1000)
        ct.check_budget("inc-1", 0.40)  # 0.50 + 0.40 = 0.90 < 1.0 → OK

    def test_multiple_incidents_tracked_separately(self):
        ct = CostTracker()
        ct.record("inc-A", 0.10, 100, 200)
        ct.record("inc-B", 0.20, 200, 400)
        assert abs(ct.get_incident_cost("inc-A") - 0.10) < 1e-9
        assert abs(ct.get_incident_cost("inc-B") - 0.20) < 1e-9
        assert abs(ct.get_daily_cost() - 0.30) < 1e-9

    def test_metrics_structure(self):
        ct = CostTracker()
        ct.record("inc-1", 0.05, 100, 200)
        m = ct.get_metrics()
        assert "daily_cost_usd" in m
        assert "daily_requests" in m
        assert m["daily_requests"] == 1
