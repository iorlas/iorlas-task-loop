"""How long a run lives, from its typed log alone: the one liveness rule the dashboard and `tl report` share, and the one retention
the sweep and the dashboard's window share. No process is probed: a run is its records.

A run is `ended` once its log has a Close record. Without one it is `live` while its newest record is younger than CRASHED_AFTER,
and `crashed` after that (the process died without closing: kill -9, power loss). The engine guarantees the margin: while a run-task
lives, its Lease thread appends a Beat record every BEAT_EVERY seconds (taskloop.app.run.run_once), whatever the engine is doing, so a
live run is never silent for CRASHED_AFTER / 2 = 150 s; a dead one reads `crashed` within CRASHED_AFTER + one read of the log, which
is inside 2 * CRASHED_AFTER."""
from collections.abc import Sequence
from enum import StrEnum
from typing import Final

from taskloop.contracts.enums import Step
from taskloop.contracts.log import Close, EngineLog

BEAT_EVERY: Final = 60.0  # seconds between the Beat records of a live run
CRASHED_AFTER: Final = 300.0  # N: an open run whose newest record is older than this has died (5 beats missed)
RETAIN: Final = 7 * 86400  # seconds a run's log, and its .live/ folder, are kept after the last write

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
    CRASHED = "crashed"


def liveness(records: Sequence[EngineLog], now: float) -> Liveness:
    """The state of the run whose engine-log records these are. A log with no record at all reads crashed: the engine's first Beat
    lands within seconds of the start, so an empty file is a run that died before it wrote."""
    if any(isinstance(r, Close) for r in records):
        return Liveness.ENDED
    newest = max((r.t for r in records), default=0.0)
    return Liveness.LIVE if now - newest < CRASHED_AFTER else Liveness.CRASHED
