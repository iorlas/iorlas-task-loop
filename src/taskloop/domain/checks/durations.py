"""What a command costs: the median of its last runs. Pure; the history file is a store."""
import statistics
from typing import Final

from taskloop.contracts.checks import Duration, Durations
from taskloop.domain.checks.names import norm

CHEAP_S: Final = 5.0  # a median under this counts as free: sub-second noise never reorders a round
KEEP_RUNS: Final = 9  # durations kept per command


def _by_step(history: Durations) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for r in history.rows:
        out.setdefault(r.step, []).append(r.exec_seconds or 0.0)
    return out


def expected_secs(cmd: str, history: Durations) -> float:
    """Median of earlier runs of the command; unknown = 0 (cheap), and anything under CHEAP_S is 0 too."""
    runs = _by_step(history).get(norm(cmd))
    s = statistics.median(runs) if runs else 0.0
    return 0.0 if s < CHEAP_S else s


def merged(history: Durations, rows: list[Duration]) -> Durations:
    """The history with `rows` added (their step normalised), the last KEEP_RUNS of each command kept."""
    kept: dict[str, list[Duration]] = {}
    for r in [*history.rows, *(r.replace(step=norm(r.step), exec_seconds=round(r.exec_seconds or 0.0, 1)) for r in rows)]:
        kept.setdefault(r.step, []).append(r)
    return Durations(rows=[r for rs in kept.values() for r in rs[-KEEP_RUNS:]])


def seconds(history: Durations) -> dict[str, float]:
    """{normalised cmd: seconds}: the longest of the runs that passed (only a pass is recorded)."""
    return {cmd: max(runs) for cmd, runs in _by_step(history).items()}
