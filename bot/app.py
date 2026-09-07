"""Telegram bot entry point.

Run modes:
  - polling (development): python -m bot.app
  - webhook (production): set TELEGRAM_WEBHOOK_URL in .env, bot registers itself
"""

import asyncio
import os

from telegram.ext import ApplicationBuilder, CommandHandler

from bot.handlers import (
    cmd_alert,
    cmd_approve,
    cmd_autonomy,
    cmd_deny,
    cmd_incident,
    cmd_pending,
    cmd_pipeline,
    cmd_start,
    cmd_status,
)
from core.logging import configure_logging, get_logger

logger = get_logger(__name__)


def build_application(token: str):
    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("alert", cmd_alert))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("incident", cmd_incident))
    app.add_handler(CommandHandler("pending", cmd_pending))
    app.add_handler(CommandHandler("approve", cmd_approve))
    app.add_handler(CommandHandler("deny", cmd_deny))
    app.add_handler(CommandHandler("pipeline", cmd_pipeline))
    app.add_handler(CommandHandler("autonomy", cmd_autonomy))
    return app


def main() -> None:
    configure_logging(log_level="INFO", log_format="console")
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set in environment")

    logger.info("telegram_bot_starting", mode="polling")
    app = build_application(token)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
