import time
from enum import Enum

from core.llm.errors import LLMCircuitOpenError


class CircuitState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    """Per-provider circuit breaker.

    CLOSED  → normal operation
    OPEN    → reject immediately after failure_threshold consecutive failures
    HALF_OPEN → allow one probe after recovery_timeout_seconds
    """

    def __init__(
        self,
        provider: str,
        failure_threshold: int = 3,
        recovery_timeout_seconds: float = 60.0,
    ) -> None:
        self.provider = provider
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at: float | None = None

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.monotonic() - (self._opened_at or 0) >= self.recovery_timeout_seconds:
                self._state = CircuitState.HALF_OPEN
        return self._state

    def allow_request(self) -> None:
        if self.state == CircuitState.OPEN:
            raise LLMCircuitOpenError(
                f"Circuit breaker OPEN for provider '{self.provider}'. "
                f"Retry after {self.recovery_timeout_seconds}s."
            )

    def record_success(self) -> None:
        self._failure_count = 0
        self._state = CircuitState.CLOSED
        self._opened_at = None

    def record_failure(self) -> None:
        self._failure_count += 1
        if self._state == CircuitState.HALF_OPEN or self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            self._opened_at = time.monotonic()
