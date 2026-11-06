"""Capped exponential backoff with symmetric jitter."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

_MAX_EXPONENT = 63  # a long outage must not overflow the float


def backoff(base: float, cap: float, attempt: int, rand: Callable[[], float], jitter: float = 0.2) -> float:
    """Seconds to wait before attempt `attempt` (0-based): `base * 2**attempt` capped at `cap`, then scaled by 1±`jitter`.

    `rand` returns [0, 1): 0 gives the low end, 1 the high end. The cap applies before the jitter.
    """
    raw = min(base * 2 ** min(max(attempt, 0), _MAX_EXPONENT), cap)
    return raw * (1 - jitter + 2 * jitter * rand())
