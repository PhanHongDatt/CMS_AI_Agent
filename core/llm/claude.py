import asyncio
import time

import anthropic

from core.llm.base import LLMProvider, LLMRequest, LLMResponse
from core.llm.errors import (
    LLMAuthError,
    LLMInvalidRequestError,
    LLMRateLimitError,
    LLMTimeoutError,
)

# Cost per 1M tokens (USD) — as of 2026-08
_COST_TABLE: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-opus-4-7": {"input": 15.00, "output": 75.00},
}
_DEFAULT_COST = {"input": 3.00, "output": 15.00}


class ClaudeProvider(LLMProvider):
    def __init__(self, api_key: str, timeout_seconds: float = 30.0) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._timeout = timeout_seconds

    @property
    def name(self) -> str:
        return "claude"

    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str) -> float:
        rates = _COST_TABLE.get(model, _DEFAULT_COST)
        return (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000

    async def complete(self, request: LLMRequest, model: str) -> LLMResponse:
        start = time.monotonic()
        try:
            response = await asyncio.wait_for(
                self._client.messages.create(
                    model=model,
                    max_tokens=request.max_tokens,
                    temperature=request.temperature,
                    system=request.system_prompt,
                    messages=[{"role": "user", "content": request.user_message}],
                ),
                timeout=self._timeout,
            )
        except TimeoutError:
            raise LLMTimeoutError(f"Claude request timed out after {self._timeout}s")
        except anthropic.RateLimitError as e:
            raise LLMRateLimitError(str(e)) from e
        except anthropic.AuthenticationError as e:
            raise LLMAuthError(str(e)) from e
        except anthropic.BadRequestError as e:
            raise LLMInvalidRequestError(str(e)) from e

        duration = time.monotonic() - start
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        content = response.content[0].text if response.content else ""

        return LLMResponse(
            content=content,
            model=model,
            provider=self.name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=self.estimate_cost(input_tokens, output_tokens, model),
            duration_seconds=duration,
        )
