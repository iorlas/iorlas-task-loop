#!/usr/bin/env python3
"""The task engine: one bead through reset → plan → (write → checks → review)* per stage → gate → land → close.

    tl.py run-task ID [--worktree DIR] [--dry-run]

Code routes; AI nodes only produce structured outputs (validated against a schema). The close step always runs.
A coordinator session may start it and watch it (attended mode); nothing here needs one. Python 3.8+, standard library only.
"""

import contextlib
import copy
import dataclasses
import difflib
import fcntl
import fnmatch
import glob
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from functools import cached_property
from pathlib import Path
from typing import Any

from taskloop.adapters import applog, beadtools, gitrepo, ident, landlock, links, looks, opencode, pidcheck
from taskloop.adapters import halt as halting
from taskloop.domain.report import matchers as lifecycle
import loop_health
from types import SimpleNamespace
import outcome as oc
import seams
from taskloop.app.slots import engine_lock
from taskloop.domain.matchers import clip
from taskloop.app.track import trail, verbs
from taskloop.adapters import context_size, slotcheck
from taskloop.adapters.gitenv import git_env, pinned_env, run_git
from taskloop.app.wire import slots as wslots
import vendored  # noqa: F401
import stream_proc
from clock import SystemClock
from taskloop.adapters import delegate as dg
from taskloop.adapters import procs as sproc
from taskloop.adapters.runner import live_path
from taskloop.adapters.check_probe import PathProbe
from taskloop.app.asks import intake, raiser
from taskloop.app.checks import evidence as check_evidence
from taskloop.app.checks.evidence import compact
from taskloop.app.checks.host import CheckFault, CheckStuck
from taskloop.app.checks.runner import Checker
from taskloop.app.plan.briefs import Briefs
from taskloop.app.plan.planner import Planner
from taskloop.app.review.routing import Routing
from taskloop.app.review.settles import Settles
from taskloop.app.review.verifier import Verifier
from taskloop.app.run import outcomes, summaries
from taskloop.app.run.console import say
from taskloop.app.run.layout import RunLayout
from taskloop.app.run import trace as runtrace
from taskloop.app.write.handoff import Handoff
from taskloop.app.write.stage_loop import StageLoop
from taskloop.app.run.calls import timing
from taskloop.app.run.resume import Resume
from taskloop.app.run.blocked import Blocked, FixFailed, blocked_for
from taskloop.app.run.waits import Waits
from taskloop.app.run.delegation import Delegation
from taskloop.app.run.ask_flow import AskFlow
from taskloop.app.run.stage_checks import StageChecks
from taskloop.app.run.run_once import RunOnce
from taskloop.app.land.closer import Closer
from taskloop.app.land.fixer import Fixer
from taskloop.app.land.lander import Lander
from taskloop.app.land.rebase import Rebase
from taskloop.app.land.checkout import Checkout
from taskloop.app.land.tree import Tree
from taskloop.app.plan.cases import Cases
from taskloop.app.release import reexec
from taskloop.app.run.records import Records
from taskloop.app.run.reload import Exec, Reload
from taskloop.app.run.reflect import Reflector
from taskloop.app.run.shared import Shared
from taskloop.app.write.briefing import Briefing
from taskloop.app.write.newfiles import NewFiles
from taskloop.app.look.judge import Judge
from taskloop.app.look.owner_look import OwnerLook
from taskloop.app.look.shots import Pictures
from taskloop.app.review.link_check import LinkCheck
from taskloop.app.run.state import Checkpoints, StateAttrs, carries_state
from taskloop.contracts.checkpoint import RunState
from taskloop.app.run.context import RunContext
from taskloop.app.run.worker_call import Ops, WorkerCall
from taskloop.app.slots.lease import Lease
from taskloop.contracts import log as rec
from taskloop.contracts.argv import FORM, argv_of, checks_to_text, checks_to_wire, text_of
from taskloop.contracts.answers import LEGACY_KINDS, ROUTED_KINDS, VERDICTS
from taskloop.contracts import answers
from taskloop.contracts.schema import unstrict
from taskloop.contracts.ask import BudgetLine
from taskloop.contracts.bead import Bead
from taskloop.contracts.checks import CheckFaultKind, CheckResult, CheckRun
from taskloop.contracts.config import FRESH_ABOVE_K
from taskloop.contracts.delegate import RunRequest
from taskloop.contracts.enums import AskClass, AskStatus
from taskloop.contracts.ports import BdFailure, BeadPatch, BeadQuery, NewBead
from taskloop.contracts.enums import Outcome, WaitWhat
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.stores import AskStore, JsonlStore
from taskloop.domain.asks import specs as askspecs
from taskloop.domain.asks import text as asktext
from taskloop.domain.lanes import policy as lp
from taskloop.domain.plan import brief
from taskloop.domain.plan.stored import role_view
from taskloop.domain.lanes.matchers import read_only_command
from taskloop.domain.lanes.says import stop_say, stop_why
from taskloop.domain.checks import lint, matchers, trim
from taskloop.domain.checks import names as check_names
from taskloop.domain.checks.matchers import glob_re, slot_wait_secs
from taskloop.domain.checks.names import norm as norm_cmd
from taskloop.stores.real import real_stores
from taskloop.domain.plan.matchers import AcceptanceText, gate_only_criteria, word_set, without_runner
from taskloop.domain.review.kinds import UNCHECKED_KINDS
from taskloop.domain.review.findings import engine_finding
from taskloop.domain.review.matchers import Wording
from taskloop.domain.write.matchers import count_tests
from taskloop.domain.prompts.common import DECIDED_TEXT, LATER_CASES, RULES_MAX, UNCHECKED_TEXT
from taskloop.domain.prompts.plan import (ASSUME_TEXT, DRY_CHECK_TEXT, EMPTY_PLAN_TEXT, GATE_ONLY_ACCEPTANCE, GATE_ONLY_ACCEPTANCE_TEXT,
                                          PLAN_BRIEF_KB, PLAN_DECIDED_TEXT, PLAN_PROMPT, TRACKER_TEXT, VISUAL_PLAN, VISUAL_STAGES)
