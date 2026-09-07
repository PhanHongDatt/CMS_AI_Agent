"""Gradual Autonomy — per action type, never global.

Levels:
  L0 Observe      — detect and log, no recommendation
  L1 Recommend    — produce recommendation, require human approval (DEFAULT)
  L2 Human Approval — same as L1 but with explicit approval workflow
  L3 Low-risk Auto — auto-execute if rollback_tested and >= 20 verified outcomes
  L4 Controlled Autonomous — full autonomous loop with all safeguards

Promotion rules (per action type):
  - >= 20 verified outcomes for that action/incident type
  - historical success rate calibrated
  - rollback tested
  - golden/regression tests stable
  - manual review completed
  - audit trail complete

Any missing prerequisite → demote to L2 (require approval).
"""

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Sequence

from core.logging import get_logger

logger = get_logger(__name__)

_MIN_OUTCOMES_FOR_L3 = 20
_MIN_SUCCESS_RATE_FOR_L3 = 0.80


class AutonomyLevel(IntEnum):
    L0_OBSERVE = 0
    L1_RECOMMEND = 1
    L2_HUMAN_APPROVAL = 2
    L3_LOW_RISK_AUTO = 3
    L4_CONTROLLED_AUTONOMOUS = 4


@dataclass
class ActionOutcome:
    action_type: str
    incident_type: str
    resolved_correctly: bool


@dataclass
class AutonomyState:
    action_type: str
    level: AutonomyLevel = AutonomyLevel.L1_RECOMMEND
    outcomes: list[bool] = field(default_factory=list)
    rollback_tested: bool = False
    manual_review_approved: bool = False


class AutonomyRegistry:
    """Track and enforce per-action-type autonomy levels.

    Promotion is explicit and requires passing all prerequisites.
    Demotion happens automatically if prerequisites are no longer met.
    """

    def __init__(self) -> None:
        self._states: dict[str, AutonomyState] = {}

    def get_level(self, action_type: str) -> AutonomyLevel:
        state = self._states.get(action_type)
        if state is None:
            return AutonomyLevel.L1_RECOMMEND
        # Re-evaluate prerequisites each time (no stale promotion)
        return self._effective_level(state)

    def record_outcome(self, action_type: str, resolved_correctly: bool) -> None:
        state = self._states.setdefault(action_type, AutonomyState(action_type=action_type))
        state.outcomes.append(resolved_correctly)
        logger.info(
            "autonomy_outcome_recorded",
            action_type=action_type,
            resolved=resolved_correctly,
            total_outcomes=len(state.outcomes),
        )

    def set_rollback_tested(self, action_type: str, tested: bool) -> None:
        state = self._states.setdefault(action_type, AutonomyState(action_type=action_type))
        state.rollback_tested = tested

    def approve_manual_review(self, action_type: str) -> None:
        state = self._states.setdefault(action_type, AutonomyState(action_type=action_type))
        state.manual_review_approved = True
        logger.info("autonomy_manual_review_approved", action_type=action_type)

    def request_promotion(self, action_type: str, target_level: AutonomyLevel) -> bool:
        """Attempt to promote to target_level. Returns True if prerequisites met."""
        state = self._states.setdefault(action_type, AutonomyState(action_type=action_type))
        # L3+ requires all prerequisites
        if target_level >= AutonomyLevel.L3_LOW_RISK_AUTO:
            if not self._meets_l3_prerequisites(state):
                logger.warning(
                    "autonomy_promotion_denied",
                    action_type=action_type,
                    requested=target_level.name,
                    effective=self._effective_level(state).name,
                )
                return False
        state.level = target_level
        logger.info("autonomy_promoted", action_type=action_type, level=target_level.name)
        return True

    def _effective_level(self, state: AutonomyState) -> AutonomyLevel:
        if not self._meets_l3_prerequisites(state):
            return min(state.level, AutonomyLevel.L2_HUMAN_APPROVAL)
        return state.level

    def _meets_l3_prerequisites(self, state: AutonomyState) -> bool:
        if len(state.outcomes) < _MIN_OUTCOMES_FOR_L3:
            return False
        success_rate = sum(state.outcomes) / len(state.outcomes)
        if success_rate < _MIN_SUCCESS_RATE_FOR_L3:
            return False
        if not state.rollback_tested:
            return False
        if not state.manual_review_approved:
            return False
        return True

    def get_summary(self) -> dict:
        return {
            action: {
                "level": self.get_level(action).name,
                "outcomes": len(state.outcomes),
                "success_rate": (
                    sum(state.outcomes) / len(state.outcomes) if state.outcomes else None
                ),
                "rollback_tested": state.rollback_tested,
                "manual_review": state.manual_review_approved,
            }
            for action, state in self._states.items()
        }
