"""One bead through `tl run-task` as a child of the loop: wait for it, watch for a stop, read what it gave."""
import contextlib
import json
import os
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from taskloop.app.loop import verdict as vd
from taskloop.app.loop.core import Running
from taskloop.app.loop.env import Child, Hold, LoopEnv
from taskloop.app.loop.files import LoopFiles, StopMode
from taskloop.app.loop.versions import Installs
from taskloop.contracts.bead import Bead
from taskloop.contracts.config import LoopConfig
from taskloop.contracts.ids import BeadId
from taskloop.contracts.ports import BdFailure, BeadPatch


@dataclass
class Where:
    """Where the bead runs and what the loop publishes about it."""

    slot: str
    wt: str
    slot_bead: BeadId | None
    started: float


class BeadRun:
    def __init__(self, env: LoopEnv, files: LoopFiles, installs: Installs, tune: Callable[[], LoopConfig],
                 stop_mode: Callable[[], StopMode], publish: Callable[[Running | None], None], beat: Callable[[], None],
                 say: Callable[[str], None]) -> None:
        self.env, self.files, self.installs, self.tune = env, files, installs, tune
        self.stop_mode, self.publish, self.beat, self.say = stop_mode, publish, beat, say

    def wait(self, child: Child, hold: Hold, bead: BeadId) -> tuple[int | None, bool]:
        """(exit code, whether a stop-now ended it). The loop breaking ends the run too: its close step runs before the slot is freed."""
        stopped = False
        try:
            hold.replay()
            while True:
                try:
                    return child.wait(timeout=self.tune().poll), stopped
                except subprocess.TimeoutExpired:
                    pass
                self.beat()
                if not stopped and self.stop_mode() == "now":
                    self.say(f"stop now: stopping {bead} (SIGTERM through stream-proc; its close step still runs)")
                    self.env.stop_now(child)  # the engine traps SIGTERM
                    stopped = True
        except BaseException:
            self.env.stop_tree(child)
            raise

    def run(self, b: Bead, at: Where, code: Path | None = None, handover: dict[str, object] | None = None) -> vd.Verdict:
        """The verdict of one bead (failed when run-task gave none). `code`: the install to run from (the fallback after a
        crash-after-exec; default this loop's own); `handover`: TL_REEXEC for that fallback run."""
        env = self.env
        runs = self.files.runs()
        stem = f"{b.id}-{time.strftime('%Y%m%d-%H%M%S', time.localtime(env.now()))}"
        out, log_path = runs / (stem + ".outcome.json"), runs / (stem + ".log")
        cmd = env.run_task_argv(b.id, at.wt, at.slot, str(out), code)
        t0 = env.now()
        extra = {"TASK_LOOP_SLOT_BEAD": at.slot_bead or "", "TASK_LOOP_LOOP_PID": str(os.getpid()),  # run-task's parent is uv, not us
                 **({"TL_REEXEC": json.dumps(handover)} if handover else {})}
        with open(log_path, "ab") as log:  # append: a rerun of the same stem never cuts a log another reader follows
            child, hold = env.spawn(cmd, log, extra)
            self.publish(Running(b.id, at.slot, t0, child.pid, str(log_path), "" if at.slot else at.wt))
            self.say(f"{b.id} in {at.slot or at.wt} (log {log_path})")
            rc, stopped = self.wait(child, hold, b.id)
        v, gave = vd.read(out, rc, log_path)
        moved = env.reload_note(b.id)  # the engine exec'd into a newer install and left this note; a clean end removes it
        soon = moved is not None and env.now() - moved.t < self.tune().reload_fallback
        if moved and soon and not gave and not stopped and rc not in (0, None) and code is None:
            back = Path(moved.from_dir)
            if (back / "tl.py").is_file():  # died soon after the exec: that version is refused, once more on the old one
                why = f"run-task died (exit {rc}) {env.now() - moved.t:.0f} s after the exec into it"
                self.installs.record_bad(moved.to, why)
                env.event("reload_fallback", b.id, who="loop", old=moved.to, new=moved.frm, why=why, run=moved.run)
                self.say(f"RED: {b.id} died after the move to task-loop {moved.to}; {b.id} goes on from its checkpoint on {moved.frm}")
                return self.run(b, at, back, {"run": moved.run, "bead": b.id, "from": moved.to, "owned": "", "fallback": True})
        if stopped and v.outcome == "failed":  # a stop is no verdict on the bead: back to the queue, unclaimed,
            if env.landed_on_base(at.wt, b.id):  # unless the stop came during a land that went through
                v = v.with_(why=f"{v.why or 'stopped'}; its land commit is on the base: not reopened, close it by hand")
            else:
                self.reopen(b.id)
        return v.with_(minutes=v.minutes if v.minutes is not None else round((env.now() - t0) / 60, 1), run_log=str(log_path))

    def reopen(self, bead: BeadId) -> None:
        with contextlib.suppress(BdFailure):  # bd refused: the bead stays where it is, reclaim gets it
            self.env.store.update(bead, BeadPatch(status="open", assignee=""))
