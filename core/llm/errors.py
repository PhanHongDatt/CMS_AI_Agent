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
