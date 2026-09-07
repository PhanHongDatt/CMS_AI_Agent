"""Controlled Remediation Executor.

Invariants:
- Valid policy_decision_id required; MCP rejects missing/invalid.
- Only whitelisted actions may execute.
- Per-entity lock prevents concurrent remediation on same target.
- Pre-state snapshot taken before every action.
- Action timeout enforced.
- Idempotency key prevents duplicate execution.
- Forbidden actions never execute.
"""

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Any

from core.logging import get_logger
from mcp.base import ActionContext
from schemas.action import Action, ActionStatus
from schemas.policy import PolicyDecision, PolicyDecisionEnum, Risk

logger = get_logger(__name__)

# Whitelisted actions only — all others DENY at MCP level
_WHITELIST: dict[str, Risk] = {
    "restart_pod": Risk.LOW,
    "scale_deployment": Risk.LOW,
    "rollback_deployment": Risk.MEDIUM,
}

# Actions that are always forbidden regardless of policy
_FORBIDDEN = {
    "kubectl_exec",
    "delete_namespace",
    "database_write",
    "terraform_apply",
    "terraform_destroy",
    "helm_uninstall",
    "shell_exec",
}

_DEFAULT_TIMEOUT_SECONDS = 60.0


@dataclass
class RemediationRequest:
    action_name: str
    incident_id: str
    policy_decision: PolicyDecision
    action_params: dict[str, Any]
    idempotency_key: str
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS


class RemediationExecutor:
    def __init__(self, action_tools: Any) -> None:
        self._tools = action_tools
        self._executed: dict[str, Action] = {}   # idempotency_key → Action
        self._entity_locks: dict[str, asyncio.Lock] = {}

    async def execute(self, req: RemediationRequest) -> Action:
        """Execute a whitelisted action with all safety checks."""
        # Idempotency: return existing result for duplicate key
        if req.idempotency_key in self._executed:
            logger.info("remediation_idempotent_skip", key=req.idempotency_key)
            return self._executed[req.idempotency_key]

        self._validate(req)

        entity_key = self._entity_key(req)
        lock = self._entity_locks.setdefault(entity_key, asyncio.Lock())

        async with lock:
            # Double-check idempotency after acquiring lock
            if req.idempotency_key in self._executed:
                return self._executed[req.idempotency_key]

            pre_state = await self._snapshot(req)

            action = Action(
                id=str(uuid.uuid4()),
                incident_id=req.incident_id,
                policy_decision_id=req.policy_decision.id,
                name=req.action_name,
                risk=_WHITELIST[req.action_name],
                rollback_supported=req.action_name in ("restart_pod", "rollback_deployment"),
                rollback_tested=req.action_params.get("rollback_tested", False),
                pre_state_snapshot=pre_state,
                status=ActionStatus.EXECUTING,
            )
            self._executed[req.idempotency_key] = action

            ctx = ActionContext(
                policy_decision_id=req.policy_decision.id,
                incident_id=req.incident_id,
                trace_id=str(uuid.uuid4()),
            )

            try:
                await asyncio.wait_for(
                    self._dispatch(ctx, req),
                    timeout=req.timeout_seconds,
                )
                final = action.model_copy(
                    update={"status": ActionStatus.SUCCESS, "executed_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc)}
                )
            except TimeoutError:
                logger.error("remediation_timeout", action=req.action_name)
                final = action.model_copy(update={"status": ActionStatus.TIMEOUT})
            except Exception as e:
                logger.error("remediation_failed", action=req.action_name, error=str(e))
                final = action.model_copy(update={"status": ActionStatus.FAILED})

            self._executed[req.idempotency_key] = final
            logger.info(
                "remediation_complete",
                action=req.action_name,
                status=final.status.value,
                incident_id=req.incident_id,
            )
            return final

    def _validate(self, req: RemediationRequest) -> None:
        if req.action_name in _FORBIDDEN:
            raise PermissionError(f"Action '{req.action_name}' is explicitly forbidden")
        if req.action_name not in _WHITELIST:
            raise PermissionError(f"Action '{req.action_name}' is not whitelisted")
        if req.policy_decision.decision != PolicyDecisionEnum.ALLOW:
            raise PermissionError(
                f"Policy decision is '{req.policy_decision.decision.value}', not ALLOW"
            )
        if not req.policy_decision.id:
            raise PermissionError("Missing policy_decision_id")

    async def _snapshot(self, req: RemediationRequest) -> dict[str, Any]:
        return {"action": req.action_name, "params": req.action_params, "snapshot_at": time.time()}

    async def _dispatch(self, ctx: ActionContext, req: RemediationRequest) -> None:
        name = req.action_name
        params = req.action_params
        if name == "restart_pod":
            await self._tools.restart_pod(ctx, params["namespace"], params["pod_name"])
        elif name == "scale_deployment":
            await self._tools.scale_deployment(ctx, params["namespace"], params["deployment"], params["replicas"])
        elif name == "rollback_deployment":
            await self._tools.rollback_deployment(ctx, params["namespace"], params["deployment"])
        else:
            raise PermissionError(f"Unknown action: {name}")

    def _entity_key(self, req: RemediationRequest) -> str:
        params = req.action_params
        ns = params.get("namespace", "default")
        name = params.get("pod_name") or params.get("deployment") or req.action_name
        return f"{ns}/{name}"
