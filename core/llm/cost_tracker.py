import time
from collections import defaultdict
from dataclasses import dataclass, field

from core.llm.errors import LLMBudgetExceededError


@dataclass
class CostRecord:
    total_usd: float = 0.0
    request_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class CostTracker:
    """Track LLM cost per-incident and per-day. Thread-safe via GIL for now.

    Budget exceeded → raises LLMBudgetExceededError before the request fires.
    """

    def __init__(
        self,
        cost_limit_per_incident: float = 1.00,
        cost_limit_daily: float = 20.00,
    ) -> None:
        self._per_incident: dict[str, CostRecord] = defaultdict(CostRecord)
        self._daily: CostRecord = CostRecord()
        self._day_start: float = time.time()
        self._cost_limit_per_incident = cost_limit_per_incident
        self._cost_limit_daily = cost_limit_daily

    def _reset_daily_if_needed(self) -> None:
        if time.time() - self._day_start >= 86400:
            self._daily = CostRecord()
            self._day_start = time.time()

    def check_budget(self, incident_id: str | None, estimated_cost: float) -> None:
        self._reset_daily_if_needed()
        if incident_id:
            current = self._per_incident[incident_id].total_usd
            if current + estimated_cost > self._cost_limit_per_incident:
                raise LLMBudgetExceededError(
                    f"Per-incident budget ${self._cost_limit_per_incident:.2f} exceeded "
                    f"for incident '{incident_id}' (current=${current:.4f})"
                )
        if self._daily.total_usd + estimated_cost > self._cost_limit_daily:
            raise LLMBudgetExceededError(
                f"Daily budget ${self._cost_limit_daily:.2f} exceeded "
                f"(current=${self._daily.total_usd:.4f})"
            )

    def record(
        self,
        incident_id: str | None,
        cost_usd: float,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        self._reset_daily_if_needed()
        self._daily.total_usd += cost_usd
        self._daily.request_count += 1
        self._daily.input_tokens += input_tokens
        self._daily.output_tokens += output_tokens
        if incident_id:
            rec = self._per_incident[incident_id]
            rec.total_usd += cost_usd
            rec.request_count += 1
            rec.input_tokens += input_tokens
            rec.output_tokens += output_tokens

    def get_incident_cost(self, incident_id: str) -> float:
        return self._per_incident[incident_id].total_usd

    def get_daily_cost(self) -> float:
        self._reset_daily_if_needed()
        return self._daily.total_usd

    def get_metrics(self) -> dict:
        self._reset_daily_if_needed()
        return {
            "daily_cost_usd": self._daily.total_usd,
            "daily_requests": self._daily.request_count,
            "daily_input_tokens": self._daily.input_tokens,
            "daily_output_tokens": self._daily.output_tokens,
            "active_incidents": len(self._per_incident),
        }
