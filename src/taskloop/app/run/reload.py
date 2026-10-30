"""A run that goes on in another process: the counters kept across a network pause or an exec into a newer install, and the exec at a
step boundary."""
import contextlib
import sys
import time
from pathlib import Path
from typing import Any

from taskloop.adapters import childenv, ident
from taskloop.adapters.halt import RUN_SLOT
from taskloop.app.loop.versions import Installs
from taskloop.app.release import catalog, pins, reexec
from taskloop.app.slots import engine_lock
from taskloop.app.track import trail
from taskloop.contracts import env as penv
from taskloop.contracts import log as rec
from taskloop.contracts.envvars import EnvVar
from taskloop.contracts.paths import ConfigDir, RunFiles
from taskloop.contracts.run import NetPause, Reexec, ReexecNote, RunCounters
from taskloop.contracts.stores import JsonStore


class Exec(BaseException):
    """Raised after a test's injected exec function returns (the real exec never does): unwinds run() without its close."""


def newer(root: Path = ident.PLUGIN_ROOT) -> tuple[str, Path] | None:
    """(version, dir) of the install the loop would move to, or None: the engine's step-boundary look."""
    found = Installs(ConfigDir(ident.config_dir()), root, lambda: catalog.installed_version("task-loop"),
                     lambda: pins.read_pin().task_loop or "", now=trail.now).move_to()
    return (found.version, found.dir) if found else None


class Reload:
    def __init__(self, host: Any) -> None:
        self.e = host

    def counters(self) -> RunCounters:
        e = self.e
        return RunCounters(elapsed=time.time() - e.t0, waited=e.waited, cost=e.cost, stats=dict(e.stats), sessions=list(e.sessions),
                           write_rounds=list(e.write_rounds), node_n=e.steps.n)

    def restore_run(self, file: Path) -> None:
        """The counters of the run that exec'd (RunFiles.reexec) or paused for the network (RunFiles.pause), so the run's cost,
        time and trace go on across the move; the time between is neither spent nor waited."""
        e = self.e
        c = JsonStore(file, RunCounters).get()
        if c is None:
            return
        e.t0 = time.time() - c.elapsed
        e.waited, e.cost = c.waited, c.cost
        e.stats.update(c.stats)
        e.sessions[:] = c.sessions
        e.write_rounds = list(c.write_rounds)
        e.steps.n = c.node_n

    def save_net_pause(self) -> None:
        """The run paused for the network: its counters and a pointer for the next run-task of this bead, which takes the same
        run id, cost and time budget up again (the pause itself is neither spent nor waited)."""
        e = self.e
        try:
            JsonStore(RunFiles(e.run_dir).pause(), RunCounters).write(self.counters())
            reexec.net_pause_store(e.bead).write(NetPause(run=e.log_path.stem, bead=e.bead, t=time.time()))
        except OSError as err:
            e.warn(f"could not keep the network pause for the next run: {err}")

    def safe_point(self, step: str) -> None:
        """A step boundary whose checkpoint is current (tl-7y6.9): when a newer task-loop is installed and not refused
        (bad-versions.json: a version a run died in soon after the move), exec into it and go on with this bead and run
        from the checkpoint. A run not started by `tl.py run-task` never moves."""
        e = self.e
        if e.dry:
            return
        slot = engine_lock.LOCK.rec.slot if engine_lock.LOCK else ""
        argv = reexec.reexec_args(e.argv if e.argv is not None else sys.argv[1:], slot, e.wt)
        if argv is None:
            return
        try:
            found = (e.newer_fn or newer)()
        except Exception as err:  # looking for a newer install never stops a run
            e.warn(f"looking for a newer task-loop failed: {err}")
            return
        if not found:
            return
        ver, d = found
        here = ident.plugin_version() or ident.PLUGIN_ROOT.name
        self.switch(step, ver, d, here, argv)

    def hand_over(self, step: str, ver: str, here: str) -> str:
        """The note the next process reads; "" when it was written, else why not."""
        e = self.e
        try:
            JsonStore(RunFiles(e.run_dir).reexec(), RunCounters).write(self.counters())
            reexec.reexec_store(e.bead).write(ReexecNote(
                run=e.log_path.stem, bead=e.bead, frm=here, to=ver, step=step, from_dir=str(ident.PLUGIN_ROOT / "skills" / "task-loop"),
                t=time.time()))
        except OSError as err:
            return str(err)
        return ""

    def switch(self, step: str, ver: str, d: Path, here: str, argv: list[str]) -> None:
        e = self.e
        run = e.log_path.stem
        e.steps.end("moved")
        err = self.hand_over(step, ver, here)
        if err:
            e.warn(f"not moving to task-loop {ver}: could not write the hand-over: {err}")
            return
        trail.event("reload", e.bead, who="engine", old=here, new=ver, step=step, run=run, code_dir=str(d))
        e.log.note(f"moving to task-loop {ver} (was {here}) at {step}; run {run} goes on from its checkpoint")
        e.log.emit(rec.Reload(old=here, new=ver, step=step))
        penv.export(EnvVar.TL_REEXEC, Reexec(run=run, bead=e.bead, frm=here, owned=RUN_SLOT["owned"]).text())
        for f in (sys.stdout, sys.stderr):
            with contextlib.suppress(Exception):
                f.flush()
        try:
            (e.exec_fn or reexec.exec_in_place)([*childenv.script_argv(d / "skills" / "task-loop" / "tl.py"), *argv])
            e.moved = True
            raise Exec()  # reached only when the exec function is a test's
        except OSError as exc:  # exec itself failed: this version goes on where it is
            penv.take(EnvVar.TL_REEXEC)
            reexec.drop_reexec(e.bead)
            e.warn(f"could not move to task-loop {ver}: {exc}")
