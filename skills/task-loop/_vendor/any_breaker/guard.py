"""The guard: run a call under a key, turn its outcome into a counted fact.

A breaker wrapped around code that never raises is inert. `judge` reads the *result* as well as the error, so a bad return value
(an error page, a blocked status) counts the same as an exception.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from any_breaker.fact import Fact

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from any_breaker.breaker import View
    from any_breaker.ledger import Ledger


class BreakerOpenError(Exception):
    def __init__(self, key: str, view: View) -> None:
        super().__init__(f"breaker open for {key!r} until {view.until}")
        self.key = key
        self.view = view


class Guard[T]:
    """`judge(result, error)` returns a failure kind, OK, or None for "not counted" (the caller's fault, a network drop).
    The error, when there was one, is re-raised after it is recorded; the result is returned even when judged a failure."""

    def __init__(
        self,
        ledger: Ledger,
        key: str,
        call: Callable[..., Awaitable[T]],
        judge: Callable[[T | None, Exception | None], str | None],
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.ledger, self.key, self.call, self.judge, self.clock = ledger, key, call, judge, clock

    async def __call__(self, *args: object, source: str | None = None, **kwargs: object) -> T:
        view = self.ledger.allow(self.key, self.clock())
        if not view.usable:
            raise BreakerOpenError(self.key, view)
        result: T | None = None
        error: Exception | None = None
        try:
            result = await self.call(*args, **kwargs)
        except Exception as exc:
            error = exc
        kind = self.judge(result, error)
        if kind is not None:
            note = str(error) if error else ""
            self.ledger.record(Fact(kind, self.clock(), self.key, source=source, note=note))
        if error is not None:
            raise error
        return result  # type: ignore[return-value]  # error is None here, so the call returned a T
