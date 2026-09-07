from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class LLMRequest:
    task: str
    system_prompt: str
    user_message: str
    max_tokens: int = 4096
    temperature: float = 0.0
    incident_id: str | None = None
    prompt_version: str = "v1.0"


@dataclass
class LLMResponse:
    content: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    duration_seconds: float


class LLMProvider(ABC):
    """Abstract interface all LLM adapters must implement."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def complete(self, request: LLMRequest, model: str) -> LLMResponse: ...

    @abstractmethod
    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str) -> float: ...
