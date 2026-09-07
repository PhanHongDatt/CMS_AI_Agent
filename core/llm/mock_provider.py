"""Mock LLM provider — returns deterministic RCA JSON for simulation/dev mode."""

import json
import re

from core.llm.base import LLMProvider, LLMRequest, LLMResponse


class MockLLMProvider(LLMProvider):
    """Returns a canned RCA response. Used when no real API key is configured."""

    @property
    def name(self) -> str:
        return "mock"

    async def complete(self, request: LLMRequest, model: str) -> LLMResponse:
        evidence_ids = self._extract_evidence_ids(request.user_message)
        rca = {
            "root_cause": "Pod OOMKilled due to memory limit breach; restart loop detected.",
            "evidence_ids": evidence_ids[:2],
            "affected_components": ["api-server"],
            "alternative_hypotheses": ["Memory leak in application code", "Sudden traffic spike"],
            "recommended_action": "restart_pod",
            "insufficient_evidence": False,
        }
        return LLMResponse(
            content=json.dumps(rca),
            model="mock-llm",
            provider="mock",
            input_tokens=100,
            output_tokens=80,
            cost_usd=0.0,
            duration_seconds=0.01,
        )

    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str) -> float:
        return 0.0

    def _extract_evidence_ids(self, message: str) -> list[str]:
        return re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", message)
