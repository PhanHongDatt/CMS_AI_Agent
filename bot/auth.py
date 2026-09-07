"""Telegram bot authorization — whitelist-based user access control."""

import os
from functools import wraps
from typing import Callable

from telegram import Update
from telegram.ext import ContextTypes

from core.logging import get_logger

logger = get_logger(__name__)


def _get_allowed_users() -> set[str]:
    """Parse TELEGRAM_ALLOWED_USERS env var (comma-separated usernames or IDs)."""
    raw = os.getenv("TELEGRAM_ALLOWED_USERS", "")
    if not raw.strip():
        return set()
    return {u.strip().lstrip("@").lower() for u in raw.split(",") if u.strip()}


def require_auth(handler: Callable) -> Callable:
    """Decorator: reject commands from users not in TELEGRAM_ALLOWED_USERS.

    If TELEGRAM_ALLOWED_USERS is empty, all users are allowed (open mode).
    """
    @wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        allowed = _get_allowed_users()
        if not allowed:
            return await handler(update, context)

        user = update.effective_user
        if user is None:
            return

        username = (user.username or "").lower()
        user_id = str(user.id)

        if username in allowed or user_id in allowed:
            return await handler(update, context)

        logger.warning(
            "bot_unauthorized_access",
            user_id=user_id,
            username=username,
        )
        await update.message.reply_text("Unauthorized. Contact the platform admin.")

    return wrapper
