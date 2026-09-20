import asyncio
import time

import openai

from core.llm.base import LLMProvider, LLMRequest, LLMResponse
from core.llm.errors import (
    LLMAuthError,
    LLMInvalidRequestError,
    LLMRateLimitError,
    LLMTimeoutError,
)

# Cost per 1M tokens (USD) — as of 2026-09
_COST_TABLE: dict[str, dict[str, float]] = {
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
}
_DEFAULT_COST = {"input": 0.40, "output": 1.60}


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, timeout_seconds: float = 30.0) -> None:
        self._client = openai.AsyncOpenAI(api_key=api_key)
        self._timeout = timeout_seconds

    @property
    def name(self) -> str:
        return "openai"

    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str) -> float:
        rates = _COST_TABLE.get(model, _DEFAULT_COST)
        return (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000

    async def complete(self, request: LLMRequest, model: str) -> LLMResponse:
        start = time.monotonic()
        try:
            response = await asyncio.wait_for(
                self._client.chat.completions.create(
                    model=model,
                    max_tokens=request.max_tokens,
                    temperature=request.temperature,
                    messages=[
                        {"role": "system", "content": request.system_prompt},
                        {"role": "user", "content": request.user_message},
                    ],
                ),
                timeout=self._timeout,
            )
        except TimeoutError as e:
            raise LLMTimeoutError(f"OpenAI request timed out after {self._timeout}s") from e
        except openai.RateLimitError as e:
            raise LLMRateLimitError(str(e)) from e
        except openai.AuthenticationError as e:
            raise LLMAuthError(str(e)) from e
        except openai.BadRequestError as e:
            raise LLMInvalidRequestError(str(e)) from e

        duration = time.monotonic() - start
        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0
        content = response.choices[0].message.content or "" if response.choices else ""

        return LLMResponse(
            content=content,
            model=model,
            provider=self.name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=self.estimate_cost(input_tokens, output_tokens, model),
            duration_seconds=duration,
        )
