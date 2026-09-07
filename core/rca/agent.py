"""Infrastructure RCA Agent.

Flow: Alert → Evidence → Context → LLM → Structured RCA
- Validates JSON output schema.
- Maximum one parse retry.
- Pins model + prompt version in every RCA record.
"""

import json
from dataclasses import replace

from core.evidence.builder import EvidenceContextBuilder
from core.llm.gateway import LLMGateway
from core.llm.base import LLMRequest
from core.logging import get_logger
from core.rca.prompts import PROMPT_VERSION, RCA_SYSTEM_PROMPT
from schemas.evidence import Evidence
from schemas.incident import Incident
from schemas.rca import RCA

logger = get_logger(__name__)

_TASK = "rca"
_MAX_PARSE_RETRIES = 1


class RCAParseError(Exception):
    """LLM output could not be parsed as valid RCA JSON after retries."""


class RCAAgent:
    def __init__(self, gateway: LLMGateway, model: str = "claude-sonnet-4-6") -> None:
        self._gateway = gateway
        self._model = model
        self._ctx_builder = EvidenceContextBuilder()

    async def analyze(self, incident: Incident, evidence: list[Evidence]) -> RCA:
        """Run RCA for an incident. Returns a validated RCA record."""
        evidence_context = self._ctx_builder.build(evidence)
        evidence_id_map = {str(e.id): e for e in evidence}

        user_message = self._build_user_message(incident, evidence_context, evidence)

        request = LLMRequest(
            task=_TASK,
            system_prompt=RCA_SYSTEM_PROMPT,
            user_message=user_message,
            max_tokens=2048,
            temperature=0.0,
            incident_id=str(incident.id),
            prompt_version=PROMPT_VERSION,
        )

        raw_content = ""
        parse_attempt = 0

        while parse_attempt <= _MAX_PARSE_RETRIES:
            response = await self._gateway.complete(request)
            raw_content = response.content
            model_used = response.model

            quality = 1.0 if parse_attempt == 0 else 0.5

            try:
                rca = self._parse_and_validate(raw_content, evidence_id_map, model_used, quality)
                logger.info(
                    "rca_success",
                    incident_id=str(incident.id),
                    model=model_used,
                    parse_attempt=parse_attempt,
                    insufficient_evidence=rca.insufficient_evidence,
                )
                return rca
            except (json.JSONDecodeError, ValueError, KeyError) as e:
                parse_attempt += 1
                if parse_attempt > _MAX_PARSE_RETRIES:
                    logger.error(
                        "rca_parse_failed",
                        incident_id=str(incident.id),
                        error=str(e),
                        raw=raw_content[:200],
                    )
                    raise RCAParseError(
                        f"RCA output invalid after {_MAX_PARSE_RETRIES} retries: {e}"
                    ) from e
                # Inject parse error hint into retry prompt
                request = replace(
                    request,
                    user_message=user_message
                    + f"\n\nPrevious response was not valid JSON: {e}. Respond with valid JSON only.",
                )

        raise RCAParseError("Unreachable")

    def _parse_and_validate(
        self,
        raw: str,
        evidence_id_map: dict,
        model: str,
        model_output_quality: float,
    ) -> RCA:
        # Strip markdown code fences if present
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            cleaned = "\n".join(
                l for l in lines if not l.strip().startswith("```")
            ).strip()

        data = json.loads(cleaned)

        # Validate evidence_ids reference only known IDs
        for eid in data.get("evidence_ids", []):
            if eid not in evidence_id_map and evidence_id_map:
                raise ValueError(f"Unknown evidence_id in RCA output: {eid}")

        return RCA(
            root_cause=data.get("root_cause"),
            evidence_ids=data.get("evidence_ids", []),
            affected_components=data.get("affected_components", []),
            alternative_hypotheses=data.get("alternative_hypotheses", []),
            recommended_action=data.get("recommended_action"),
            insufficient_evidence=bool(data.get("insufficient_evidence", False)),
            model=model,
            prompt_version=PROMPT_VERSION,
        )

    def _build_user_message(
        self, incident: Incident, evidence_context: str, evidence: list[Evidence]
    ) -> str:
        evidence_ids = [str(e.id) for e in evidence]
        return (
            f"Incident ID: {incident.id}\n"
            f"Severity: {incident.severity.value}\n"
            f"Domain: {incident.domain.value}\n"
            f"Source: {incident.source}\n\n"
            f"Available evidence IDs: {evidence_ids}\n\n"
            f"{evidence_context}\n\n"
            "Perform RCA and respond with JSON only."
        )
