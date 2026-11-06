"""The small documents of one run that were files in its folder (pause, reexec, handoff, the prepare stamp, the once-per-run notes)
as `kv` rows `run:<run>:<name>` in factory.db, and the check durations of a repo as `kv` rows `durations:<repo key>`. An older tl's file
is adopted on first read (dual-read, never dual-write). What stays in the run folder is evidence that people and tools read as files:
the engine log, `plan.json`, `engine-checks*.json`, the live folder, the push logs."""
import time
from typing import ClassVar, final

from taskloop.contracts.checks import Durations
from taskloop.contracts.docrows import RowDoc, RowDocs, singleton
from taskloop.contracts.looprows import LoopRows
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.run import HandoffMirror, RunCounters
from taskloop.contracts.wire import Rec

RUN = "run:"


@final
class PrepareStamp(Rec):
    """What `engine.prepare` last ran against: the fingerprint of its inputs and the clock (ns) it finished at."""

    V: ClassVar[int] = 1
    fingerprint: str
    ns: int


def pause(cfg: ConfigDir, run: str) -> RowDoc[RunCounters]:
    return singleton(cfg, RunCounters, f"{RUN}{run}:pause")


def reexec(cfg: ConfigDir, run: str) -> RowDoc[RunCounters]:
    return singleton(cfg, RunCounters, f"{RUN}{run}:reexec")


def handoff(cfg: ConfigDir, run: str) -> RowDoc[HandoffMirror]:
    return singleton(cfg, HandoffMirror, f"{RUN}{run}:handoff")


def prepare_stamp(cfg: ConfigDir, run: str) -> RowDoc[PrepareStamp]:
    return singleton(cfg, PrepareStamp, f"{RUN}{run}:prepare")


def stamped(fingerprint: str) -> PrepareStamp:
    return PrepareStamp(fingerprint=fingerprint, ns=time.time_ns())


def once(cfg: ConfigDir, run: str, key: str) -> bool:
    """True the first time `key` is asked for in this run (also across engine reloads), False after: one row, inserted if absent."""
    with LoopRows(cfg, "").transaction() as con:
        return bool(con.execute("INSERT INTO kv (k, v, t) VALUES (?, '1', ?) ON CONFLICT(k) DO NOTHING",
                                (f"{RUN}{run}:once:{key}", time.time())).rowcount)


def forget(cfg: ConfigDir, run: str) -> None:
    """The run's rows go with its logs."""
    if not cfg.factory_db().exists():
        return
    with LoopRows(cfg, "").transaction() as con:
        con.execute("DELETE FROM kv WHERE k LIKE ? ESCAPE '\\'", (f"{RUN}{run.replace('%', '\\%').replace('_', '\\_')}:%",))


def durations(cfg: ConfigDir, *, quiet: bool = False) -> RowDocs[Durations]:
    return RowDocs(cfg, Durations, table="kv", key_col="k", body_col="v", prefix="durations:", quiet=quiet)
