"""The owner's hold on a bead, read off its metadata (the keys the `hold` verb writes, app/asks/intake.py)."""
from collections.abc import Mapping
from typing import Final

HOLD: Final = "owner_hold"
HOLD_UNTIL: Final = "owner_hold_until"  # epoch seconds; absent = until released


def held(meta: Mapping[str, str], now: float) -> str:
    """Who holds the bead ("" when nobody): a hold with an `until` ends when that time passes, one without lasts until released."""
    who = (meta.get(HOLD) or "")
    until = float(meta.get(HOLD_UNTIL) or 0)
    return who if who and (not until or until > now) else ""
