from dataclasses import dataclass


@dataclass(frozen=True)
class ModelRoute:
    provider: str
    model: str
    fallback_provider: str | None = None
    fallback_model: str | None = None


# Task → (provider, model) routing table.
# Fallback is the secondary provider when primary circuit is open.
ROUTING_TABLE: dict[str, ModelRoute] = {
    "rca": ModelRoute(
        provider="claude",
        model="claude-sonnet-4-6",
        fallback_provider="gemini",
        fallback_model="gemini-2.0-flash",
    ),
    "rca_lightweight": ModelRoute(
        provider="claude",
        model="claude-haiku-4-5-20251001",
        fallback_provider="gemini",
        fallback_model="gemini-2.0-flash",
    ),
    "business_analysis": ModelRoute(
        provider="claude",
        model="claude-sonnet-4-6",
        fallback_provider="gemini",
        fallback_model="gemini-2.0-flash",
    ),
    "default": ModelRoute(
        provider="claude",
        model="claude-sonnet-4-6",
        fallback_provider="gemini",
        fallback_model="gemini-2.0-flash",
    ),
}


def resolve_route(task: str) -> ModelRoute:
    return ROUTING_TABLE.get(task, ROUTING_TABLE["default"])
