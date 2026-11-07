"""The machinery of a run: waits, the delegation seam, owner asks and requests, shell and check runs, the reload, the records, the
tree check every node is wrapped in, and the live file and engine lock a worker call leaves."""
import threading
from functools import cached_property
from typing import Any, Protocol

from tlkernel import childenv
from tlkernel.kinds import Kind

from taskloop.adapters import deadline, ident, slotcheck
from taskloop.adapters.agent import last_event_t, new_live
from taskloop.adapters.check_probe import PathProbe
from taskloop.app.asks.closing import ClosingTrust
from taskloop.app.checks.step import StageChecks
from taskloop.app.land.closing import LandHistory
from taskloop.app.pipeline.journal import Journal, JournalHost
from taskloop.app.pipeline.reflect import Reflector
from taskloop.app.pipeline.reload import Reload, ReloadChoice, ReloadCounters, ReloadTransfer
from taskloop.app.pipeline.requests import OwnerRequests
from taskloop.app.pipeline.resume import Resume, ResumePlanning, ResumeProgress, ResumeRecords
from taskloop.app.pipeline.review_glue import ReviewGlue, ReviewLists, ReviewOwner
from taskloop.app.pipeline.stuck import StuckHost, StuckTick
from taskloop.app.pipeline.waits import Waits, WaitsHost
from taskloop.app.release.closing import ReexecBook
from taskloop.app.run.ask_flow import AskFlow
from taskloop.app.run.bead_env import bead_env
from taskloop.app.run.layout import repo_of
from taskloop.app.run.plumbing import Plumbing
from taskloop.app.run.reload_ports import installed_newer, locked_slot
from taskloop.app.run.shared import Shared
from taskloop.app.run.shell import Shell
from taskloop.app.run.state import state_names
from taskloop.app.slots.engine_lock import HeldLock
from taskloop.app.track.closing import TrailEvents
from taskloop.app.workers.delegation import Delegation


class ResumeBinding[T](ResumeProgress, ResumePlanning[T], ResumeRecords, ReviewOwner, Protocol):
    @property
    def review(self) -> ReviewLists: ...


class ReloadBinding(ReloadCounters, ReloadTransfer, ReloadChoice, Protocol):
    @property
    def held_lock(self) -> HeldLock: ...


class JournalBinding(JournalHost, Protocol):
    @property
    def held_lock(self) -> HeldLock: ...


class RunParts(Plumbing):
    held_lock: HeldLock

    bead_env = cached_property(bead_env)  # the slot's environment: every command of the bead gets it (Shell.stream, the worker call)
    @cached_property
    def waits(self: WaitsHost) -> Waits: return Waits(self, deadline)
    delegation = cached_property(Delegation)
    ask_flow = cached_property(AskFlow)
    stage_checks = cached_property(StageChecks)
    shell = cached_property(Shell)
    @cached_property
    def reload(self: ReloadBinding) -> Reload:
        return Reload(self, self, self, ReexecBook(self.home), TrailEvents(), lambda: installed_newer(self.env),
                      lambda: locked_slot(self.held_lock), childenv, ident)

    @cached_property
    def records(self: JournalBinding) -> Journal:
        return Journal(self, lambda: locked_slot(self.held_lock), repo_of)
    shared = cached_property(Shared)
    @cached_property
    def stuck(self: StuckHost) -> StuckTick: return StuckTick(self, last_event_t)
    requests = cached_property(OwnerRequests)

    @cached_property
    def resume[T](self: ResumeBinding[T]) -> Resume[T]:
        return Resume(self, self, self, LandHistory(self.git), ReviewGlue(self), state_names())

    @cached_property
    def reflector(self) -> Reflector:
        return Reflector(self, self, self, ClosingTrust(), childenv.delegate_call_env)

    def sh(self, cmd: Any, timeout: float = 3600, check: bool = False, save: Any = None, env: Any = None, pin: bool = False,
           what: str = "command", cwd: Any = None, stop: threading.Event | None = None, *, network: bool = False) -> tuple[int, str]:
        return self.shell.run(cmd, timeout, check, save, env, pin, what, cwd, stop, network=network)

    def run_checks(self, *a: Any, **kw: Any) -> Any:
        return self.stage_checks.run(*a, **kw)

    def step_guard(self, step: str) -> None:
        """Before every step but the close: the owner's requests (a park or a stop ends the run here), then the tree check."""
        self.requests.at_step(step)
        self.assert_tree(step)

    def assert_tree(self, step: str, when: str = "before") -> None:
        """Before and after every node, and before the land: this slot's git is the slot (a core.worktree in the shared
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

    def live(self, step: str) -> str:
        """The live file for the next delegate call (delegate appends worker events there; the dashboard's Live view reads them)."""
        self.live_n += 1
        path = new_live(self.live_dir, self.live_n, step)
        if not path:
            return ""
        self.live_now = path
        return path
