import asyncio
import time

import google.generativeai as genai
from google.api_core.exceptions import (
    DeadlineExceeded,
    PermissionDenied,
    ResourceExhausted,
)

from core.llm.base import LLMProvider, LLMRequest, LLMResponse
from core.llm.errors import (
    LLMAuthError,
    LLMRateLimitError,
    LLMTimeoutError,
)

_COST_TABLE: dict[str, dict[str, float]] = {
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
}
_DEFAULT_COST = {"input": 0.10, "output": 0.40}

# Rough estimate: 1 token ≈ 4 characters
_CHARS_PER_TOKEN = 4


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, timeout_seconds: float = 30.0) -> None:
        genai.configure(api_key=api_key)
        self._timeout = timeout_seconds

    @property
    def name(self) -> str:
        return "gemini"

    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str) -> float:
        rates = _COST_TABLE.get(model, _DEFAULT_COST)
        return (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000

    async def complete(self, request: LLMRequest, model: str) -> LLMResponse:
        start = time.monotonic()
        client = genai.GenerativeModel(
            model_name=model,
            system_instruction=request.system_prompt,
        )
        prompt = request.user_message

        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    client.generate_content,
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        max_output_tokens=request.max_tokens,
                        temperature=request.temperature,
                    ),
                ),
                timeout=self._timeout,
            )
        except TimeoutError:
            raise LLMTimeoutError(f"Gemini request timed out after {self._timeout}s")
        except ResourceExhausted as e:
            raise LLMRateLimitError(str(e)) from e
        except PermissionDenied as e:
            raise LLMAuthError(str(e)) from e
        except DeadlineExceeded as e:
            raise LLMTimeoutError(str(e)) from e

        duration = time.monotonic() - start
        content = response.text if response.text else ""

        # Gemini SDK exposes usage_metadata when available
        usage = getattr(response, "usage_metadata", None)
        if usage:
            input_tokens = getattr(usage, "prompt_token_count", 0) or 0
            output_tokens = getattr(usage, "candidates_token_count", 0) or 0
        else:
            input_tokens = len(request.system_prompt + request.user_message) // _CHARS_PER_TOKEN
            output_tokens = len(content) // _CHARS_PER_TOKEN

        return LLMResponse(
            content=content,
            model=model,
            provider=self.name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=self.estimate_cost(input_tokens, output_tokens, model),
            duration_seconds=duration,
        )