from taskloop.domain.prompts.reflect import REFLECT_PROMPT
from taskloop.domain.prompts.verify import VERIFY_PROMPT
from taskloop.domain.prompts.review import NEW_FILES_TEXT, review_prompt
from taskloop.domain.prompts.write import (DONE_SO_FAR, LOOK_FEEDBACK, LOOK_WRITE_TABLE, REPEAT_RED, SHOTS_FIX, STAGES_DONE,
                                           WRITE_RESUME_PROMPT, write_prompt)

# ---- output contracts -----------------------------------------------------------------------------------------------

FLAKE_DAYS = 14     # how long a writer-reported flaky test stays in the shared notes
# tl-bxk.10.23: engine.visual_paths {include, exclude} (globs) says which changes are visual; absent, no look rules at all
IMAGE_EXT = (".png", ".jpg", ".jpeg")
MAX_SHOTS, MAX_SHOT_BYTES = 20, 5 * 1024 * 1024
LOOK_LABEL = "owner-look"


def tool_on_path(name):
    return shutil.which(name)


def visual_hit(vp, paths):
    """True when a path matches an include glob and no exclude glob."""
    inc = [glob_re(g) for g in vp.include] if vp else []
    exc = [glob_re(g) for g in vp.exclude] if vp else []
    return any(any(r.match(p) for r in inc) and not any(r.match(p) for r in exc) for p in paths)




















# ---- workers --------------------------------------------------------------------------------------------------------



# ---- moving to a newer install between steps (tl-7y6.9): by exec only, no module is ever reloaded in place ----------------------------


# tl-bxk.13.16.4: a push that died of the network (lifesim-l4ow: curl 56 broken pipe, after a 17 min hook) is retried with a rest
TRANSIENT_PUSH = re.compile(r"curl \d+|Broken pipe|Connection (?:reset|timed out|refused)|Could not resolve host|early EOF|RPC failed|"
                            r"remote end hung up|SSL_ERROR|TLS|Operation timed out|Network is unreachable|"
                            r"Temporary failure in name resolution|error: 5\d\d|HTTP/\d(?:\.\d)? 5\d\d", re.I)
