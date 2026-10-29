"""The window a report verb reads: the owner's T for --since and --until (see domain/report/matchers.py: parse_time)."""
from taskloop.domain.report import matchers

DAY_S = 86400


def window(since: str | None, until: str | None, now: float) -> tuple[float, float]:
    """(since, until) of `tl report`: --since defaults to 24 h back, --until to now."""
    return (matchers.parse_time(since, now) if since else now - DAY_S,
            matchers.parse_time(until, now, forward=True) if until else now)


def since_of(text: str | None, now: float) -> float | None:
    """`tl lost --since`: the time, or None for no limit."""
    return matchers.parse_time(text, now) if text else None


def digest_time(text: str, now: float) -> float:
    """`tl reflect digest --since/--until`: Nh back, epoch seconds, or anything a report takes."""
    return matchers.window_time(text, now)
