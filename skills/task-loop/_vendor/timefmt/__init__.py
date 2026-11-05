"""timefmt — human strings for durations, spans and counts, so they read the same everywhere.

**Stop hand-formatting durations.** ``fmt_dur(ms)`` is the single place a
millisecond count becomes a human string: sub-second stays integer milliseconds,
low seconds carry one decimal, whole seconds drop the decimal, and a minute or
more renders ``{m}m{ss}s``. The unit tracks the magnitude, so no reading wastes
precision and every duration in a codebase looks alike.

``fmt_span(seconds)`` is the coarse form for a wait or an age (``"2d5h"``, ``"3h07m"``, ``"12m"``),
``fmt_until(when)`` the same toward a moment (``"now"`` once it has passed), and
``human_count(n)`` a magnitude-matched count (``"950"``, ``"12k"``, ``"1.5M"``).

``parse_until(value, now)`` and ``to_epoch(value)`` are the way back from text: ``"+90m"`` / ``"+2h"`` /
``"+3d"``, epoch seconds, epoch milliseconds or an ISO time in, epoch seconds out (``None`` when unparsable).

Zero-dependency and domain-free — number in, string out; the *policy* for where a
duration appears lives above this primitive.
"""

from __future__ import annotations

import math
import time
from datetime import datetime

__all__ = ["fmt_dur", "fmt_span", "fmt_until", "human_count", "parse_until", "to_epoch"]

_MINUTE = 60
_HOUR = 3600
_DAY = 86400
_MS_THRESHOLD = 1e11  # above this a bare number is epoch milliseconds (1e11 s is year 5138)
_UNIT_SECONDS = {"m": _MINUTE, "h": _HOUR, "d": _DAY}


def fmt_dur(ms: int) -> str:
    """Format ``ms`` (integer milliseconds) per the four-tier rule.

    Args:
        ms: A duration in whole milliseconds.

    Returns:
        A magnitude-matched string:

        - ``< 1000`` -> ``"{ms}ms"`` (integer, never ``"0.0s"`` for zero)
        - ``1000 <= ms < 7000`` -> ``"{s:.1f}s"`` (one decimal)
        - ``7000 <= ms < 60_000`` -> ``"{s}s"`` (integer)
        - ``>= 60_000`` -> ``"{m}m{s:02d}s"``
    """
    if ms < 1000:
        return f"{ms}ms"
    if ms < 7000:
        return f"{ms / 1000:.1f}s"
    if ms < 60_000:
        return f"{ms // 1000}s"
    minutes, sec = divmod(ms // 1000, 60)
    return f"{minutes}m{sec:02d}s"


def fmt_span(seconds: float) -> str:
    """Format a span of ``seconds`` coarsely, in days, hours and minutes (seconds are dropped).

    - ``>= 1 day`` -> ``"{d}d{h}h"``
    - ``>= 1 hour`` -> ``"{h}h{mm}m"``
    - otherwise -> ``"{m}m"`` (``"0m"`` under a minute)

    A negative span reads as zero.
    """
    whole = max(int(seconds), 0)
    days, rest = divmod(whole, _DAY)
    hours, rest = divmod(rest, _HOUR)
    minutes = rest // _MINUTE
    if days:
        return f"{days}d{hours}h"
    if hours:
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m"


def fmt_until(when: float, *, now: float | None = None) -> str:
    """Format the span from ``now`` (default: the current time) to ``when``, both epoch seconds.

    ``"now"`` when ``when`` is at or past ``now`` is not ahead — including a moment under a
    second away; otherwise :func:`fmt_span` of the wait.
    """
    remaining = when - (time.time() if now is None else now)
    if int(remaining) <= 0:
        return "now"
    return fmt_span(remaining)


def human_count(n: float) -> str:
    """Format a count by magnitude: ``< 1000`` the integer, ``< 1M`` whole thousands, else millions to 1 decimal.

    ``950 -> "950"``, ``1500 -> "2k"``, ``12_400 -> "12k"``, ``1_500_000 -> "1.5M"``. A negative
    count keeps its sign.
    """
    sign = "-" if n < 0 else ""
    mag = abs(n)
    thousands = round(mag / 1e3)
    if mag >= 1e6 or thousands >= 1000:
        return f"{sign}{mag / 1e6:.1f}M"
    if mag >= 1e3:
        return f"{sign}{thousands}k"
    return f"{sign}{int(mag)}"


def to_epoch(value: object) -> float | None:
    """Normalise ``value`` to epoch seconds: a number (seconds, or milliseconds above 1e11) or an ISO string.

    ``None``, ``""``, a bool, a non-finite number and anything unparsable give ``None``. A trailing
    ``Z`` reads as UTC; an ISO time without an offset reads as local time.
    """
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            return None
        return number / 1000.0 if number > _MS_THRESHOLD else number
    try:
        return datetime.fromisoformat(str(value).strip()).timestamp()
    except ValueError:
        return None


def parse_until(value: object, now: float) -> float | None:
    """Resolve a deadline to epoch seconds: ``"+90m"`` / ``"+2h"`` / ``"+3d"`` relative to ``now``, else :func:`to_epoch`.

    A numeric string (``"1700000000"``, ``"1700000000000"``) reads as the number. ``None`` when
    unparsable: a bad unit (``"+5x"``), no count (``"+h"``), garbage, ``None`` or ``""``.
    """
    if value is None:
        return None
    text = str(value).strip()
    if len(text) > 2 and text[0] == "+" and text[-1] in _UNIT_SECONDS and text[1:-1].isascii() and text[1:-1].isdigit():
        try:
            return now + int(text[1:-1]) * _UNIT_SECONDS[text[-1]]
        except OverflowError:
            return None
    try:
        return to_epoch(float(text))
    except ValueError:
        return to_epoch(text)
