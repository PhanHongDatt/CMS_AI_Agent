"""Gate G1: LLM Gateway tests — uses mock providers, no real API calls."""

import pytest

from core.llm.base import LLMProvider, LLMRequest, LLMResponse
from core.llm.cost_tracker import CostTracker
from core.llm.errors import (
    LLMAuthError,
    LLMBudgetExceededError,
    LLMCircuitOpenError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from core.llm.gateway import LLMGateway


def _make_response(provider: str = "claude", model: str = "claude-sonnet-4-6") -> LLMResponse:
    return LLMResponse(
        content='{"root_cause": "OOM"}',
        model=model,
        provider=provider,
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.001,
        duration_seconds=0.5,
    )


class MockProvider(LLMProvider):
    def __init__(self, name_: str, responses: list):
        self._name = name_
        self._responses = list(responses)
        self._call_count = 0

    @property
    def name(self) -> str:
        return self._name

    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str) -> float:
        return 0.001

    async def complete(self, request: LLMRequest, model: str) -> LLMResponse:
        self._call_count += 1
        if not self._responses:
            raise LLMUnavailableError("no more responses")
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _make_gateway(primary_responses, fallback_responses=None, **kwargs) -> LLMGateway:
    providers: dict[str, LLMProvider] = {
        "claude": MockProvider("claude", primary_responses),
    }
    if fallback_responses is not None:
        providers["gemini"] = MockProvider("gemini", fallback_responses)
    cost = CostTracker(cost_limit_per_incident=10.0, cost_limit_daily=100.0)
    return LLMGateway(providers, cost, **kwargs)


def _make_request(task: str = "rca", incident_id: str = "inc-1") -> LLMRequest:
    return LLMRequest(
        task=task,
        system_prompt="You are an SRE.",
        user_message="What caused this incident?",
        incident_id=incident_id,
    )


class TestGatewaySuccess:
    @pytest.mark.asyncio
    async def test_successful_request(self):
        gw = _make_gateway([_make_response()])
        resp = await gw.complete(_make_request())
        assert resp.content == '{"root_cause": "OOM"}'
        assert resp.provider == "claude"

    @pytest.mark.asyncio
    async def test_cost_recorded_after_success(self):
        gw = _make_gateway([_make_response()])
        await gw.complete(_make_request(incident_id="inc-cost"))
        metrics = gw.get_metrics()
        assert metrics["cost"]["daily_cost_usd"] > 0

    @pytest.mark.asyncio
    async def test_metrics_include_circuit_states(self):
        gw = _make_gateway([_make_response()])
        await gw.complete(_make_request())
        m = gw.get_metrics()
        assert "circuit_breakers" in m
        assert "claude" in m["circuit_breakers"]


class TestGatewayRetry:
    @pytest.mark.asyncio
    async def test_retries_on_rate_limit_then_succeeds(self):
        gw = _make_gateway(
            [LLMRateLimitError("rate limited"), _make_response()],
            failure_threshold=5,
        )
        resp = await gw.complete(_make_request())
        assert resp.content == '{"root_cause": "OOM"}'

    @pytest.mark.asyncio
    async def test_retries_on_timeout_then_succeeds(self):
        gw = _make_gateway(
            [LLMTimeoutError("timeout"), _make_response()],
            failure_threshold=5,
        )
        resp = await gw.complete(_make_request())
        assert resp.content == '{"root_cause": "OOM"}'

    @pytest.mark.asyncio
    async def test_does_not_retry_auth_error(self):
        primary = MockProvider("claude", [LLMAuthError("bad key"), _make_response()])
        cost = CostTracker()
        gw = LLMGateway({"claude": primary}, cost)
        with pytest.raises(LLMUnavailableError):
            await gw.complete(_make_request())
        assert primary._call_count == 1  # no retry

    @pytest.mark.asyncio
    async def test_max_retries_not_exceeded(self):
        # 3 rate limit errors → should give up after 2 retries (3 total attempts)
        primary = MockProvider("claude", [
            LLMRateLimitError("r"), LLMRateLimitError("r"), LLMRateLimitError("r"),
        ])
        cost = CostTracker()
        gw = LLMGateway({"claude": primary}, cost, failure_threshold=10)
        with pytest.raises(LLMUnavailableError):
            await gw.complete(_make_request())
        assert primary._call_count == 3  # initial + 2 retries


class TestGatewayFallback:
    @pytest.mark.asyncio
    async def test_falls_back_to_gemini_when_primary_fails(self):
        gw = _make_gateway(
            primary_responses=[LLMAuthError("bad key")],
            fallback_responses=[_make_response("gemini", "gemini-2.0-flash")],
            failure_threshold=1,
        )
        resp = await gw.complete(_make_request())
        assert resp.provider == "gemini"

    @pytest.mark.asyncio
    async def test_raises_unavailable_when_all_fail(self):
        gw = _make_gateway(
            primary_responses=[LLMAuthError("bad key")],
            fallback_responses=[LLMAuthError("bad key")],
            failure_threshold=1,
        )
        with pytest.raises(LLMUnavailableError):
            await gw.complete(_make_request())

    @pytest.mark.asyncio
    async def test_raises_unavailable_when_no_providers(self):
        cost = CostTracker()
        gw = LLMGateway({}, cost)
        with pytest.raises(LLMUnavailableError):
            await gw.complete(_make_request())


class TestGatewayCircuitBreaker:
    @pytest.mark.asyncio
    async def test_circuit_opens_after_failures(self):
        primary = MockProvider("claude", [
            LLMTimeoutError("t"), LLMTimeoutError("t"), LLMTimeoutError("t"),
        ])
        cost = CostTracker()
        gw = LLMGateway({"claude": primary}, cost, failure_threshold=3)
        with pytest.raises(LLMUnavailableError):
            await gw.complete(_make_request())
        # Circuit should now be open
        assert gw.get_metrics()["circuit_breakers"]["claude"] == "OPEN"


class TestGatewayBudget:
    @pytest.mark.asyncio
    async def test_raises_budget_exceeded_before_calling_provider(self):
        primary = MockProvider("claude", [_make_response()])
        cost = CostTracker(cost_limit_per_incident=0.0001, cost_limit_daily=100.0)
        cost.record("inc-1", 0.0001, 10, 20)
        gw = LLMGateway({"claude": primary}, cost)
        with pytest.raises(LLMBudgetExceededError):
            await gw.complete(_make_request(incident_id="inc-1"))
        assert primary._call_count == 0  # budget check stops before API call
