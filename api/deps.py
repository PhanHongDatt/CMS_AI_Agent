"""Singleton service container — injected into FastAPI routes and pipeline."""

import os

from core.approval.manager import ApprovalManager
from core.approval.notifier import TelegramNotifier
from core.logging import get_logger

_log = get_logger(__name__)
from core.autonomy.level import AutonomyRegistry
from core.confidence.engine import ConfidenceEngine
from core.incident.correlator import AlertCorrelator
from core.incident.manager import IncidentManager
from core.llm.cost_tracker import CostTracker
from core.llm.gateway import LLMGateway
from core.llm.mock_provider import MockLLMProvider
from core.pipeline.evidence_gatherer import MockActionTools, MockEvidenceGatherer
from core.pipeline.runner import PipelineRunner
from core.policy.engine import PolicyEngine
from core.rca.agent import RCAAgent
from core.remediation.executor import RemediationExecutor

# ── Core singletons ───────────────────────────────────────────────────────────
_correlator = AlertCorrelator()
_incident_manager = IncidentManager(correlator=_correlator)
_approval_manager = ApprovalManager(timeout_seconds=300.0)
_autonomy_registry = AutonomyRegistry()
_confidence_engine = ConfidenceEngine()
_policy_engine = PolicyEngine()

# ── LLM Gateway (mock if no real keys configured) ─────────────────────────────
def _build_llm_gateway() -> LLMGateway:
    # Routing table hardcodes "claude" as primary provider.
    # Register mock under "claude" as default so pipeline works without real keys.
    # Real ClaudeProvider replaces mock if ANTHROPIC_API_KEY is set.
    providers: dict = {"claude": MockLLMProvider(), "gemini": MockLLMProvider()}

    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if anthropic_key:
        try:
            from core.llm.claude import ClaudeProvider
            providers["claude"] = ClaudeProvider(api_key=anthropic_key)
            _log.info("llm_provider_loaded", provider="claude")
        except Exception as e:
            _log.warning("claude_provider_init_failed", error=str(e))

    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        try:
            from core.llm.gemini import GeminiProvider
            providers["gemini"] = GeminiProvider(api_key=gemini_key)
            _log.info("llm_provider_loaded", provider="gemini")
        except Exception as e:
            _log.warning("gemini_provider_init_failed", error=str(e))

    cost_tracker = CostTracker(cost_limit_per_incident=1.0, cost_limit_daily=20.0)
    return LLMGateway(providers=providers, cost_tracker=cost_tracker)


_llm_gateway = _build_llm_gateway()
_rca_agent = RCAAgent(gateway=_llm_gateway)

# ── Telegram Notifier (optional) ──────────────────────────────────────────────
def _build_notifier() -> TelegramNotifier | None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if token and chat_id:
        return TelegramNotifier(bot_token=token, chat_id=chat_id)
    return None


_notifier = _build_notifier()

# ── Remediation (mock action tools — swap for real MCP in production) ─────────
_action_tools = MockActionTools()
_executor = RemediationExecutor(action_tools=_action_tools)

# ── Pipeline Runner ───────────────────────────────────────────────────────────
_pipeline_runner = PipelineRunner(
    incident_manager=_incident_manager,
    evidence_gatherer=MockEvidenceGatherer(),
    rca_agent=_rca_agent,
    confidence_engine=_confidence_engine,
    policy_engine=_policy_engine,
    approval_manager=_approval_manager,
    notifier=_notifier,
    remediation_executor=_executor,
    environment=os.getenv("APP_ENV", "development"),
)


# ── Dependency getters ────────────────────────────────────────────────────────
def get_incident_manager() -> IncidentManager:
    return _incident_manager


def get_approval_manager() -> ApprovalManager:
    return _approval_manager


def get_autonomy_registry() -> AutonomyRegistry:
    return _autonomy_registry


def get_pipeline_runner() -> PipelineRunner:
    return _pipeline_runner
