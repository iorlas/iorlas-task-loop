"""A run that goes on in another process: the counters kept across a network pause or an exec into a newer install, and the exec at a
step boundary."""
import os
import sys
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from tlkernel import log as rec
from tlkernel import rundocs
from tlkernel.env import Env
from tlkernel.envvars import EnvVar
from tlkernel.identity import Identity
from tlkernel.ids import BeadId
from tlkernel.paths import ConfigDir
from tlkernel.run import NetPause, Reexec, ReexecNote, RunCounters
from tlkernel.run_slot import RUN_SLOT
from tlkernel.runrows import RunRows
from tlkernel.wire import Open

from taskloop.app.pipeline.adapter_ports import ChildEnv, Install
from taskloop.app.pipeline.ports import Reexecs, Trail
from taskloop.app.pipeline.store_ports import ReadDoc


class Exec(BaseException):
    """Raised after a test's injected exec function returns (the real exec never does): unwinds run() without its close."""


class ReloadWrite(Protocol):
    write_rounds: list[Open]


class ReloadSteps(Protocol):
    n: int

    def end(self, outcome: str = "") -> None: ...


class ReloadBudget(Protocol):
    def restore(self, elapsed: float, waited: float) -> None: ...


class ReloadLog(Protocol):
    def note(self, text: str) -> int: ...
    def emit(self, item: rec.Reload, /) -> int: ...


class ReloadHost(Protocol):
    @property
    def t0(self) -> float: ...
    @property
    def waited(self) -> float: ...
    @property
    def cost(self) -> float: ...
    @cost.setter
    def cost(self, value: float) -> None: ...
    stats: dict[str, int]
    sessions: list[Open]
    home: ConfigDir
    run_id: str
    bead: BeadId
    wt: str
    who: Identity
    env: Env
    argv: list[str] | None
    dry: bool
    moved: bool
    newer_fn: Callable[[], tuple[str, Path] | None] | None
    exec_fn: Callable[[list[str], dict[str, str]], object] | None

    @property
    def write(self) -> ReloadWrite: ...
    @property
    def steps(self) -> ReloadSteps: ...
    @property
    def budget(self) -> ReloadBudget: ...
    @property
    def log(self) -> ReloadLog: ...
    def warn(self, text: str) -> None: ...


class Reload:
    def __init__(self, host: ReloadHost, reexecs: Reexecs, trail: Trail,
                 newer: Callable[[], tuple[str, Path] | None], slot: Callable[[], str], child_env: ChildEnv, install: Install) -> None:
        self.host = host
        self.child_env, self.install = child_env, install
        self.reexecs, self.trail, self.newer, self.slot = reexecs, trail, newer, slot

    def counters(self) -> RunCounters:
        host = self.host
        return RunCounters(elapsed=time.time() - host.t0, waited=host.waited, cost=host.cost, stats=dict(host.stats),
                           sessions=list(host.sessions),
                           write_rounds=list(host.write.write_rounds), node_n=host.steps.n)

    def restore_run(self, doc: ReadDoc[RunCounters]) -> None:
        """The counters of the run that exec'd (RunFiles.reexec) or paused for the network (RunFiles.pause), so the run's cost,
        time and trace go on across the move; the time between is neither spent nor waited."""
        host = self.host
        c = doc.get()
        if c is None:
            return
        host.budget.restore(c.elapsed, c.waited)
        host.cost = c.cost
        host.stats.update(c.stats)
        host.sessions[:] = c.sessions
        host.write.write_rounds = list(c.write_rounds)
        host.steps.n = c.node_n

    def carry_done_memo(self, paused: Path) -> None:
        """The answers the paused run already took go on under this run's id: no finished call is asked again."""
        with RunRows(self.host.home).transaction() as con:
            con.execute("INSERT INTO step (run,key,try,attempt,status,started,ended,input_digest,result,fingerprint,calls) "
                        "SELECT ?,key,try,attempt,status,started,ended,input_digest,result,fingerprint,calls "
                        "FROM step WHERE run=? AND status='done' ON CONFLICT(run,key,try) DO NOTHING",
                        (self.host.run_id, paused.name))

    def save_net_pause(self) -> None:
        """The run paused for the network: keep its counters for the next run of this bead. Its terminal answer stays immutable;
        the new run keeps the cost and time budget (the pause itself is neither spent nor waited)."""
        host = self.host
        try:
            rundocs.pause(host.home, host.run_id).write(self.counters())
            self.reexecs.net_pause(NetPause(run=host.run_id, bead=host.bead, t=time.time()))
        except OSError as err:
            host.warn(f"could not keep the network pause for the next run: {err}")

    def safe_point(self, step: str) -> None:
        """A step boundary whose checkpoint is current (tl-7y6.9): when a newer task-loop is installed and not refused
        (bad-versions.json: a version a run died in soon after the move), exec into it and go on with this bead and run
        from the checkpoint. A run not started by `tl.py run-task` never moves."""
        host = self.host
        if host.dry:
            return
        slot = self.slot()
        argv = self.reexecs.args(host.argv if host.argv is not None else sys.argv[1:], slot, host.wt)
        if argv is None:
            return
        try:
            found = (host.newer_fn or self.newer)()
        except Exception as err:  # looking for a newer install never stops a run
            host.warn(f"looking for a newer task-loop failed: {err}\n" + traceback.format_exc())
            return
        if not found:
            return
        ver, d = found
        here = self.install.plugin_version() or self.install.PLUGIN_ROOT.name
        self.switch(step, ver, d, here, argv)

    def hand_over(self, step: str, ver: str, here: str) -> str:
        """The note the next process reads; "" when it was written, else why not."""
        host = self.host
        try:
            rundocs.reexec(host.home, host.run_id).write(self.counters())
            self.reexecs.note(ReexecNote(
                run=host.run_id, bead=host.bead, frm=here, to=ver, step=step,
                from_dir=str(self.install.PLUGIN_ROOT / "skills" / "task-loop"),
                t=time.time()))
        except OSError as err:
            return str(err)
        return ""

    def switch(self, step: str, ver: str, d: Path, here: str, argv: list[str]) -> None:
        host = self.host
        run = host.run_id
        host.steps.end("moved")
        err = self.hand_over(step, ver, here)
        if err:
            host.warn(f"not moving to task-loop {ver}: could not write the hand-over: {err}")
            return
        self.trail.event(host.who, "reload", host.bead, who="engine", old=here, new=ver, step=step, run_id=run, code_dir=str(d))
        host.log.note(f"moving to task-loop {ver} (was {here}) at {step}; run {run} goes on from its checkpoint")
        host.log.emit(rec.Reload(old=here, new=ver, step=step))
        handed = self.child_env.exec_env(host.env, {EnvVar.TL_REEXEC: Reexec(
            run=run, bead=host.bead, pid=os.getpid(), frm=here, owned=RUN_SLOT["owned"]).text()})
        for f in (sys.stdout, sys.stderr):
            try:
                f.flush()
            except Exception as err:
                host.warn(f"could not flush output before reload: {err}\n" + traceback.format_exc())
        try:
            (host.exec_fn or self.reexecs.exec)(
                [*self.child_env.script_argv(d / "skills" / "task-loop" / "tl.py", host.env), *argv], handed)
            host.moved = True
            raise Exec()  # reached only when the exec function is a test's
        except OSError as exc:  # exec itself failed: this version goes on where it is
            self.reexecs.drop(host.bead)
            host.warn(f"could not move to task-loop {ver}: {exc}")
