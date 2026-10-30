"""The task engine: one bead through reset, plan, (write, checks, review) per stage, gate, land, close. The Engine is the composition
root of a run: it holds the run's state (fields.py), builds the parts that do the work, and has the few methods every part uses."""
import json
import os
import shutil
import threading
import time
from functools import cached_property
from pathlib import Path
from typing import Any, ClassVar

from taskloop.adapters import beadtools, childenv, context_size, gitrepo, ident, landlock, opencode, pidcheck, slotcheck
from taskloop.adapters import halt as halting
from taskloop.adapters.check_probe import PathProbe
from taskloop.adapters.clock import SystemClock
from taskloop.adapters.runner import live_path
from taskloop.app.checks.runner import Checker
from taskloop.app.land.checkout import Checkout
from taskloop.app.land.fixer import Fixer
from taskloop.app.land.lander import Lander
from taskloop.app.land.rebase import Rebase
from taskloop.app.land.tree import Tree
from taskloop.app.look.judge import Judge
from taskloop.app.look.owner_look import OwnerLook
from taskloop.app.look.shots import Pictures
from taskloop.app.plan.briefs import Briefs
from taskloop.app.plan.cases import Cases
from taskloop.app.plan.planner import Planner
from taskloop.app.release import reexec, seams
from taskloop.app.review.link_check import LinkCheck
from taskloop.app.review.routing import Routing
from taskloop.app.review.settles import Settles
from taskloop.app.review.verifier import Verifier
from taskloop.app.run import ended, summaries
from taskloop.app.run.ask_flow import AskFlow
from taskloop.app.run.bead_env import bead_env
from taskloop.app.run.blocked import Blocked, FixFailed, blocked_for
from taskloop.app.run.closer import Closer
from taskloop.app.run.console import say
from taskloop.app.run.context import RunContext
from taskloop.app.run.delegation import Delegation
from taskloop.app.run.fields import RunFields
from taskloop.app.run.layout import RunLayout
from taskloop.app.run.records import Records
from taskloop.app.run.reflect import Reflector
from taskloop.app.run.reload import Reload
from taskloop.app.run.requests import OwnerRequests
from taskloop.app.run.resume import Resume
from taskloop.app.run.run_once import RunOnce
from taskloop.app.run.shared import Shared
from taskloop.app.run.shell import Shell
from taskloop.app.run.stage_checks import StageChecks
from taskloop.app.run.state import carries_state
from taskloop.app.run.stuck import StuckTick
from taskloop.app.run.waits import Waits
from taskloop.app.run.worker_call import Ops, WorkerCall
from taskloop.app.slots import engine_lock
from taskloop.app.track import trail, verbs
from taskloop.app.wire import real as wire_real
from taskloop.app.write.briefing import Briefing
from taskloop.app.write.handoff import Handoff
from taskloop.app.write.newfiles import NewFiles
from taskloop.app.write.stage_loop import StageLoop
from taskloop.contracts import fence, plancheck
from taskloop.contracts.argv import text_of
from taskloop.contracts.enums import Result
from taskloop.contracts.ids import BeadId
from taskloop.contracts.kinds import Kind
from taskloop.contracts.landed import Landed, LandedStore
from taskloop.contracts.log import Assumed, Said
from taskloop.contracts.paths import PLAN_FILE, ConfigDir, RunFiles
from taskloop.contracts.run import RunReport
from taskloop.domain import outcome as oc
from taskloop.domain.lanes.matchers import read_only_command
from taskloop.domain.lanes.says import stop_say, stop_why
from taskloop.stores.real import real_stores

__all__ = ["Blocked", "Engine", "FixFailed", "tool_on_path"]


def tool_on_path(name: str) -> str | None:
    return shutil.which(name)


