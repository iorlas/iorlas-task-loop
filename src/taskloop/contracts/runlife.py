"""How long a run lives, from its manifest alone: the one liveness rule every reader shares. A run's state is RECORDED by its writer
(contracts/run.py RunState, runs/<run>/manifest.json), never inferred from a log gap: the engine marks it running on every
heartbeat and terminal on every exit; `reconcile` (tl processes only) is the one writer of `lost`, `is_lost` the one decision it and the
read-only dashboard share. How long its files are kept is KEEP_DAYS, swept by `tl prune` alone."""
from collections.abc import Callable
from enum import StrEnum
from typing import Final

from taskloop.contracts.enums import Step
from taskloop.contracts.locator import RunLocator, host_name
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


def is_lost(m: RunManifest, host: str, now: float, alive: Callable[[int], bool]) -> bool:
    """The one decision: a run in a live state, of THIS host, whose heartbeat is older than STALE_AFTER and whose pid is gone, is lost.
    Pure: the writer (`reconcile`) and the dashboard's display both ask it, so what is shown is what would be written."""
    return m.state.live and m.host == host and now - m.heartbeat >= STALE_AFTER and not (m.pid > 0 and alive(m.pid))


def lost_reason(m: RunManifest, now: float) -> str:
    return f"pid {m.pid} on {m.host} is gone; last heartbeat {now - m.heartbeat:.0f} s ago while {m.state}"


def shown(m: RunManifest, now: float) -> Liveness:
    """What a reader that must not write displays: the recorded state, or LOST when the reconciler would mark it so now."""
    return Liveness.LOST if is_lost(m, host_name(), now, pid_alive) else liveness(m)


def reconcile(cfg: ConfigDir, now: float) -> list[str]:
    """WRITE `lost` for every run `is_lost` finds, once. Called only by tl processes: loop start, `tl doctor`, `tl wait`, `tl report` and
    the owner-request gate. The dashboard never calls it (it only reads: `shown`). -> the run ids marked."""
    where, host = RunLocator(cfg), host_name()
    marked: list[str] = []
    for b in where.runs():
        if is_lost(b.manifest, host, now, pid_alive):
            where.mark_lost(b.run, lost_reason(b.manifest, now))
            marked.append(b.run)
    return marked
