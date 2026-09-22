import re


class LLMError(Exception):
    """Base class for all LLM gateway errors."""


class LLMUnavailableError(LLMError):
    """All configured providers are unavailable."""


class LLMTimeoutError(LLMError):
    """Request exceeded the configured timeout."""


class LLMRateLimitError(LLMError):
    """Provider rate limit hit — eligible for retry."""


class LLMAuthError(LLMError):
    """Authentication failure — do not retry."""


class LLMInvalidRequestError(LLMError):
    """Malformed request — do not retry."""


class LLMBudgetExceededError(LLMError):
    """Cost budget (per-incident or daily) exhausted."""


class LLMCircuitOpenError(LLMError):
    """Circuit breaker is open for this provider."""


# Credential shapes to redact: Bearer headers plus OpenAI/Anthropic/Google keys.
# An HTTP client error can embed the whole Authorization header (seen with a
# malformed key: "Illegal header value b'Bearer sk-...'"), so provider
# exception text is never safe to log verbatim.
_SECRET_PATTERNS = [
    re.compile(r"Bearer\s+[A-Za-z0-9_\-.]{8,}", re.IGNORECASE),
    re.compile(r"\b(?:sk|rk)-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\bAIza[A-Za-z0-9_\-]{10,}"),
]


def sanitize_llm_error(exc: BaseException) -> str:
    """Return exception text with any credential-looking substring redacted."""
    text = f"{type(exc).__name__}: {exc}"
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("<REDACTED>", text)
    return text
