"""A run that goes on in another process: the counters kept across a network pause or an exec into a newer install, and the exec at a
step boundary."""
import contextlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from taskloop.adapters import ident
from taskloop.adapters.halt import RUN_SLOT
from taskloop.app.loop.versions import Installs
from taskloop.app.release import catalog, pins, reexec
from taskloop.app.slots import engine_lock
from taskloop.app.track import trail
from taskloop.contracts import log as rec
from taskloop.contracts.paths import ConfigDir


class Exec(BaseException):
    """Raised after a test's injected exec function returns (the real exec never does): unwinds run() without its close."""


def newer(root: Path = ident.PLUGIN_ROOT) -> tuple[str, Path] | None:
    """(version, dir) of the install the loop would move to, or None: the engine's step-boundary look."""
    found = Installs(ConfigDir(ident.config_dir()), root, lambda: catalog.installed_version("task-loop"),
                     lambda: pins.read_pin().get("task-loop") or "", now=trail.now).move_to()
    return (found.version, found.dir) if found else None


class Reload:
    def __init__(self, host: Any) -> None:
        self.e = host

    def counters(self) -> dict[str, Any]:
        e = self.e
        return {"elapsed": time.time() - e.t0, "waited": e.waited, "cost": e.cost, "stats": e.stats, "sessions": e.sessions,
                "write_rounds": e.write_rounds, "node_n": e.steps.n}

    def restore_run(self, name: str = "reexec.json") -> None:
        """The counters of the run that exec'd (run_dir/reexec.json) or paused for the network (pause.json), so the run's cost,
        time and trace go on across the move; the time between is neither spent nor waited."""
        e = self.e
        try:
            c = json.loads((e.run_dir / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(c, dict):
            return
        e.t0 = time.time() - float(c.get("elapsed") or 0)
        e.waited, e.cost = float(c.get("waited") or 0), float(c.get("cost") or 0)
        if isinstance(c.get("stats"), dict):
            e.stats.update(c["stats"])
        e.sessions[:] = c.get("sessions") or []
        e.write_rounds = list(c.get("write_rounds") or [])
        e.steps.n = int(c.get("node_n") or 0)

    def save_net_pause(self) -> None:
        """The run paused for the network: its counters and a pointer for the next run-task of this bead, which takes the same
        run id, cost and time budget up again (the pause itself is neither spent nor waited)."""
        e = self.e
        try:
            (e.run_dir / "pause.json").write_text(json.dumps(self.counters()), encoding="utf-8")
            note = reexec.net_pause_path(e.bead)
            note.parent.mkdir(parents=True, exist_ok=True)
            note.write_text(json.dumps({"run": e.log_path.stem, "bead": e.bead, "t": time.time()}), encoding="utf-8")
        except OSError as err:
            e.warn(f"could not keep the network pause for the next run: {err}")

    def safe_point(self, step: str) -> None:
        """A step boundary whose checkpoint is current (tl-7y6.9): when a newer task-loop is installed and not refused
        (bad-versions.json: a version a run died in soon after the move), exec into it and go on with this bead and run
        from the checkpoint. A run not started by `tl.py run-task` never moves."""
        e = self.e
        if e.dry:
            return
        slot = (engine_lock.LOCK.data.get("slot") if engine_lock.LOCK else "") or ""
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
            (e.run_dir / "reexec.json").write_text(json.dumps(self.counters()), encoding="utf-8")
            note = reexec.reexec_path(e.bead)
            note.parent.mkdir(parents=True, exist_ok=True)
            note.write_text(json.dumps({"run": e.log_path.stem, "bead": e.bead, "from": here, "to": ver, "step": step,
                                        "from_dir": str(ident.PLUGIN_ROOT / "skills" / "task-loop"), "t": time.time()}), encoding="utf-8")
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
        os.environ["TL_REEXEC"] = json.dumps({"run": run, "bead": e.bead, "from": here, "owned": RUN_SLOT["owned"]})
        for f in (sys.stdout, sys.stderr):
            with contextlib.suppress(Exception):
                f.flush()
        try:
            (e.exec_fn or reexec.exec_in_place)([sys.executable, str(d / "skills" / "task-loop" / "tl.py"), *argv])
            e.moved = True
            raise Exec()  # reached only when the exec function is a test's
        except OSError as exc:  # exec itself failed: this version goes on where it is
            os.environ.pop("TL_REEXEC", None)
            reexec.drop_reexec(e.bead)
            e.warn(f"could not move to task-loop {ver}: {exc}")
