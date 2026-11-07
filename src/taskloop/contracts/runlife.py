"""How long a run lives, from its manifest alone: the one liveness rule every reader shares. A run's state is RECORDED by its writer
(contracts/run.py RunState, factory.db run.manifest), never inferred from a log gap: the engine marks it running on every
heartbeat and terminal on every exit; `reconcile` (tl processes only) is the one writer of `lost`, `is_lost` the one decision it and the
read-only dashboard share. How long its files are kept is KEEP_DAYS, swept by `tl prune` alone."""
from collections.abc import Callable
from enum import StrEnum
from typing import Final

from taskloop.contracts.enums import Step
from taskloop.contracts.ids import loop_key
from taskloop.contracts.locator import RunLocator, host_name
from taskloop.contracts.locks import pid_alive
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.run import RunManifest, RunState

BEAT_EVERY: Final = 60.0  # seconds between the heartbeats of a live run (the manifest's `heartbeat`)
SUSPECT_AFTER: Final = 2 * BEAT_EVERY  # a heartbeat this old with its process gone is shown SUSPECT: not running, not yet written lost
STALE_AFTER: Final = 300.0  # a heartbeat older than this (5 missed) lets the reconciler look at the run's pid
RETAIN: Final = 7 * 86400  # seconds the dashboard and `tl report` look back; it deletes nothing (the sweep is KEEP_DAYS)
KEEP_DAYS: Final = 30  # days run data of a closed bead is kept at least (logs, check rounds, evidence); a bead not closed keeps all of it

# The stuck rule (dash-spec 2.4, 2.6), in one place: a step silent this long (no record but Beats, no worker output) is stuck, and so are
# SAME_RED rounds in a row with the same red checks. The limits sit above the engine's own stops of a silent worker (write_idle_min 25).
SILENT_LIMIT: Final[dict[str, float]] = {
    Step.PLAN: 20 * 60.0, Step.REPLAN: 20 * 60.0, Step.WRITE: 30 * 60.0, Step.CHECKS: 45 * 60.0, Step.REVIEW: 20 * 60.0,
    Step.VERIFY: 20 * 60.0, Step.LOOK: 20 * 60.0, Step.GATE: 45 * 60.0, Step.LAND: 20 * 60.0,
    Step.RESET: 30 * 60.0, Step.CLOSE: 30 * 60.0, Step.REFLECT: 30 * 60.0,
    "push": 60 * 60.0,  # an internal step, not a selectable stage; includes LFS and the pre-push hook (up to 2900 s)
}
SILENT_DEFAULT: Final = 30 * 60.0  # internal steps without a dedicated limit
SAME_RED: Final = 3


def silent_limit(step: str) -> float:
    """The seconds of silence after which `step` is stuck."""
    return SILENT_LIMIT.get(step, SILENT_DEFAULT)


class Liveness(StrEnum):
    LIVE = "live"
    ENDED = "ended"
    LOST = "lost"
    SUSPECT = "suspect"  # shown only: the process is gone, the reconciler has not yet written `lost`


GONE: Final = frozenset({Liveness.LOST, Liveness.SUSPECT})  # what a reader shows as "its process is gone"


def liveness(m: RunManifest) -> Liveness:
    """The recorded state of a run, in the readers' three words."""
    return Liveness.LIVE if m.state.live else Liveness.LOST if m.state is RunState.LOST else Liveness.ENDED


def is_lost(m: RunManifest, host: str, now: float, alive: Callable[[int, str], bool]) -> bool:
    """The one decision: a run in a live state, of THIS host, whose heartbeat is older than STALE_AFTER and whose pid is gone, is lost.
    Pure: the writer (`reconcile`) and the dashboard's display both ask it, so what is shown is what would be written."""
    return m.state.live and m.host == host and now - m.heartbeat >= STALE_AFTER and not (m.pid > 0 and alive(m.pid, m.pid_start))


def suspect(m: RunManifest, host: str, now: float, alive: Callable[[int, str], bool]) -> bool:
    """A live-state run of THIS host whose heartbeat missed two beats and whose process (pid and start token) is gone: a killed engine.
    Display only, nothing is written; `is_lost` still waits STALE_AFTER."""
    return m.state.live and m.host == host and now - m.heartbeat >= SUSPECT_AFTER and not (m.pid > 0 and alive(m.pid, m.pid_start))


def lost_reason(m: RunManifest, now: float) -> str:
    return f"pid {m.pid} on {m.host} is gone; last heartbeat {now - m.heartbeat:.0f} s ago while {m.state}"


def shown(m: RunManifest, now: float) -> Liveness:
    """What a reader that must not write displays: the recorded state, LOST when the reconciler would mark it so now, or SUSPECT while
    a killed engine's heartbeat is not yet old enough for that."""
    host = host_name()
    if is_lost(m, host, now, pid_alive):
        return Liveness.LOST
    return Liveness.SUSPECT if suspect(m, host, now, pid_alive) else liveness(m)


def command_scope(cfg: ConfigDir, repo: str, bead: str, run: str, now: float) -> str:
    """Refuse an owner command before any write when its observed identities or liveness disagree."""
    bundle = RunLocator(cfg).get(run) if run else None
    if bundle is None:
        return "no run of this bead is going"
    m = bundle.manifest
    if loop_key(m.repo) != loop_key(repo) or m.bead != bead:
        return "That run does not belong to this repo and bead. Refresh before trying again."
    return "" if shown(m, now) is Liveness.LIVE else "no run of this bead is going"


def reconcile(cfg: ConfigDir, now: float) -> list[str]:
    """WRITE `lost` for every run `is_lost` finds, once. Called only by tl processes: loop start, `tl doctor`, `tl wait`, `tl report` and
    the owner-request gate. The dashboard never calls it (it only reads: `shown`). -> the run ids marked."""
    where, host = RunLocator(cfg), host_name()
    marked: list[str] = []
    for b in where.runs():
        if is_lost(b.manifest, host, now, pid_alive):
            result = where.mark_lost(b.run, lost_reason(b.manifest, now), b.manifest.heartbeat)
            if result is not None and result.won:
                marked.append(b.run)
    return marked
