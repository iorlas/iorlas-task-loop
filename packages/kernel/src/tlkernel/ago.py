"""How long ago, for every line that says it: timefmt's span (12m, 3h07m, 2d5h) and "never" for a time that was not recorded."""

import timefmt


def ago(now: float, t: float) -> str:
    return "never" if t <= 0 else f"{timefmt.fmt_span(now - t)} ago"
