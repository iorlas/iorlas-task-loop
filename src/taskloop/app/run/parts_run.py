"""The machinery of a run: waits, the delegation seam, owner asks and requests, shell and check runs, the reload, the records, the
tree check every node is wrapped in, and the live file and engine lock a worker call leaves."""
import threading
from functools import cached_property
from typing import Any, Protocol

from tlartifacts import ask_pictures
from tlasks.closing import ClosingTrust
from tlasks.flow import AskFlow, AskFlowHost
from tlkernel import askspecs, asktext, childenv
from tlkernel.askspec import AskSpec
from tlkernel.check_files import repo_key
from tlkernel.kinds import Kind
from tlkernel.runlayout import repo_of
from tlpipeline import api
from tlrelease.reexec import ReexecBook
from tlslots.engine_lock import HeldLock
from tlslots.shared import Shared, SharedHost

from taskloop.adapters import deadline, ident, slotcheck
from taskloop.adapters.agent import last_event_t, new_live
from taskloop.adapters.check_probe import PathProbe
from taskloop.app.checks.step import StageChecks
from taskloop.app.land.closing import LandHistory
from taskloop.app.run.bead_env import bead_env
from taskloop.app.run.plumbing import Plumbing
from taskloop.app.run.reload_ports import installed_newer, locked_slot
from taskloop.app.run.shell import Shell
from taskloop.app.run.state import state_names
from taskloop.app.track.closing import TrailEvents
from taskloop.app.wire import slotfx
from taskloop.app.workers.delegation import Delegation


def shared_over(host: SharedHost) -> Shared:
    return Shared(host, fx=slotfx.FX)


def ask_blocked(why: str, spec: AskSpec | None = None, *, kind: Kind) -> api.Blocked:
    return api.Blocked(why, spec, kind=kind)


def ask_flow_over(host: AskFlowHost) -> AskFlow:
    return AskFlow(host, ident.plugin_version, ask_blocked, ask_pictures.attach, repo_of, repo_key, askspecs.open_question, asktext.comment)


class ResumeBinding[T](api.ResumeProgress, api.ResumePlanning[T], api.ResumeRecords, api.ReviewOwner, Protocol):
    @property
    def review(self) -> api.ReviewLists: ...


class ReloadBinding(api.ReloadCounters, api.ReloadTransfer, api.ReloadChoice, Protocol):
    @property
    def held_lock(self) -> HeldLock: ...


class JournalBinding(api.JournalOrigin, api.JournalActivity, api.JournalOutcome, api.JournalTrace, api.JournalProjection,
                     api.RecordHost, api.HostFacts, Protocol):
    @property
    def held_lock(self) -> HeldLock: ...


class RunParts(Plumbing):
    held_lock: HeldLock

    bead_env = cached_property(bead_env)  # the slot's environment: every command of the bead gets it (Shell.stream, the worker call)
    @cached_property
    def waits(self: api.WaitsHost) -> api.Waits: return api.Waits(self, deadline)
    delegation = cached_property(Delegation)
    ask_flow = cached_property(ask_flow_over)
    stage_checks = cached_property(StageChecks)
    shell = cached_property(Shell)
    @cached_property
    def reload(self: ReloadBinding) -> api.Reload:
        return api.Reload(self, self, self, ReexecBook(self.home), TrailEvents(), lambda: installed_newer(self.env),
                      lambda: locked_slot(self.held_lock), childenv, ident)

    @cached_property
    def records(self: JournalBinding) -> api.Journal:
        return api.Journal(self, self, self, self, self, self, self, lambda: locked_slot(self.held_lock), repo_of, ident.plugin_version)
    shared = cached_property(shared_over)
    @cached_property
    def stuck(self: api.StuckHost) -> api.StuckTick: return api.StuckTick(self, last_event_t)
    requests = cached_property(api.OwnerRequests)

    @cached_property
    def resume[T](self: ResumeBinding[T]) -> api.Resume[T]:
        return api.Resume(self, self, self, LandHistory(self.git), api.ReviewGlue(self), state_names())

    @cached_property
    def reflector(self) -> api.Reflector:
        return api.Reflector(self, self, self, ClosingTrust(), childenv.delegate_call_env)

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
