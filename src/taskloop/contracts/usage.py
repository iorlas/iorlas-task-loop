"""Lane usage history: one row per delegate usage window each time `tl lanes` files a status snapshot, and the projection of a
window's use at its reset from the recent rows. The window name is kept as delegate printed it (the contract types it as a free
string): this module never reads a name's meaning, it only groups rows by it."""
from typing import ClassVar, Final

from taskloop.contracts.codec import record
from taskloop.contracts.snapshots import StatusSnapshot

USAGE_KEEP_S: Final = 30 * 86400  # a row older than this is pruned; the only way a row leaves the file
FORECAST_ROWS: Final = 12  # the projection fits the last this many rows of the current window
RESET_JITTER_S: Final = 600  # two rows whose resets_at differ by more are of two windows


@record
class UsageRow:
    """usage-history.jsonl: one window of one lane as the snapshot filed at `at` (delegate's clock) saw it."""

    V: ClassVar[int] = 1
    at: float
    lane: str
    window: str
    used_pct: float
    resets_at: float | None = None


def rows_of(snap: StatusSnapshot) -> list[UsageRow]:
    """The rows a snapshot adds: each window that reports a use (an unknown use is not a row)."""
    return [UsageRow(at=snap.at, lane=ln.id, window=w.name, used_pct=w.used_pct, resets_at=w.resets_at)
            for ln in snap.lanes for w in ln.windows if w.used_pct is not None]


def current_window(rows: list[UsageRow]) -> list[UsageRow]:
    """The newest run of rows of one series that is one window: same reset time (within RESET_JITTER_S) and use never falling
    (a fall is a reset). Oldest first, at most FORECAST_ROWS."""
    rs = sorted(rows, key=lambda r: r.at)
    if not rs:
        return []
    last = rs[-1]
    out = [last]
    for r in reversed(rs[:-1]):
        same = (r.resets_at is None) == (last.resets_at is None) and (
            last.resets_at is None or (r.resets_at is not None and abs(r.resets_at - last.resets_at) <= RESET_JITTER_S))
        if not same or r.used_pct > out[-1].used_pct or len(out) >= FORECAST_ROWS:
            break
        out.append(r)
    return out[::-1]


def forecast(rows: list[UsageRow], now: float) -> float | None:
    """used_pct at the window's reset: least squares of used_pct on time over the current window's last FORECAST_ROWS rows, read at
    `resets_at`, kept between the newest use and 100. None with fewer than 2 rows, rows all at one instant, no reset time, or a
    reset already past."""
    win = current_window(rows)
    reset = win[-1].resets_at if win else None
    if len(win) < 2 or reset is None or reset <= now:
        return None
    n = len(win)
    mt, mu = sum(r.at for r in win) / n, sum(r.used_pct for r in win) / n
    var = sum((r.at - mt) ** 2 for r in win)
    if var == 0:
        return None
    slope = sum((r.at - mt) * (r.used_pct - mu) for r in win) / var
    return min(100.0, max(win[-1].used_pct, mu + slope * (reset - mt)))
