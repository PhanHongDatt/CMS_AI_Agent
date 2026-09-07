"""Gate G1: Circuit breaker tests."""

import time

import pytest

from core.llm.circuit_breaker import CircuitBreaker, CircuitState
from core.llm.errors import LLMCircuitOpenError


class TestCircuitBreaker:
    def test_starts_closed(self):
        cb = CircuitBreaker("test")
        assert cb.state == CircuitState.CLOSED

    def test_allow_request_when_closed(self):
        cb = CircuitBreaker("test")
        cb.allow_request()  # should not raise

    def test_opens_after_failure_threshold(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_rejects_when_open(self):
        cb = CircuitBreaker("test", failure_threshold=1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        with pytest.raises(LLMCircuitOpenError):
            cb.allow_request()

    def test_transitions_to_half_open_after_timeout(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout_seconds=0.05)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.1)
        assert cb.state == CircuitState.HALF_OPEN

    def test_closes_after_success_in_half_open(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout_seconds=0.05)
        cb.record_failure()
        time.sleep(0.1)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_reopens_on_failure_in_half_open(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout_seconds=0.05)
        cb.record_failure()
        time.sleep(0.1)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED  # not yet at threshold
