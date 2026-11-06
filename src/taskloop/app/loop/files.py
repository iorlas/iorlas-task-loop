"""The loop's files under the config dir: one LoopState per loop process, the repo's stop command, its rests, its pass log
and exit lines. A torn or foreign-version file reads as absent; the stores do that."""
import contextlib
import json
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from taskloop.adapters.locks import hold_path
from taskloop.app.loop import exits
from taskloop.contracts import paths
from taskloop.contracts.enums import LockWhat
from taskloop.contracts.loop import LoopCommand, LoopState, LoopTarget, Rest, StopRequest
from taskloop.contracts.looprows import DIED, KvDoc, LoopRows
from taskloop.contracts.run import LoopLogLine
from taskloop.contracts.stores import LoopLog, Page

StopMode = Literal["now", "after", ""]
EXIT_REASONS = (
    "drained", "until", "max_beads", "stop_request", "signal", "storm", "crash", "profile_ahead",
    "low_disk", "system_exit", "lost",
)


def append_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


class LoopFiles:
    def __init__(self, cfg: paths.ConfigDir, key: str, pid_alive: Callable[[int], bool], now: Callable[[], float] = time.time) -> None:
        self.cfg, self.key, self.pid_alive, self.now = cfg, key, pid_alive, now

    # ---- one state per loop process: a `lease` row in factory.db -------------------
    def rows(self) -> LoopRows:
        return LoopRows(self.cfg, self.key)

    def write(self, st: LoopState) -> None:
        self.rows().put(st)

    def read(self, pid: int) -> LoopState | None:
        return self.rows().get(pid)

    def remove(self, pid: int) -> None:
        """A row that cannot be deleted (no disk, a locked database) stays: the next `live()` finds its pid dead and records it."""
        with contextlib.suppress(OSError, sqlite3.Error):
            self.rows().delete(pid)

    def runs(self) -> Path:
        d = self.cfg.loop_runs(self.key)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def live(self, but: int | None = None) -> list[LoopState]:
        """The repo's live loops (`but`: leave this pid out), oldest first. A dead loop's row is kept as evidence (renamed `died-`)."""
        out: list[LoopState] = []
        for st in self.rows().rows(""):
            if not self.pid_alive(st.pid):
                self.record_dead(st)
                self.rows().mark_died(st.pid)
            elif st.pid != but:
                out.append(st)
        return sorted(out, key=lambda st: st.started)

    def record_dead(self, st: LoopState, reason: str = "lost",
                    detail: str = "process disappeared without an exit record; cause unknown") -> None:
        directory = self.cfg.loop_runs(self.key)
        recorded = exits.rows(directory / "factory.log")
        if not any(rec.get("pid") == st.pid and rec.get("started") == st.started for rec in recorded):
            exits.record(directory, {"v": 1, "pid": st.pid, "started": st.started, "repo": st.repo, "t": self.now(),
                                     "reason": reason, "detail": detail})

    def died(self) -> list[LoopState]:
        return [*self.rows().rows(DIED)]

    # ---- the stop command ------------------------------------------------------------------------------------------
    def lock(self) -> contextlib.AbstractContextManager[object]:
        return hold_path(self.cfg.lock_record(LockWhat.LOOP.value, self.key), "loop", what=LockWhat.LOOP)

    def command(self) -> KvDoc[LoopCommand]:
        return KvDoc(self.rows(), f"loop-command:{self.key}", LoopCommand)

    def rest_doc(self) -> KvDoc[Rest]:
        return KvDoc(self.rows(), f"loop-rest:{self.key}", Rest)

    def stop_for(self, pid: int, started: float) -> StopMode:
        """What the repo's command says to the loop (`pid`, `started`): a loop the command does not name (one started later, even on
        the same pid) ignores it."""
        cmd = self.command().get()
        if cmd is None or LoopTarget(pid=pid, started=started) not in cmd.targets:
            return ""
        return "now" if cmd.action == "stop_now" else "after" if cmd.action == "stop_after_current" else ""

    def request_stop(self, now_flag: bool, by: str) -> list[LoopState]:
        """Every live loop of the repo stops after its bead, or now. The loops it reaches; none: nothing is written."""
        with self.lock():
            loops = self.live()
            if loops:
                self.command().write(LoopCommand(action="stop_now" if now_flag else "stop_after_current", by=by, t=self.now(),
                                                 targets=[LoopTarget(pid=st.pid, started=st.started) for st in loops]))
        return loops

    def clean_command(self) -> None:
        """Caller holds the lock. The command goes when no live loop it names is left."""
        cmd = self.command().get()
        if cmd is not None and not any(LoopTarget(pid=st.pid, started=st.started) in cmd.targets for st in self.live()):
            self.command().delete()

    @staticmethod
    def stop_request(mode: StopMode, by: str, t: float) -> StopRequest | None:
        return StopRequest(kind="now" if mode == "now" else "after_current", by=by, t=t) if mode else None

    # ---- rests, the pass log, exits ------------------------------------------------------------------------------
    def rests(self) -> dict[str, float]:
        """{bead: when it may run again}, shared by every loop on the repo."""
        doc = self.rest_doc().get()
        return {b: t for b, t in (doc.beads if doc else {}).items() if t > self.now()}

    def rest_bead(self, bead: str, until: float) -> None:
        with self.lock():
            rests = self.rests()
            rests[bead] = until
            self.rest_doc().write(Rest(beads=rests))

    def log(self) -> LoopLog:
        return LoopLog(self.cfg, self.key)

    def log_line(self, row: LoopLogLine) -> None:
        self.log().append(row)

    def log_rows(self, last: int) -> Page[LoopLogLine]:
        """The last `last` lines of the loop's log; a line that is not this version's is skipped and counted (Page.skipped)."""
        return self.log().tail(last)

    def write_exit(self, rec: dict[str, object]) -> None:
        exits.record(self.cfg.loop_runs(self.key), rec)

    def last_exit(self) -> dict[str, object]:
        try:
            return json.loads((self.runs() / "exits.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        except (OSError, ValueError, IndexError):
            return {}

