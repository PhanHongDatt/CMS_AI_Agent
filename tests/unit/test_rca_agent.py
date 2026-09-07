"""Gate G5: RCA Agent tests — uses mock LLM gateway."""

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from core.evidence.builder import EvidenceContextBuilder
from core.llm.base import LLMRequest, LLMResponse
from core.llm.cost_tracker import CostTracker
from core.llm.gateway import LLMGateway
from core.rca.agent import RCAAgent, RCAParseError
from schemas.evidence import Evidence, EvidenceSource, TrustLevel
from schemas.incident import Domain, Incident, IncidentStatus, Severity
from schemas.rca import RCA

from tests.unit.test_llm_gateway import MockProvider


def _ev(value="CrashLoopBackOff") -> Evidence:
    now = datetime.now(timezone.utc)
    return Evidence(
        incident_id=uuid.uuid4(),
        source=EvidenceSource.KUBERNETES,
        entity="api-pod",
        metric_or_query="pod_status",
        value=value,
        timestamp=now,
        source_reference="kubernetes://default/pods/api-pod",
        freshness_seconds=30.0,
        ttl_expires_at=now + timedelta(hours=24),
    )


def _incident() -> Incident:
    return Incident(
        source="alertmanager",
        fingerprint="fp-001",
        domain=Domain.INFRASTRUCTURE,
        severity=Severity.HIGH,
        trace_id=str(uuid.uuid4()),
    )


def _valid_rca_json(evidence_ids: list[str]) -> str:
    return json.dumps({
        "root_cause": "Container OOMKilled due to memory limit exceeded",
        "evidence_ids": evidence_ids,
        "affected_components": ["api-deployment", "api-pod"],
        "alternative_hypotheses": [
            {"hypothesis": "Memory leak in application code", "likelihood": 0.8},
        ],
        "recommended_action": "Increase memory limit and investigate heap usage",
        "insufficient_evidence": False,
    })


def _insufficient_rca_json() -> str:
    return json.dumps({
        "root_cause": None,
        "evidence_ids": [],
        "affected_components": [],
        "alternative_hypotheses": [],
        "recommended_action": None,
        "insufficient_evidence": True,
    })


def _mock_response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        model="claude-sonnet-4-6",
        provider="claude",
        input_tokens=500,
        output_tokens=200,
        cost_usd=0.002,
        duration_seconds=1.0,
    )


def _make_gateway(responses: list) -> LLMGateway:
    provider = MockProvider("claude", responses)
    cost = CostTracker(cost_limit_per_incident=10.0, cost_limit_daily=100.0)
    return LLMGateway({"claude": provider}, cost)


class TestRCAAgent:
    @pytest.mark.asyncio
    async def test_successful_rca(self):
        ev = _ev()
        inc = _incident()
        gw = _make_gateway([_mock_response(_valid_rca_json([str(ev.id)]))])
        agent = RCAAgent(gw)
        rca = await agent.analyze(inc, [ev])
        assert rca.root_cause is not None
        assert not rca.insufficient_evidence
        assert rca.prompt_version == "v1.0"
        assert rca.model == "claude-sonnet-4-6"

    @pytest.mark.asyncio
    async def test_insufficient_evidence_rca(self):
        inc = _incident()
        gw = _make_gateway([_mock_response(_insufficient_rca_json())])
        agent = RCAAgent(gw)
        rca = await agent.analyze(inc, [])
        assert rca.insufficient_evidence
        assert rca.root_cause is None

    @pytest.mark.asyncio
    async def test_retries_once_on_invalid_json(self):
        ev = _ev()
        inc = _incident()
        gw = _make_gateway([
            _mock_response("not valid json at all"),
            _mock_response(_valid_rca_json([str(ev.id)])),
        ])
        agent = RCAAgent(gw)
        rca = await agent.analyze(inc, [ev])
        assert rca.root_cause is not None

    @pytest.mark.asyncio
    async def test_raises_parse_error_after_max_retries(self):
        ev = _ev()
        inc = _incident()
        gw = _make_gateway([
            _mock_response("bad json 1"),
            _mock_response("bad json 2"),
        ])
        agent = RCAAgent(gw)
        with pytest.raises(RCAParseError):
            await agent.analyze(inc, [ev])

    @pytest.mark.asyncio
    async def test_strips_markdown_code_fences(self):
        ev = _ev()
        inc = _incident()
        wrapped = f"```json\n{_valid_rca_json([str(ev.id)])}\n```"
        gw = _make_gateway([_mock_response(wrapped)])
        agent = RCAAgent(gw)
        rca = await agent.analyze(inc, [ev])
        assert rca.root_cause is not None

    @pytest.mark.asyncio
    async def test_rca_with_no_evidence_uses_insufficient(self):
        """Spec: insufficient_evidence=true must not invent a root cause."""
        inc = _incident()
        gw = _make_gateway([_mock_response(_insufficient_rca_json())])
        agent = RCAAgent(gw)
        rca = await agent.analyze(inc, [])
        assert rca.insufficient_evidence is True
        assert rca.root_cause is None
