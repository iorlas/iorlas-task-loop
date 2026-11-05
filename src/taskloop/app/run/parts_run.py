"""The machinery of a run: waits, the delegation seam, owner asks and requests, shell and check runs, the reload, the records, the
tree check every node is wrapped in, and the live file and engine lock a worker call leaves."""
import os
import threading
from functools import cached_property
from typing import Any

from taskloop.adapters import childenv, pidcheck, slotcheck
from taskloop.adapters.check_probe import PathProbe
from taskloop.adapters.runner import live_path
from taskloop.app.run.ask_flow import AskFlow
from taskloop.app.run.bead_env import bead_env
from taskloop.app.run.delegation import Delegation
from taskloop.app.run.plumbing import Plumbing
from taskloop.app.run.records import Records
from taskloop.app.run.reflect import Reflector
from taskloop.app.run.reload import Reload
from taskloop.app.run.requests import OwnerRequests
from taskloop.app.run.resume import Resume
from taskloop.app.run.shared import Shared
from taskloop.app.run.shell import Shell
from taskloop.app.run.stage_checks import StageChecks
from taskloop.app.run.stuck import StuckTick
from taskloop.app.run.waits import Waits
from taskloop.app.slots import engine_lock
from taskloop.contracts.kinds import Kind


class RunParts(Plumbing):
    bead_env = cached_property(bead_env)  # the slot's environment: every command of the bead gets it (Shell.stream, the worker call)
    waits = cached_property(Waits)
    delegation = cached_property(Delegation)
    ask_flow = cached_property(AskFlow)
    stage_checks = cached_property(StageChecks)
    shell = cached_property(Shell)
    reload = cached_property(Reload)
    records = cached_property(Records)
    reflector = cached_property(Reflector)
    shared = cached_property(Shared)
    resume = cached_property(Resume)
    stuck = cached_property(StuckTick)
    requests = cached_property(OwnerRequests)

    def sh(self, cmd: Any, timeout: float = 3600, check: bool = False, save: Any = None, env: Any = None, pin: bool = False,
           what: str = "command", cwd: Any = None, stop: threading.Event | None = None) -> tuple[int, str]:
        return self.shell.run(cmd, timeout, check, save, env, pin, what, cwd, stop)

    def run_checks(self, *a: Any, **kw: Any) -> Any:
        return self.stage_checks.run(*a, **kw)

    def step_guard(self, step: str) -> None:
        """Before every step but the close: the owner's requests (a park or a stop ends the run here), then the tree check."""
        self.requests.at_step(step)
        self.assert_tree(step)

    def assert_tree(self, step: str, when: str = "before") -> None:
        """Before and after every node, and before the land: this slot's git is the slot (lifesim-1mm: a core.worktree in the shared
        .git/config pointed every slot's git at another folder). Unpinned, as a worker's or check's git would see it. A wrong tree
        stops the run with an owner ask, never a skip."""
        bad = slotcheck.tree_problem(self.wt, self.git.unpinned(), self.env)
        if bad:
            self.steps.move("fault", "wrong_tree", bad[0])
            raise self.Blocked(f"failed: tree: {bad[0]} ({when} {step}). {bad[1]}", kind=Kind.FAULT_SLOT)

    def shell_probe(self) -> PathProbe:
        """What the plan lint may ask of this tree: PATH, just, the files (one per engine, so its answers are remembered)."""
        if self._probe is None:
            self._probe = PathProbe(self.wt, childenv.current_env(self.env))
        return self._probe

    def lock_worker(self, started: Any) -> None:
        """The worker delegate launched (the live file's first line) goes into the engine lock, so a SIGKILLed engine leaves it findable."""
        if engine_lock.LOCK:
            engine_lock.LOCK.note(workers=[(started.pid, pidcheck.proc_start(started.pid) or "")])

    def lock_workers(self, survivors: Any, started: Any) -> None:
        """After a call: the pids that outlived its stop keep the slot busy; none: free."""
        if engine_lock.LOCK:
            engine_lock.LOCK.note(workers=[(pid, pidcheck.proc_start(pid) or "") for pid in survivors])

    def live(self, step: str) -> str:
        """The live file for the next delegate call (delegate appends worker events there; the dashboard's Live view reads them)."""
        self.live_n += 1
        path = live_path(self.live_dir, self.live_n, step)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        except OSError:
            return ""
        self.live_now = path
        return path