# tl-fsj: a configured check that fails because the tree lacks what the base's config names is the engine's, never a writer's amend




# ---- the engine -----------------------------------------------------------------------------------------------------



@carries_state
class Engine(StateAttrs):
    stop_pending = False  # run_bead sets it when a SIGTERM came during the claim
    tree_memo: Any = None  # (git status, file stats) -> tree hash, of the last tree_hash()
    done: list[str]  # RunState fields the tests assign (the type checker saw them assigned in the moved methods before)
    writer_said: str
    plan_data: Any
    accepted: list[int]
    stage_tree: str

    def __init__(self, bead, wt, cfg, dry_run=False, verbose=True, store=None, route=seams.DelegateRoute(), clock=None, git=None,
                 stores=None, fresh=False):
        self.bead, self.wt, self.cfg, self.dry, self.verbose, self.store, self.router, self.repo = bead, wt, cfg, dry_run, verbose, store or beadtools.bd_store(), route, git
        self.stats = {"writes": 0, "rounds": 0, "reviews": 0, "replans": 0, "nodes": 0, "tests_added": 0, "tests_removed": 0,
                      "tokens_in": 0, "tokens_cached": 0, "tokens_out": 0}
        self.session, self.fresh = ident.session_id(), fresh
        self.leftovers = []
        self.bead_parent = ""  # tl-bxk.10.23
        self.look_filed, self.filed, self.unfiled = False, [], []  # unfiled: follow-ups bd refused (the ReviewState keeps both)
        self.look_retried, self.shots_skipped = set(), set()
        self.unverified = []  # tl-bxk.10.28: items that land for the owner
        self.link_ok, self.link_bad, self.link_fn, self.link_tries = set(), {}, None, {}  # tl-bxk.7: links opened from this host (link_fn: a test's check)
        self.amended = False  # a plan was amended or replanned: its first stage does not start at the task's base
        self.strays = []  # unaccepted untracked files moved to evidence/strays before the land gate (tl-bxk.10.24)
        self.cap_granted = False
        self.old_plan, self.amend_text, self.amend_why = None, "", ""  # set where a checkpoint's plan is kept to be amended
        self.unchecked = []   # what the last review of this run says nobody checked (each review re-judges it)
        self.answered = None  # the owner ask this run starts from, once answered
        self.verify_answer = ""  # the owner's answer to a verify ask, when it asks for more than a yes
        self.stuck_why = ""
        self.resolved, self.refusal, self.route, self.contract = None, None, "", None  # the delegate install in use (delegate_link.resolve) and its contract.json
        self.probe = None  # the network probe (a test's); None: delegate's `route.py net`
        self.net_up_times = []  # when a network stop came while the probe said up (lane_policy: three in five minutes pause the run)
        self.at_stage = 0  # the stage a call belongs to, for its key
        self.pause_role, self.pause_lane = "", ""  # the role and lane a paused run waits for: the loop wakes the bead when the role is usable
        self.budget_warned = set()
        self.plan_assumed = False  # tl-ntp: the planner was sent back once to plan on assumptions
        self.plan_decided = False  # the planner was sent back once with the requirement that answers its question
        self.verified = []  # the verifier's answer per unchecked item at land: in the trace and on the bead
        self.write_rounds = []  # per write round: resumed, input tokens, turns, prompt chars, context k, why fresh (a fix round's cost)
        self.last_summary = ""  # the last write's summary: a fresh writer is told it
        self.state, self.checkpoints = RunState(), Checkpoints(self)  # what survives a park (contracts/checkpoint.py), and its one writer
        self.plan_summary, self.bead_title, self.reflection = "", "", None
        self.left_dirty, self.branch, self.task_branch = False, "", ""
        self.gate_log: Path | None = None
        self.salvage_tail, self.rebase_orig, self.rebase_pre = "", "", []
        self.shot_cache: dict[str, Any] | None = None
        self.salvaged = False  # a resume conflict was fixed in place, not by starting again (tl-7y6.2.19)
        self.lane_notes = []  # steps that ran on the writer's own family, with delegate's warning (tl: same_family, never a pause)
        self.taste = []  # [{id, title}] taste items for the owner-look bead
        self.scope = ""  # the bead's acceptance text: an unchecked item outside it is a follow-up, not a gap (tl-bxk.13.5)
        self.sessions = []  # every AI call of this run: the trace a later reflection reads (traces.jsonl)
        self.outcome, self.why, self.asked = "failed", "", False  # what result() tells the loop
        self.kind, self.fp, self.storm = None, "", ""  # the run's outcome.Kind (None: the verify-gaps ask), its fingerprint, a storm banner
        self.clock, self.disp = clock or SystemClock(), None
        self.retry_after = 0.0  # a pause for a lane: when delegate says it is back (epoch; 0 = unknown)
        self.landed_sha = ""  # set the moment the push goes through: whatever stops the run after it, the bead landed
        self.last_run = None  # the CheckRun of the last stage round: the engine's evidence for the verifier (tl-bxk.10.25)
        self.prev_ck, self.ck_run, self.resumed, self.run_logged = "", "", False, False
        self.reexec = reexec.take_reexec_env()  # this run-task came from an exec into a newer install, or a fallback to the older
        if self.reexec.get("bead") != bead:
            self.reexec = {}
        pause = {} if self.reexec else reexec.take_net_pause(bead)  # a run paused for the network: its run id and counters go on
        layout = RunLayout.open(bead, wt, self.reexec.get("run") or pause.get("run"))  # the same run id: log, run dir and trace go on
        self.log_path, self.err_path, self.run_dir = layout.log_path, layout.err_path, layout.run_dir
        self.task_dir, self.brief_file, self.evidence_dir = layout.task_dir, layout.brief_file, layout.evidence_dir
        stem = self.log_path.stem
        self.exec_fn, self.newer_fn, self.argv, self.moved, self.os_lock = None, None, None, False, landlock.os_lock  # a test's exec, newer-install lookup, run-task argv, the cross-process lock
        self.stores = stores or real_stores(ConfigDir(ident.config_dir()))
        self.ctx = RunContext.open(bead, cfg, Path(wt), stem, self.run_dir, self.stores, store, route, self.clock, self.sessions, self.stats,
                                   opencode.opencode_id, context_size.context_tokens, say, verbose, dry_run, lambda: time.time(), self.assert_tree,
                                   lambda text: trail.event("stage", bead, text=text))
        c: Any = self.ctx
        self.log, self.steps, self.budget, self.calls, self.checklog = c.log, c.steps, c.budget, c.calls, c.checklog
        self.checker = Checker(self, lambda secs: self.halt_point(wait=secs))
        self.delegation.route(quiet=True)
        if self.reexec:
            self.reload.restore_run()
        elif pause:
            self.reload.restore_run("pause.json")
            self.log.note("back from a network pause: run %s goes on" % stem)

    # the budget's numbers, read and set as the engine's own (waited: seconds spent waiting for a shared resource, not budget_min's)
    t0, waited, labels, cost = (property(lambda obj, k=k: getattr(obj.budget, k), lambda obj, v, k=k: setattr(obj.budget, k, v))
                                for k in ("t0", "waited", "labels", "spent"))

    def call_dir(self):
        return ident.config_dir() / "checkpoints"

    def publish_plan(self):
        if self.plan_data:
            (self.run_dir / "plan.json").write_text(json.dumps(checks_to_wire(self.plan_data), indent=1))

    def blocked_for(self, why, kind, stop=None, spec=None, fix=False):
        return blocked_for(why, kind, stop, spec, fix)

    def run_checks(self, *a, **kw):
        return self.stage_checks.run(*a, **kw)

    def git_in(self, path, *a):
        return gitrepo.git(*a, cwd=path)

    def record_land(self, sha):
        verbs.land(self.bead, sha, self.wt, self.store)

    def land_lock_path(self):
        return landlock.land_lock_path(self.git("remote", "get-url", "origin") or str(self.wt))

    @cached_property
    def tree(self):
        return Tree(self)

    @cached_property
    def rebase(self):
        return Rebase(self)

    @cached_property
    def fixer(self):
        return Fixer(self)

    @cached_property
    def lander(self):
        return Lander(self)

    @cached_property
    def closer(self):
        return Closer(self, SimpleNamespace(oc=oc, loop_health=loop_health, track=verbs, attempt=beadtools.attempt, say=say, outcome_for=outcomes.outcome_for, node_outcome=outcomes.node_outcome,
                                            close_move=outcomes.close_move, reflection_text=outcomes.reflection_text, why_code=runtrace.why_code,
                                            config_dir=ident.config_dir()))

    waits = cached_property(Waits)
    delegation = cached_property(Delegation)
    ask_flow = cached_property(AskFlow)
    stage_checks = cached_property(StageChecks)
    cases = cached_property(Cases)
    reload = cached_property(Reload)
    records = cached_property(Records)
    reflector = cached_property(Reflector)
    shared = cached_property(Shared)
    briefing = cached_property(Briefing)

    @cached_property
    def checkout(self):
        return Checkout(self)

    @cached_property
    def newfiles(self):
        return NewFiles(self)

    @cached_property
    def pictures(self):
        return Pictures(self)

    @cached_property
    def judge(self):
        return Judge(self)

    @cached_property
    def owner_look(self):
        return OwnerLook(self)

    @cached_property
    def link_check(self):
        return LinkCheck(self)

    def lock_worker(self, started):
        """The worker delegate launched (the live file's first line) goes into the engine lock, so a SIGKILLed engine leaves it findable."""
        if engine_lock.LOCK:
            engine_lock.LOCK.note(workers=[[started.pid, sproc.proc_start(started.pid) or ""]])

    def lock_workers(self, survivors, started):
        """After a call: the pids that outlived its stop keep the slot busy; none: free."""
        if engine_lock.LOCK:
            engine_lock.LOCK.note(workers=[[pid, sproc.proc_start(pid) or ""] for pid in survivors])

    def live(self, step):
        """The live file for the next delegate call (delegate appends worker events there; the dashboard's Live view reads them)."""
        self.live_n += 1
        path = live_path(self.log_path, self.live_n, step)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        except OSError:
            return ""
        return path

    # -- records
    def warn(self, text):
        """Something a watching coordinator should look at: printed with ⚠, kept in the log, shown on the dashboard."""
        self.log.warn(text)

    def detail(self, lines):
        """Verbose mode (the default): the facts behind a step, indented under it."""
        if self.verbose:
            for ln in lines:
                if ln:
                    say("           %s" % ln[:400])

    # -- AI node
    def ai(self, node, title, prompt, *a, **kw):
        """One AI node, then the tree check: a worker that wrote core.worktree is caught before review or land."""
        out = self.worker.run(node, title, prompt, *a, **kw)
        self.assert_tree(kw.get("step") or node, "after")
        checks_to_text(out[0])
        return out

    live_n = 0  # the number of delegate calls with a live file so far

    @cached_property
    def resume(self):
        return Resume(self)

    @cached_property
    def stage_loop(self):
        return StageLoop(self)

    @cached_property
    def hand(self):
        return Handoff(self)

    @cached_property
    def planner(self):
        return Planner(self)

    @cached_property
    def briefs(self):
        return Briefs(self)

    def on_path(self, name):
        return tool_on_path(name)

    @cached_property
    def routing(self):
        return Routing(self)

    @cached_property
    def settles(self):
        return Settles(self)

    @cached_property
    def verifier(self):
        return Verifier(self)

    Blocked = Blocked  # the stop a step raises: components catch it through the host
    FixFailed = FixFailed

    @cached_property
    def worker(self):
        return WorkerCall(self, Ops(summaries.summarize, read_only_command, self.blocked_for, stop_why,
                                    stop_say, self.after_call))

    def after_call(self, c, res):
        """A node's answer was taken: its detail lines, then what was odd about it."""
        checks_to_text(res.data)  # from here on a check is its one-line text
        self.detail(summaries.details(c.node, res.data))
        self.anomalies(c.node, res, c.tries)

    def anomalies(self, node, r, attempt):
        d = r.data
        if attempt > 1:
            self.warn("%s needed a retry to produce valid output" % node)
        if node != "write" and r.secs > float(self.cfg.node_timeout_min) * 60 * 0.6:  # a write follows its worker's activity
            self.warn("%s took %d min, close to the %s min limit" % (node, r.secs // 60, self.cfg.node_timeout_min))
        spent = self.budget.used()
        for mark in (0.5, 0.8):
            if spent > mark and mark not in self.budget_warned:
                self.budget_warned.add(mark)
                self.warn("%.0f%% of the task's budget is used" % (spent * 100))
        if node == "review" and any(f["severity"] == "high" for f in d["findings"]):
            self.warn("the reviewer found a high-severity problem")

    # -- script helpers
    def assert_tree(self, step, when="before"):
        """Before and after every node, and before the land: this slot's git is the slot (lifesim-1mm: a core.worktree in the shared
        .git/config pointed every slot's git at another folder). Unpinned, as a worker's or check's git would see it. A wrong tree
        stops the run with an owner ask, never a skip."""
        bad = slotcheck.tree_problem(self.wt)
        if bad:
            why = "tree: %s (%s %s)" % (bad[0], when, step)
            self.steps.move("fault", "wrong_tree", bad[0])
            raise Blocked("failed: %s. %s" % (why, bad[1]), kind=oc.Kind.FAULT_SLOT)

    @cached_property
    def halt(self):
        # The stop flag of the run: set from any thread (the SIGTERM handler does), sh() ends the command's tree, a worker call is
        # stopped and a wait ends; the run then stops at its next safe point (halt_point), never from inside a signal handler.
        return halting.RUN_HALT["ev"] or threading.Event()

    def halt_point(self, when=True, wait=0):  # a safe point (and a wait of `wait` s that a stop ends): a stop ends the run here
        if when and halting.nap(self.halt, wait):
            raise Blocked("failed: stopped (SIGTERM)", kind=oc.Kind.PAUSE_KILLED)

    def sh(self, cmd, timeout=3600, check=False, save=None, env=None, pin=False, what="command", cwd=None):
        """A command: an argv list, exec'd as given (no shell, no quoting rules; a string is a programming error), run by stream-proc
        in a group of its own. It ends by itself, at `timeout` seconds of wall time (exit 124; its tree is stopped), or when
        `self.halt` is set. Nothing else stops it: a quiet command may be waiting. pin=True: an engine git command, run with
        GIT_DIR/GIT_WORK_TREE of the slot; checks and gates run unpinned (they may run git on other repos)."""
        if isinstance(cmd, str):
            raise TypeError("a command is an argv list, never a string: %r" % cmd[:80])
        if what == "check" and self.halt.is_set():  # a stop: no check starts; it reports itself failed, the run stops at its next safe point
            self.killed = True
            return -15, ""
        cid = self.log.next_id("m")
        cwd = cwd or self.wt  # a check on the untouched base runs in its own checkout
        self.log.emit(rec.CmdStart(id=cid, text=text_of(cmd), cwd=str(cwd)))
        started, chunks = time.time(), []
        self.killed = self.wall_hit = False
        try:
            res = stream_proc.run(list(cmd), cwd=cwd, env=dict(sproc.current_env(), **(pinned_env(self.wt) if pin else {}), **(env or {})),
                                  on_stdout=chunks.append, on_stderr=chunks.append, timeout=timeout, stop=self.halt)
        except BaseException:  # stopped (stream-proc stopped the tree first): never leave a check (just check, Unity) running
            self.killed, now = True, time.time()
            self.log.emit(rec.Kill(what=what, why="interrupted", secs=round(now - started), started_t=started, kill_t=now, observed_t=now))
            self.log.emit(rec.CmdEnd(id=cid, exit=-1, secs=round(now - started, 1)))
            raise
        rc = 124 if res.timed_out == "wall" else -res.signal if res.signal else res.returncode or 0
        text = "".join(chunks)
        if res.timed_out:  # only a stop the engine performed; a command that exits 124 by itself is not a kill
            self.killed, self.wall_hit, now = True, res.timed_out == "wall", time.time()
            if self.wall_hit:
                text += "\n(timed out after %g min: the engine stopped it and everything it started)" % round(timeout / 60, 2)
            self.log.emit(rec.Kill(what=what, why="timeout" if self.wall_hit else res.timed_out, secs=round(res.secs), exit=rc,
                                   started_t=started, kill_t=now, observed_t=now, alive=list(res.survivors)))
        if save:
            Path(save).write_text(text, encoding="utf-8")
        tail = "\n".join(text.strip().splitlines()[-15:])
        self.log.emit(rec.CmdEnd(id=cid, exit=rc, secs=round(time.time() - started, 1), out=tail[-600:] if rc else ""))
        self.halt_point(what != "check")  # a stop, not the command's verdict (a stopped check reports itself first)
        if check and rc:
            raise Blocked("failed: `%s` exit %d\n%s" % (text_of(cmd), rc, tail), kind=oc.Kind.FAULT_INFRA)
        return rc, tail

    def git(self, *a):
        return gitrepo.git(*a, cwd=self.wt)


    def comment(self, text):
        if not self.dry:
            beadtools.attempt(self.store.add_comment, self.bead, text)

    # -- tl-bxk.13.8: notes shared by the tasks of one repo (docs/design/stages.md section 6)
    def run(self):
        return RunOnce(self).go()

    def result(self):
        """The run's outcome for the loop: landed (closed, done too), parked (blocked for the owner: an ask, or one
        still open), paused (the machine's trouble: lanes, login, network; the bead stays open), failed."""
        out = ("landed" if self.outcome in ("landed", "done") else oc.POLICY[self.kind].loop if self.kind
               else "failed" if self.outcome == "failed" else "parked")
        return {"v": 1, "outcome": out, "bead": self.bead, "why": self.why[:500], "run": self.log_path.stem,
                "log": str(self.log_path), "minutes": round((time.time() - self.t0) / 60, 1),
                "rounds": self.stats["rounds"], "tests_added": self.stats["tests_added"], "asked": self.asked,
                "retry_after": self.retry_after if out == "paused" else 0.0, "cost": round(self.cost, 2),
                "kind": self.kind.value if self.kind else "", "fingerprint": self.fp, "storm": self.storm,
                "role": self.pause_role if out == "paused" else "", "lane": self.pause_lane if out == "paused" else ""}



    def diff_text(self):
        tree = self.checkout.tree_hash()
        return (gitrepo.git("diff", self.checkout.base_sha(), tree, cwd=self.wt) if tree else "") or ""

    # -- review and verify (src/taskloop/app/review): the engine lends its state, the components do the work
    _probe: PathProbe | None = None

    def shell_probe(self):
        """What the plan lint may ask of this tree: PATH, just, the files (one per engine, so its answers are remembered)."""
        if self._probe is None:
            self._probe = PathProbe(self.wt, sproc.current_env())
        return self._probe

    # -- checkpoints: where a stopped run was, outside the worktree, so the next run goes on from there
    MARKERS_ARGV = ["python3", str(Path(__file__).with_name("markers.py"))]  # exit 1 and the lines when a conflict marker is in the tree
    MARKERS = text_of(MARKERS_ARGV)

    # -- look and feel (tl-bxk.10.23): screenshots for a visual change, judged by the agent, held for the owner's batch
    # -- tl-bxk.13.15: visual work. The engine renders, a look judge judges, the owner decides taste (docs/design/visual-work.md)
    stop_deferred = staticmethod(halting.stop_deferred)







LINK_CAP = 200  # links opened per review





# ---- prompts (one copy each; the per-node instructions of the design) -----------------------------------------------


MAX_REBASE_RESETS = 2   # per bead, across runs (tl-19i)
