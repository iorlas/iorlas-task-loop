"""What a command costs: the median of its last runs. Pure; the history file is a store."""
import statistics

from taskloop.contracts.checks import Durations
from taskloop.domain.checks.names import norm

CHEAP_S = 5.0  # a median under this counts as free: sub-second noise never reorders a round
KEEP_RUNS = 9  # durations kept per command


def expected_secs(cmd: str, history: Durations) -> float:
    """Median of earlier runs of the command; unknown = 0 (cheap), and anything under CHEAP_S is 0 too."""
    runs = history.runs.get(norm(cmd))
    s = statistics.median(runs) if runs else 0.0
    return 0.0 if s < CHEAP_S else s


def merged(history: Durations, runs: list[tuple[str, float]]) -> Durations:
    """The history with [(cmd, secs)] added, the last KEEP_RUNS of each command kept."""
    data = {k: list(v) for k, v in history.runs.items()}
    for cmd, secs in runs:
        data.setdefault(norm(cmd), []).append(round(float(secs), 1))
    return Durations(runs={k: v[-KEEP_RUNS:] for k, v in data.items()})


def seconds(history: Durations) -> dict[str, float]:
    """{normalised cmd: seconds}: the longest of the runs that passed (only a pass is recorded)."""
    return {cmd: max(runs) for cmd, runs in history.runs.items() if runs}
