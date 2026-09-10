"""Shared monotonic deadline primitives for one broker request."""

from __future__ import annotations

import inspect
import math
import time
from dataclasses import dataclass
from typing import Callable, TypeVar, cast


class BrokerDeadlineExceeded(TimeoutError):
    """The broker request's absolute monotonic deadline has passed."""


Clock = Callable[[], float]
_Result = TypeVar("_Result")


@dataclass(frozen=True)
class BrokerDeadline:
    """One absolute monotonic deadline shared by every broker stage.

    Capability timestamps are wall-clock values and are converted to a duration
    exactly once by the request receiver. All later checks use only the injected
    monotonic clock, so wall-clock adjustments cannot extend a request.
    """

    expires_at: float
    monotonic_clock: Clock = time.monotonic

    def __post_init__(self) -> None:
        if (
            isinstance(self.expires_at, bool)
            or not isinstance(self.expires_at, (int, float))
            or not math.isfinite(float(self.expires_at))
        ):
            raise ValueError("deadline must be a finite monotonic timestamp")
        if not callable(self.monotonic_clock):
            raise ValueError("monotonic_clock must be callable")

    @classmethod
    def from_receipt(
        cls,
        *,
        receipt_monotonic: float,
        budget_s: float,
        monotonic_clock: Clock = time.monotonic,
    ) -> "BrokerDeadline":
        if (
            isinstance(receipt_monotonic, bool)
            or not isinstance(receipt_monotonic, (int, float))
            or not math.isfinite(float(receipt_monotonic))
        ):
            raise ValueError("receipt_monotonic must be a finite number")
        if (
            isinstance(budget_s, bool)
            or not isinstance(budget_s, (int, float))
            or not math.isfinite(float(budget_s))
            or budget_s <= 0
        ):
            raise ValueError("budget_s must be a positive finite number")
        return cls(float(receipt_monotonic) + float(budget_s), monotonic_clock)

    def remaining(self) -> float:
        """Return the current remaining budget, never a negative timeout."""
        remaining = float(self.expires_at) - float(self.monotonic_clock())
        return max(0.0, remaining)

    def check(self) -> float:
        """Fail closed if no budget remains and return the remaining seconds."""
        remaining = self.remaining()
        if remaining <= 0:
            raise BrokerDeadlineExceeded("broker deadline expired")
        return remaining


_SQLITE_DEFAULT_BUSY_TIMEOUT_S = 30.0
_SQLITE_MIN_BUSY_TIMEOUT_MS = 1


def sqlite_busy_timeout_s(deadline: BrokerDeadline | None) -> float:
    """Return a SQLite connection timeout bounded by the shared deadline."""
    if deadline is None:
        return _SQLITE_DEFAULT_BUSY_TIMEOUT_S
    return min(_SQLITE_DEFAULT_BUSY_TIMEOUT_S, deadline.check())


def configure_sqlite_busy_timeout(
    connection: object,
    deadline: BrokerDeadline | None,
) -> None:
    """Apply a deadline-bounded SQLite busy timeout to an open connection."""
    timeout_s = sqlite_busy_timeout_s(deadline)
    timeout_ms = max(
        _SQLITE_MIN_BUSY_TIMEOUT_MS,
        min(30_000, int(math.ceil(timeout_s * 1000.0))),
    )
    execute = getattr(connection, "execute")
    execute(f"PRAGMA busy_timeout = {timeout_ms}")
    if deadline is not None:
        deadline.check()


def accepts_keyword(callable_object: object, keyword: str) -> bool:
    """Return whether a dependency can receive an optional keyword argument."""
    try:
        signature = inspect.signature(cast(Callable[..., object], callable_object))
    except (TypeError, ValueError):
        return False
    parameters = signature.parameters.values()
    return keyword in signature.parameters or any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters
    )


def invoke_with_deadline(
    callable_object: Callable[..., _Result],
    /,
    *args: object,
    deadline: BrokerDeadline | None = None,
    **kwargs: object,
) -> _Result:
    """Call an injected dependency without breaking prior one-argument fakes."""
    if deadline is not None:
        deadline.check()
        if accepts_keyword(callable_object, "deadline"):
            kwargs["deadline"] = deadline
    return callable_object(*args, **kwargs)


def invoke_transport(
    transport: Callable[..., _Result],
    /,
    *args: object,
    deadline: BrokerDeadline | None = None,
    **kwargs: object,
) -> _Result:
    """Call an injected network transport with the shared remaining timeout."""
    if deadline is not None:
        remaining = deadline.check()
        if accepts_keyword(transport, "deadline"):
            kwargs["deadline"] = deadline
        if accepts_keyword(transport, "timeout_s"):
            kwargs["timeout_s"] = remaining
    result = transport(*args, **kwargs)
    if deadline is not None:
        deadline.check()
    return result


__all__ = [
    "BrokerDeadline",
    "BrokerDeadlineExceeded",
    "accepts_keyword",
    "configure_sqlite_busy_timeout",
    "invoke_transport",
    "invoke_with_deadline",
    "sqlite_busy_timeout_s",
]
