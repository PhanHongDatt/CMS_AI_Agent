import asyncio
import time

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from core.llm.base import LLMProvider, LLMRequest, LLMResponse
from core.llm.errors import (
    LLMAuthError,
    LLMRateLimitError,
    LLMTimeoutError,
)

# NOTE (2026-09): key format mới của Google AI Studio ("AQ....") KHÔNG hoạt
# động với SDK cũ google.generativeai (deprecated) — trả 403 "project denied"
# gây hiểu lầm là account bị chặn. Bắt buộc dùng SDK mới google-genai.
_COST_TABLE: dict[str, dict[str, float]] = {
    "gemini-3.5-flash": {"input": 0.10, "output": 0.40},
}
_DEFAULT_COST = {"input": 0.10, "output": 0.40}

# Rough estimate: 1 token ≈ 4 characters (fallback nếu SDK không trả usage)
_CHARS_PER_TOKEN = 4


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, timeout_seconds: float = 30.0) -> None:
        self._client = genai.Client(api_key=api_key)
        self._timeout = timeout_seconds

    @property
    def name(self) -> str:
        return "gemini"

    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str) -> float:
        rates = _COST_TABLE.get(model, _DEFAULT_COST)
        return (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000

    async def complete(self, request: LLMRequest, model: str) -> LLMResponse:
        start = time.monotonic()
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.models.generate_content,
                    model=model,
                    contents=request.user_message,
                    config=types.GenerateContentConfig(
                        system_instruction=request.system_prompt,
                        max_output_tokens=request.max_tokens,
                        temperature=request.temperature,
                    ),
                ),
                timeout=self._timeout,
            )
        except TimeoutError:
            raise LLMTimeoutError(f"Gemini request timed out after {self._timeout}s")
        except genai_errors.ClientError as e:
            status = getattr(e, "code", None)
            if status == 429:
                raise LLMRateLimitError(str(e)) from e
            if status in (401, 403):
                raise LLMAuthError(str(e)) from e
            raise
        except genai_errors.ServerError as e:
            raise LLMTimeoutError(str(e)) from e

        duration = time.monotonic() - start
        content = response.text or ""

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
