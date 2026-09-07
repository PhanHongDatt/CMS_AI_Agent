"""Policy Engine — deterministic rule-based decision making.

Inputs: severity, confidence, risk, blast_radius, rollback_tested, environment, action_type.
Default final rule: DENY.
Unknown rule → DEFAULT_DENY.

INVARIANT: confidence > 0.80 alone NEVER grants AUTO authorization.
HIGH risk ALWAYS requires human approval regardless of confidence.
"""

import uuid
from dataclasses import dataclass

from schemas.confidence import Confidence
from schemas.incident import Severity
from schemas.policy import PolicyDecision, PolicyDecisionEnum, PolicyInputs, Risk

_PRODUCTION = "production"
_STAGING = "staging"


@dataclass(frozen=True)
class PolicyRequest:
    incident_id: str
    action_type: str
    confidence: Confidence
    severity: Severity
    risk: Risk
    blast_radius: str
    rollback_tested: bool
    environment: str


class PolicyEngine:
    """Evaluate a PolicyRequest against ordered rules.

    Rules are evaluated top-to-bottom; first match wins.
    If no rule matches, DEFAULT_DENY applies.
    """

    def evaluate(self, req: PolicyRequest) -> PolicyDecision:
        score = req.confidence.final_score
        inputs = PolicyInputs(
            confidence=score,
            severity=req.severity,
            risk=req.risk,
            blast_radius=req.blast_radius,
            rollback_tested=req.rollback_tested,
            environment=req.environment,
        )

        decision, reason, rule = self._match_rules(req, score)

        return PolicyDecision(
            id=str(uuid.uuid4()),
            incident_id=req.incident_id,
            decision=decision,
            reason=reason,
            inputs=inputs,
            rule_matched=rule,
        )

    def _match_rules(
        self, req: PolicyRequest, score: float
    ) -> tuple[PolicyDecisionEnum, str, str]:
        # Rule 1: CRITICAL severity → always require approval
        if req.severity == Severity.CRITICAL:
            return (
                PolicyDecisionEnum.REQUIRE_APPROVAL,
                "CRITICAL severity requires human approval",
                "CRITICAL_SEVERITY",
            )

        # Rule 2: HIGH risk → always require approval (regardless of confidence)
        if req.risk == Risk.HIGH:
            return (
                PolicyDecisionEnum.REQUIRE_APPROVAL,
                "HIGH risk action always requires human approval",
                "HIGH_RISK",
            )

        # Rule 3: Production environment → require approval for MEDIUM risk
        if req.environment == _PRODUCTION and req.risk == Risk.MEDIUM:
            return (
                PolicyDecisionEnum.REQUIRE_APPROVAL,
                "MEDIUM risk in production requires human approval",
                "PROD_MEDIUM_RISK",
            )

        # Rule 4: Rollback not tested → require approval
        if not req.rollback_tested:
            return (
                PolicyDecisionEnum.REQUIRE_APPROVAL,
                "Rollback procedure not tested; human approval required",
                "ROLLBACK_NOT_TESTED",
            )

        # Rule 5: Low confidence → deny
        if score < 0.60:
            return (
                PolicyDecisionEnum.DENY,
                f"Confidence {score:.2f} too low (threshold: 0.60)",
                "LOW_CONFIDENCE_DENY",
            )

        # Rule 6: Moderate confidence → require approval
        if score < 0.80:
            return (
                PolicyDecisionEnum.REQUIRE_APPROVAL,
                f"Confidence {score:.2f} requires human approval (threshold: 0.80)",
                "MODERATE_CONFIDENCE_APPROVAL",
            )

        # Rule 7: High confidence + LOW risk + rollback tested + non-critical → AUTO allowed
        if score >= 0.80 and req.risk == Risk.LOW and req.rollback_tested:
            return (
                PolicyDecisionEnum.ALLOW,
                f"Confidence {score:.2f} sufficient for LOW risk auto-remediation",
                "HIGH_CONFIDENCE_LOW_RISK_AUTO",
            )

        # DEFAULT: deny anything not explicitly allowed
        return (
            PolicyDecisionEnum.DENY,
            "No rule matched; defaulting to DENY",
            "DEFAULT_DENY",
        )
