"""Third-party HTTP loggers must not leak credentials; RCA must demand real IDs."""

import logging

from core.logging import configure_logging
from core.rca.prompts import RCA_SYSTEM_PROMPT


def test_http_client_loggers_are_quiet():
    """httpx logs the full request URL at INFO, which includes the Telegram bot token."""
    configure_logging()
    for name in ("httpx", "httpcore", "openai", "anthropic"):
        assert logging.getLogger(name).level >= logging.WARNING, name


def test_prompt_forbids_index_style_evidence_ids():
    """The model returned "3" instead of a UUID, so the RCA was rejected."""
    text = RCA_SYSTEM_PROMPT.lower()
    assert "verbatim" in text
    assert "index" in text or "position" in text
