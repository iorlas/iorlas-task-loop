"""Process-wide run budgets enforced by child timeouts and bounded waits without sending signals.

One engine runs in a process; its check threads share the budgets. Nested scopes can only shorten a timeout.
"""
import threading
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import overload

from tlkernel.deadline import DeadlineExpired


@dataclass(frozen=True, eq=False)
class Budget:
    end: float
    scope: str


_ACTIVE: list[Budget] = []
_LOCK = threading.RLock()


@overload
def remaining(seconds: float) -> float: ...


@overload
def remaining(seconds: None) -> float | None: ...


def remaining(seconds: float | None) -> float | None:
    """Clamp an operation's timeout to the earliest run budget, including on check threads."""
    with _LOCK:
        budget = min(_ACTIVE, key=lambda b: b.end) if _ACTIVE else None
    if budget is None:
        return seconds
    left = budget.end - time.monotonic()
    if left <= 0:
        raise DeadlineExpired(budget.scope)
    return left if seconds is None else min(seconds, left)


def check() -> None:
    """A safe point after work or a timeout: propagate the budget's typed stop before any retry."""
    remaining(None)


def wait[T](seconds: float, waiter: Callable[[float], T]) -> T:
    """Give an in-process wait its bounded timeout, then check before the caller can retry."""
    result = waiter(remaining(seconds))
    check()
    return result


@contextmanager
def deadline(seconds: float, scope: str) -> Generator[None]:
    """Install a budget until work unwinds. Process and wait seams enforce it while work runs."""
    budget = Budget(time.monotonic() + seconds, scope)
    with _LOCK:
        _ACTIVE.append(budget)
    try:
        check()
        yield
        check()
    finally:
        with _LOCK:
            _ACTIVE.remove(budget)
