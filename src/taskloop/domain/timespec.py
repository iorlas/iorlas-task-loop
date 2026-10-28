"""A time the owner types: `+2h`, `90m`, `HH:MM` (the next one), an ISO date or date-time, or epoch seconds. Pure: the caller passes now."""
from datetime import datetime, timedelta
from typing import Final

UNITS: Final = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_future(text: str, now: datetime) -> float:
    """Epoch seconds of `text`, strictly after `now`; ValueError when it says nothing or names a time already gone."""
    s = text.strip()
    if not s:
        raise ValueError("no time given")
    if s[-1:] in UNITS and s.lstrip("+")[:-1].replace(".", "", 1).isdigit():
        return now.timestamp() + float(s.lstrip("+")[:-1]) * UNITS[s[-1]]
    if s.replace(".", "", 1).isdigit() and float(s) > 10**9:
        at = float(s)
    elif len(s) <= 5 and ":" in s:
        hh, _, mm = s.partition(":")
        at_dt = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        at = (at_dt if at_dt > now else at_dt + timedelta(days=1)).timestamp()
    else:
        at_dt = datetime.fromisoformat(s)
        at = (at_dt if at_dt.tzinfo else at_dt.replace(tzinfo=now.tzinfo)).timestamp()
    if at <= now.timestamp():
        raise ValueError(f"{text!r} is already past")
    return at
