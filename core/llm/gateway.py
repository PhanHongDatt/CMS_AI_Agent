"""LLM Gateway — single entry point for all LLM calls.

Flow per request:
  1. Resolve route (task → provider + model)
  2. Check budget
  3. Check circuit breaker
  4. Call provider with retry (max 2, exponential backoff)
  5. On primary failure → try fallback provider
  6. Record cost
  7. Raise LLMUnavailableError if all paths exhausted
"""

import asyncio

from core.llm.base import LLMProvider, LLMRequest, LLMResponse
from core.llm.circuit_breaker import CircuitBreaker
from core.llm.cost_tracker import CostTracker
from core.llm.errors import (
    LLMAuthError,
    LLMBudgetExceededError,
    LLMCircuitOpenError,
    LLMInvalidRequestError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from core.llm.router import ModelRoute, resolve_route
from core.logging import get_logger

logger = get_logger(__name__)

_RETRYABLE = (LLMRateLimitError, LLMTimeoutError)
_NON_RETRYABLE = (LLMAuthError, LLMInvalidRequestError)

_MAX_RETRIES = 2
_BACKOFF_BASE = 1.0  # seconds


class LLMGateway:
    def __init__(
        self,
        providers: dict[str, LLMProvider],
        cost_tracker: CostTracker,
        timeout_seconds: float = 30.0,
        failure_threshold: int = 3,
        recovery_timeout_seconds: float = 60.0,
    ) -> None:
        self._providers = providers
        self._cost = cost_tracker
        self._timeout = timeout_seconds
        self._breakers: dict[str, CircuitBreaker] = {
            name: CircuitBreaker(name, failure_threshold, recovery_timeout_seconds)
            for name in providers
        }

    async def complete(self, request: LLMRequest) -> LLMResponse:
        route = resolve_route(request.task)

        # Budget pre-check with rough estimate
        estimated = self._rough_estimate(route, request)
        try:
            self._cost.check_budget(request.incident_id, estimated)
        except LLMBudgetExceededError:
            raise

        # Try primary, then fallback
        response = await self._try_route(request, route.provider, route.model)
        if response is None and route.fallback_provider and route.fallback_model:
            logger.warning(
                "primary_provider_failed_using_fallback",
                primary=route.provider,
                fallback=route.fallback_provider,
            )
            response = await self._try_route(
                request, route.fallback_provider, route.fallback_model
            )

        if response is None:
            raise LLMUnavailableError(
                f"All providers unavailable for task '{request.task}'"
            )

        self._cost.record(
            request.incident_id,
            response.cost_usd,
            response.input_tokens,
            response.output_tokens,
        )
        return response

    async def _try_route(
        self, request: LLMRequest, provider_name: str, model: str
    ) -> LLMResponse | None:
        provider = self._providers.get(provider_name)
        if provider is None:
            return None

        breaker = self._breakers[provider_name]
        try:
            breaker.allow_request()
        except LLMCircuitOpenError:
            logger.warning("circuit_open", provider=provider_name)
            return None

        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = await provider.complete(request, model)
                breaker.record_success()
                return response
            except _NON_RETRYABLE as e:
                breaker.record_failure()
                logger.error("llm_non_retryable_error", provider=provider_name, error=str(e))
                return None
            except _RETRYABLE as e:
                breaker.record_failure()
                if attempt < _MAX_RETRIES:
                    delay = _BACKOFF_BASE * (2**attempt)
                    logger.warning(
                        "llm_retryable_error_retrying",
                        provider=provider_name,
                        attempt=attempt + 1,
                        delay=delay,
                        error=str(e),
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "llm_max_retries_exceeded", provider=provider_name, error=str(e)
                    )
            except Exception as e:
                breaker.record_failure()
                logger.error("llm_unexpected_error", provider=provider_name, error=str(e))
                return None

        return None

    def _rough_estimate(self, route: ModelRoute, request: LLMRequest) -> float:
        provider = self._providers.get(route.provider)
        if provider is None:
            return 0.0
        # Estimate ~500 input tokens, ~1000 output tokens
        return provider.estimate_cost(500, 1000, route.model)

    def get_metrics(self) -> dict:
        return {
            "cost": self._cost.get_metrics(),
            "circuit_breakers": {
                name: cb.state.value for name, cb in self._breakers.items()
            },
        }
