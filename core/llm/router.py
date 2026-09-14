from dataclasses import dataclass


@dataclass(frozen=True)
class ModelRoute:
    provider: str
    model: str
    fallback_provider: str | None = None
    fallback_model: str | None = None


# Task → (provider, model) routing table. Model đều PIN cứng — không dùng
# alias "latest"/"-preview" (tránh Google/OpenAI đổi hành vi/giá âm thầm).
# Fallback là provider phụ khi circuit breaker của provider chính mở.
ROUTING_TABLE: dict[str, ModelRoute] = {
    "rca": ModelRoute(
        provider="openai",
        model="gpt-4.1-mini",
        fallback_provider="gemini",
        fallback_model="gemini-3.5-flash",
    ),
    "rca_lightweight": ModelRoute(
        provider="openai",
        model="gpt-4.1-mini",
        fallback_provider="gemini",
        fallback_model="gemini-3.5-flash",
    ),
    "business_analysis": ModelRoute(
        provider="openai",
        model="gpt-4.1-mini",
        fallback_provider="gemini",
        fallback_model="gemini-3.5-flash",
    ),
    "default": ModelRoute(
        provider="openai",
        model="gpt-4.1-mini",
        fallback_provider="gemini",
        fallback_model="gemini-3.5-flash",
    ),
}


def resolve_route(task: str) -> ModelRoute:
    return ROUTING_TABLE.get(task, ROUTING_TABLE["default"])
