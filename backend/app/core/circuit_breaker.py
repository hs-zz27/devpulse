from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Literal

import httpx

CircuitBreakerState = Literal["closed", "open", "half_open"]


class CircuitBreakerOpenError(Exception):
    def __init__(self, message: str = "Circuit breaker is open"):
        super().__init__(message)


class CircuitBreaker:
    def __init__(
        self,
        consecutive_failure_threshold: int = 3,
        recovery_timeout_seconds: int = 60,
    ) -> None:
        self.state: CircuitBreakerState = "closed"
        self.consecutive_failures = 0
        self.recovery_timeout = timedelta(seconds=recovery_timeout_seconds)
        self.opened_at: datetime | None = None
        self.threshold = consecutive_failure_threshold
        self.last_attempt_was_failure = False

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _cooldown_has_passed(self) -> bool:
        if self.opened_at is None:
            return True

        elapsed = self._now() - self.opened_at
        return elapsed >= self.recovery_timeout

    def _record_success(self) -> None:
        self.consecutive_failures = 0
        self.opened_at = None
        self.state = "closed"
        self.last_attempt_was_failure = False

    def _record_failure(self) -> None:
        if self.last_attempt_was_failure:
            self.consecutive_failures += 1
        else:
            self.consecutive_failures = 1

        if self.consecutive_failures >= self.threshold:
            self.state = "open"
            self.opened_at = self._now()

        self.last_attempt_was_failure = True

    def _should_count_failure(self, exc: Exception) -> bool:
        if (
            isinstance(exc, httpx.TimeoutException)
            or isinstance(exc, httpx.ConnectError)
            or isinstance(exc, httpx.NetworkError)
        ):
            return True

        if isinstance(exc, httpx.HTTPStatusError):
            code = exc.response.status_code
            if code >= 500:
                return True
            if code == 429:
                return True

        return False

    async def call(
        self, func: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any
    ) -> Any:
        if self.state == "open":
            if self._cooldown_has_passed():
                self.state = "half_open"
            else:
                raise CircuitBreakerOpenError()

        try:
            result = await func(*args, **kwargs)
        except Exception as exc:
            if self._should_count_failure(exc):
                self._record_failure()
            raise

        self._record_success()
        return result


github_circuit_breaker = CircuitBreaker(
    consecutive_failure_threshold=5, recovery_timeout_seconds=60
)