@carries_state
class Engine(RunFields):
    tree_memo: Any = None  # (git status, file stats) -> tree hash, of the last tree_hash()
    stop_pending = False  # run_bead sets it when a SIGTERM came during the claim
    live_n = 0  # the number of delegate calls with a live file so far
    live_now = ""  # the live file of the newest delegate call (the stuck tick reads when it was last written)
    _probe: PathProbe | None = None
    MARKERS_ARGV: ClassVar[list[str]] = ["python3", str(ident.PLUGIN_ROOT / "src" / "taskloop" / "adapters" / "markers.py")]
    MARKERS = text_of(MARKERS_ARGV)
    Blocked = Blocked  # the stop a step raises: components catch it through the host
    FixFailed = FixFailed
    stop_deferred = staticmethod(halting.stop_deferred)
    done: list[str]  # RunState fields the tests assign (the type checker saw them assigned in the moved methods before)
    writer_said: str
    plan_data: Any
    accepted: list[int]
    stage_tree: str

    def __init__(self, bead: BeadId, wt: str, cfg: Any, dry_run: bool = False, verbose: bool = True, store: Any = None,
                 route: Any = None, clock: Any = None, git: Any = None, stores: Any = None, fresh: bool = False,
                 claim: fence.Claim | None = None, spawner: Any = None) -> None:
        route = route or seams.DelegateRoute()
        self.spawner = spawner or wire_real.spawner()
        super().__init__(bead, wt, cfg, dry_run, verbose, store, route, git, fresh, claim)
        self.clock = clock or SystemClock()
        self.reexec: dict[str, Any] = reexec.take_reexec_env()  # this run-task came from an exec into a newer install, or a fallback
        if self.reexec.get("bead") != bead:
            self.reexec = {}
        # a run paused for the network: its run id and counters go on
        pause = None if self.reexec else reexec.take_net_pause(bead)
        self.stores = stores or real_stores(ConfigDir(ident.config_dir()))
        # a run that died inside its close: its id goes on (the keys of the effects it applied are under it)
        ck = None if dry_run or self.reexec or pause else self.checkpoints.read()
        self.dead = ck if ended.unfinished(ck) else None
        # the same run id: log, run dir and trace go on
        taken = self.reexec.get("run") or (pause.run if pause else None) or (self.dead.ended.run if self.dead and self.dead.ended else None)
        layout = RunLayout.open(bead, wt, taken)
        self.log_path, self.err_path, self.run_dir = layout.log_path, layout.err_path, layout.run_dir
        self.task_dir, self.brief_file, self.evidence_dir = layout.task_dir, layout.brief_file, layout.evidence_dir
        self.exec_fn: Any = None  # a test's exec, newer-install lookup, run-task argv, the cross-process lock
        self.newer_fn: Any = None
        self.argv: Any = None
        self.moved = False
        self.os_lock = landlock.os_lock
        stem = self.log_path.stem
        self.ctx = RunContext.open(bead, cfg, Path(wt), stem, self.run_dir, self.stores, store, route, self.clock, self.sessions,
                                   self.stats, opencode.opencode_id, context_size.context_tokens, say, verbose, dry_run,
                                   self.now, self.step_guard, self.on_step)
        c: Any = self.ctx
        self.log, self.steps, self.budget, self.calls, self.checklog = c.log, c.steps, c.budget, c.calls, c.checklog
        host: Any = self
        self.checker = Checker(host, lambda secs: self.halt_point(wait=secs))
        self.delegation.route(quiet=True)
        if self.reexec:
            self.reload.restore_run(RunFiles(self.run_dir).reexec())
        elif pause:
            self.reload.restore_run(RunFiles(self.run_dir).pause())
            self.log.note(f"back from a network pause: run {stem} goes on")

    # the budget's numbers, read and set as the engine's own (waited: seconds spent waiting for a shared resource, not budget_min's)
    t0, waited, labels, cost = (property(lambda obj, k=k: getattr(obj.budget, k), lambda obj, v, k=k: setattr(obj.budget, k, v))
                                for k in ("t0", "waited", "labels", "spent"))

    # the parts: each is built when first asked for, from this engine
    tree = cached_property(Tree)
    bead_env = cached_property(bead_env)  # the slot's environment: every command of the bead gets it (Shell.stream, the worker call)
    rebase = cached_property(Rebase)
    fixer = cached_property(Fixer)
    lander = cached_property(Lander)
    closer = cached_property(Closer)
    waits = cached_property(Waits)
    delegation = cached_property(Delegation)
    ask_flow = cached_property(AskFlow)
    stage_checks = cached_property(StageChecks)
    shell = cached_property(Shell)
    cases = cached_property(Cases)
    reload = cached_property(Reload)
    records = cached_property(Records)
    reflector = cached_property(Reflector)
    shared = cached_property(Shared)
    briefing = cached_property(Briefing)
    checkout = cached_property(Checkout)
    newfiles = cached_property(NewFiles)
    pictures = cached_property(Pictures)
    judge = cached_property(Judge)
    owner_look = cached_property(OwnerLook)
    link_check = cached_property(LinkCheck)
    resume = cached_property(Resume)
    stage_loop = cached_property(StageLoop)
    hand = cached_property(Handoff)
    planner = cached_property(Planner)
    briefs = cached_property(Briefs)
    routing = cached_property(Routing)
    settles = cached_property(Settles)
    verifier = cached_property(Verifier)
    stuck = cached_property(StuckTick)
    requests = cached_property(OwnerRequests)

    @cached_property
    def worker(self) -> WorkerCall:
        return WorkerCall(self, Ops(summaries.summarize, read_only_command, self.blocked_for, stop_why, stop_say, self.records.after_call))

    @cached_property
    def halt(self) -> threading.Event:
        # The stop flag of the run: set from any thread (the SIGTERM handler does), sh() ends the command's tree, a worker call is
        # stopped and a wait ends; the run then stops at its next safe point (halt_point), never from inside a signal handler.
        return halting.RUN_HALT["ev"] or threading.Event()

    def halt_point(self, when: bool = True, wait: float = 0) -> None:  # a safe point (and a wait of `wait` s that a stop ends)
        if when and halting.nap(self.halt, wait):
            raise Blocked("failed: stopped (SIGTERM)", kind=Kind.PAUSE_KILLED)

    def sh(self, cmd: Any, timeout: float = 3600, check: bool = False, save: Any = None, env: Any = None, pin: bool = False,
           what: str = "command", cwd: Any = None) -> tuple[int, str]:
        return self.shell.run(cmd, timeout, check, save, env, pin, what, cwd)

    def git(self, *a: str) -> str:
        return gitrepo.git(*a, cwd=self.wt)

    def git_in(self, path: Any, *a: str) -> str:
        return gitrepo.git(*a, cwd=path)

    def run_checks(self, *a: Any, **kw: Any) -> Any:
        return self.stage_checks.run(*a, **kw)

    def blocked_for(self, why: str, kind: str, stop: Any = None, spec: Any = None, fix: bool = False) -> Blocked:
        return blocked_for(why, kind, stop, spec, fix)

    def warn(self, text: str) -> None:
        """Something a watching coordinator should look at: printed with a warning sign, kept in the log, shown on the dashboard."""
        self.log.warn(text)

    def detail(self, lines: list[str]) -> None:
        """Verbose mode (the default): the facts behind a step, indented under it."""
        if self.verbose:
            for ln in lines:
                if ln:
                    say(f"           {ln[:400]}")

    def comment(self, text: str) -> None:
        """The one poster of the engine's comments on the bead: each is also a Said record, tied to the open step (or the last)."""
        if not self.dry:
            self.log.emit(Said(step=self.step_id(), who="engine", text=text))
            beadtools.attempt(self.store.add_comment, self.bead, text)

    def assumed(self, text: str) -> None:
        """What the planner planned around instead of asking: an Assumed record, tied to the open step."""
        self.log.emit(Assumed(step=self.step_id(), text=text))

    def step_id(self) -> str:
        """The open step's id; between steps (the close-out after the close step), the last one's."""
        last = self.steps.cur or self.steps.last
        return last.id if last else ""

    def ai(self, node: str, title: str, prompt: str, *a: Any, **kw: Any) -> Any:
        """One AI node, then the tree check: a worker that wrote core.worktree is caught before review or land. Before it, the
        owner's requests are taken (a safe point), and the notes taken since the last call end its prompt (and its delta)."""
        self.requests.at_step(kw.get("step") or node)
        notes = self.requests.prompt_tail()
        if notes:
            prompt += notes
            if kw.get("delta") is not None:
                kw["delta"] += notes
        out = self.worker.run(node, title, prompt, *a, **kw)
        self.assert_tree(kw.get("step") or node, "after")
        plancheck.parse(out[0])
        return out

    def step_guard(self, step: str) -> None:
        """Before every step but the close: the owner's requests (a park or a stop ends the run here), then the tree check."""
        self.requests.at_step(step)
        self.assert_tree(step)

    def assert_tree(self, step: str, when: str = "before") -> None:
        """Before and after every node, and before the land: this slot's git is the slot (lifesim-1mm: a core.worktree in the shared
        .git/config pointed every slot's git at another folder). Unpinned, as a worker's or check's git would see it. A wrong tree
        stops the run with an owner ask, never a skip."""
        bad = slotcheck.tree_problem(self.wt)
        if bad:
            self.steps.move("fault", "wrong_tree", bad[0])
            raise Blocked(f"failed: tree: {bad[0]} ({when} {step}). {bad[1]}", kind=Kind.FAULT_SLOT)

    def on_path(self, name: str) -> str | None:
        return tool_on_path(name)

    def shell_probe(self) -> PathProbe:
        """What the plan lint may ask of this tree: PATH, just, the files (one per engine, so its answers are remembered)."""
        if self._probe is None:
            self._probe = PathProbe(self.wt, childenv.current_env())
        return self._probe

    @staticmethod
    def now() -> float:
        return time.time()  # looked up at each call: a test sets the wall clock

    def on_step(self, text: str) -> None:
        trail.event("stage", self.bead, text=text)

    def call_dir(self) -> Path:
        return ident.config_dir() / "checkpoints"

    def publish_plan(self) -> None:
        if self.plan_data:
            (self.run_dir / PLAN_FILE).write_text(json.dumps(plancheck.to_wire(self.plan_data), indent=1))

    def record_land(self, sha: str) -> None:
        LandedStore(ident.config_dir()).put(Landed(bead=self.bead, sha=sha, base=self.cfg.base, t=self.now()))
        verbs.land(self.bead, sha, self.wt, self.store, base=self.cfg.base, claim=self.claim)

    def land_lock_path(self) -> Path:
        return landlock.land_lock_path(self.git("remote", "get-url", "origin") or str(self.wt))

    @property
    def tree_writer(self) -> Checkout:
        """The same checkout: app/checks gets the right to stage only through this name (tests/rules/test_tree_writer.py)."""
        return self.checkout

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
        path = live_path(self.log_path, self.live_n, step)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        except OSError:
            return ""
        self.live_now = path
        return path

    def diff_text(self) -> str:
        tree = self.checkout.tree_hash()
        return (gitrepo.git("diff", self.checkout.base_sha(), tree, cwd=self.wt) if tree else "") or ""

    def run(self) -> int:
        return RunOnce(self).go()

    def result(self) -> RunReport:
        """The run's outcome for the loop: landed (closed, done too), parked (blocked for the owner: an ask, or one
        still open), paused (the machine's trouble: lanes, login, network; the bead stays open), failed."""
        out = oc.POLICY[self.kind].loop
        paused = out is Result.PAUSED
        return RunReport(outcome=out, bead=self.bead, why=self.why[:500], run=self.log_path.stem, log=str(self.log_path),
                         minutes=round((time.time() - self.t0) / 60, 1), rounds=self.stats["rounds"],
                         tests_added=self.stats["tests_added"], asked=self.asked, retry_after=self.retry_after if paused else 0.0,
                         cost=round(self.cost, 2), kind=self.kind.value, fingerprint=self.fp, storm=self.storm,
                         role=self.pause_role if paused else "", lane=self.pause_lane if paused else "")
