"""The loop's files under the config dir: one LoopState per loop process, the repo's stop command, its rests, its pass log
and exit lines. A torn or foreign-version file reads as absent; the stores do that."""
import contextlib
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from taskloop.adapters.locks import hold_path
from taskloop.contracts import paths
from taskloop.contracts.enums import LockWhat
from taskloop.contracts.loop import LoopCommand, LoopState, Rest, StopRequest
from taskloop.contracts.stores import JsonStore

StopMode = Literal["now", "after", ""]
EXIT_REASONS = ("drained", "until", "max_beads", "stop_request", "signal", "storm", "crash")


def append_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


class LoopFiles:
    def __init__(self, cfg: paths.ConfigDir, key: str, pid_alive: Callable[[int], bool], now: Callable[[], float] = time.time) -> None:
        self.cfg, self.key, self.pid_alive, self.now = cfg, key, pid_alive, now

    # ---- one state per loop process -------------------------------------------------------------------------------
    def state_file(self, pid: int) -> JsonStore[LoopState]:
        return JsonStore(self.cfg.loop_state(f"{self.key}.{pid}"), LoopState)

    def write(self, st: LoopState) -> None:
        self.state_file(st.pid).write(st)

    def read(self, pid: int) -> LoopState | None:
        return self.state_file(pid).read()

    def remove(self, pid: int) -> None:
        self.state_file(pid).delete()

    def runs(self) -> Path:
        d = self.cfg.loop_runs(self.key)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def live(self, but: int | None = None) -> list[LoopState]:
        """The repo's live loops (`but`: leave this pid out), oldest first. A dead loop's file is kept as evidence."""
        d = self.cfg.loop_state(self.key).parent
        out: list[LoopState] = []
        for f in sorted(d.glob(self.key + ".*.json")):
            if f.name.endswith(".command.json"):
                continue
            st = JsonStore(f, LoopState).read()
            if st is None:
                continue
            if not self.pid_alive(st.pid):
                with contextlib.suppress(OSError):
                    f.replace(self.runs() / f"died-{st.pid}.json")
            elif st.pid != but:
                out.append(st)
        return sorted(out, key=lambda st: st.started)

    def died(self) -> list[LoopState]:
        found = (JsonStore(f, LoopState).read() for f in self.runs().glob("died-*.json"))
        return [st for st in found if st is not None]

    # ---- the stop command ------------------------------------------------------------------------------------------
    def lock(self) -> contextlib.AbstractContextManager[object]:
        return hold_path(self.cfg.lock_record(LockWhat.LOOP.value, self.key), "loop", what=LockWhat.LOOP)

    def command(self) -> JsonStore[LoopCommand]:
        return JsonStore(self.cfg.loop_command(self.key), LoopCommand)

    def stop_for(self, pid: int) -> StopMode:
        """What the repo's command says to loop `pid`: a loop the command does not name (one started later) ignores it."""
        cmd = self.command().read()
        if cmd is None or pid not in cmd.targets:
            return ""
        return "now" if cmd.action == "stop_now" else "after" if cmd.action == "stop_after_current" else ""

    def request_stop(self, now_flag: bool, by: str) -> list[LoopState]:
        """Every live loop of the repo stops after its bead, or now. The loops it reaches; none: nothing is written."""
        with self.lock():
            loops = self.live()
            if loops:
                self.command().write(LoopCommand(action="stop_now" if now_flag else "stop_after_current", by=by, t=self.now(),
                                                 targets=[st.pid for st in loops]))
        return loops

    def clean_command(self) -> None:
        """Caller holds the lock. The command goes when no live loop it names is left."""
        cmd = self.command().read()
        if cmd is not None and not any(st.pid in cmd.targets for st in self.live()):
            self.command().delete()

    @staticmethod
    def stop_request(mode: StopMode, by: str, t: float) -> StopRequest | None:
        return StopRequest(kind="now" if mode == "now" else "after_current", by=by, t=t) if mode else None

    # ---- rests, the pass log, exits ------------------------------------------------------------------------------
    def rests(self) -> dict[str, float]:
        """{bead: when it may run again}, shared by every loop on the repo."""
        doc = JsonStore(self.cfg.loop_rest(self.key), Rest).read()
        return {b: t for b, t in (doc.beads if doc else {}).items() if t > self.now()}

    def rest_bead(self, bead: str, until: float) -> None:
        with self.lock():
            rests = self.rests()
            rests[bead] = until
            JsonStore(self.cfg.loop_rest(self.key), Rest).write(Rest(beads=rests))

    def log_line(self, row: dict[str, object]) -> None:
        append_line(self.cfg.loop_log(self.key), json.dumps(row, ensure_ascii=False))

    def log_rows(self, last: int) -> list[dict[str, object]]:
        try:
            lines = self.cfg.loop_log(self.key).read_text(encoding="utf-8").splitlines()[-last:]
        except OSError:
            return []
        rows: list[dict[str, object]] = []
        for ln in lines:
            with contextlib.suppress(ValueError):
                row = json.loads(ln)
                if isinstance(row, dict):
                    rows.append(row)
        return rows

    def write_exit(self, rec: dict[str, object]) -> None:
        append_line(self.runs() / "exits.jsonl", json.dumps(rec))

    def last_exit(self) -> dict[str, object]:
        try:
            return json.loads((self.runs() / "exits.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        except (OSError, ValueError, IndexError):
            return {}

