"""How long a run lives, from its manifest alone: the one liveness rule every reader shares. A run's state is RECORDED by its writer
(contracts/run.py RunState, runs/<run>/manifest.json), never inferred from a log gap: the engine marks it running on every heartbeat and
terminal on every exit; `reconcile` is the one place that marks a run whose process is gone `lost`. How long its files are kept is
KEEP_DAYS, swept by `tl prune` alone."""
from enum import StrEnum
from typing import Final

from taskloop.contracts.enums import Step
from taskloop.contracts.locator import RunLocator
from taskloop.contracts.locks import pid_alive
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.run import RunManifest, RunState

BEAT_EVERY: Final = 60.0  # seconds between the heartbeats of a live run (the manifest's `heartbeat`)
STALE_AFTER: Final = 300.0  # a heartbeat older than this (5 missed) lets the reconciler look at the run's pid
RETAIN: Final = 7 * 86400  # seconds the dashboard and `tl report` look back; it deletes nothing (the sweep is KEEP_DAYS)
KEEP_DAYS: Final = 30  # days run data of a closed bead is kept at least (logs, check rounds, evidence); a bead not closed keeps all of it

# The stuck rule (dash-spec 2.4, 2.6), in one place: a step silent this long (no record but Beats, no worker output) is stuck, and so are
# SAME_RED rounds in a row with the same red checks. The limits sit above the engine's own stops of a silent worker (write_idle_min 25).
SILENT_LIMIT: Final[dict[Step, float]] = {
    Step.PLAN: 20 * 60.0, Step.REPLAN: 20 * 60.0, Step.WRITE: 30 * 60.0, Step.CHECKS: 45 * 60.0, Step.REVIEW: 20 * 60.0,
    Step.VERIFY: 20 * 60.0, Step.LOOK: 20 * 60.0, Step.GATE: 45 * 60.0, Step.LAND: 20 * 60.0,
}
SILENT_DEFAULT: Final = 30 * 60.0  # a step the table does not name (reset, close, reflect)
SAME_RED: Final = 3


def silent_limit(step: str) -> float:
    """The seconds of silence after which `step` is stuck."""
    try:
        return SILENT_LIMIT.get(Step(step), SILENT_DEFAULT)
    except ValueError:
        return SILENT_DEFAULT


class Liveness(StrEnum):
    LIVE = "live"
    ENDED = "ended"
    LOST = "lost"


def liveness(m: RunManifest) -> Liveness:
    """The recorded state of a run, in the readers' three words."""
    return Liveness.LIVE if m.state.live else Liveness.LOST if m.state is RunState.LOST else Liveness.ENDED


def reconcile(cfg: ConfigDir, now: float) -> list[str]:
    """Mark the runs of this host whose heartbeat is stale and whose process is dead `lost`, once. Called at loop start, by `tl doctor`
    and by the dashboard's read of the runs. -> the run ids marked."""
    return RunLocator(cfg).reconcile(now, pid_alive, STALE_AFTER)
