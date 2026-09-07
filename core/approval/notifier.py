"""Notification interface.

Channels: Telegram + Webhook.
Notification includes: incident, severity, RCA, evidence, confidence, policy, action, risk, rollback status.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx

from core.approval.manager import ApprovalRequest
from core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class NotificationPayload:
    title: str
    incident_id: str
    severity: str
    rca_summary: str
    confidence_score: float
    policy_decision: str
    proposed_action: str
    risk: str
    rollback_tested: bool
    approval_request_id: str | None = None


class Notifier(ABC):
    @abstractmethod
    async def send(self, payload: NotificationPayload) -> bool: ...


class TelegramNotifier(Notifier):
    def __init__(self, bot_token: str, chat_id: str, timeout: float = 10.0) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._timeout = timeout

    async def send(self, payload: NotificationPayload) -> bool:
        text = self._format(payload)
        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json={"chat_id": self._chat_id, "text": text, "parse_mode": "HTML"})
                resp.raise_for_status()
                logger.info("telegram_notification_sent", incident_id=payload.incident_id)
                return True
        except Exception as e:
            logger.error("telegram_notification_failed", error=str(e))
            return False

    def _format(self, p: NotificationPayload) -> str:
        rollback = "YES" if p.rollback_tested else "NO"
        return (
            f"<b>{p.title}</b>\n"
            f"Incident: <code>{p.incident_id}</code>\n"
            f"Severity: {p.severity}\n"
            f"RCA: {p.rca_summary}\n"
            f"Confidence: {p.confidence_score:.0%}\n"
            f"Policy: {p.policy_decision}\n"
            f"Action: {p.proposed_action}\n"
            f"Risk: {p.risk} | Rollback tested: {rollback}\n"
            + (f"Approval ID: <code>{p.approval_request_id}</code>" if p.approval_request_id else "")
        )


class WebhookNotifier(Notifier):
    def __init__(self, webhook_url: str, timeout: float = 10.0) -> None:
        self._url = webhook_url
        self._timeout = timeout

    async def send(self, payload: NotificationPayload) -> bool:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(self._url, json=payload.__dict__)
                resp.raise_for_status()
                logger.info("webhook_notification_sent", incident_id=payload.incident_id)
                return True
        except Exception as e:
            logger.error("webhook_notification_failed", error=str(e))
            return False
