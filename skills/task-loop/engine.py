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
from taskloop.app.run import outcomes
from taskloop.app.run import trace as runtrace
from taskloop.app.write.handoff import Handoff
from taskloop.app.write.stage_loop import StageLoop
from taskloop.app.run.calls import timing
from taskloop.app.run.resume import Resume
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


_TREE_MEMO = {}   # (slot, what the config files and environment are now) -> tree_problem's answer


def tree_problem(wt):
    """(what is wrong, the owner's fix) when git at `wt`, read as ambient config has it, is not that checkout; else None.
    Two git calls, none while the config files are as they were: a run asks eleven times."""
    key = gitrepo.config_key(wt)
    if key and key in _TREE_MEMO:
        return _TREE_MEMO[key]
    out = _tree_problem(wt)
    if key:
        _TREE_MEMO[key] = out
    return out


def _tree_problem(wt):
    clean = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR")}

    def g(*a):
        r = subprocess.run(["git", "-C", str(wt)] + list(a), env=clean, capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        return r.stdout.strip() if r.returncode == 0 else ""

    both = g("rev-parse", "--path-format=absolute", "--git-common-dir", "--show-toplevel").split("\n")
    if len(both) == 2:
        common, top = both
    else:  # one of the two fails (core.bare=true has no top level): ask for each alone, as the message needs what is left
        common, top = g("rev-parse", "--path-format=absolute", "--git-common-dir"), None
    repo = str(Path(common or ".").parent)
    origin = bare = ""
    for ln in g("config", "--show-origin", "--get-regexp", r"^core\.(worktree|bare)$").splitlines():  # the last of each key wins, as `--get` does
        where, _, kv = ln.partition("\t")
        k, _, v = kv.partition(" ")
        if k.lower() == "core.worktree":
            origin = "%s\t%s" % (where, v) if v else where
        elif k.lower() == "core.bare":
            bare = v
    origin = origin.strip()
    if origin:
        where = origin.split("\t")[0].replace("file:", "")
        return ("core.worktree is set (%s)" % origin.replace("\t", " = ", 1),
                "core.worktree redirects every worktree of this repo to another folder. Remove it: "
                "`git config --unset core.worktree` in %s (it was set in %s), then rerun." % (repo, where))
    if bare.strip().lower() == "true":
        return ("core.bare is true",
                "core.bare=true in the repo's config makes git refuse the work tree. Fix: `git config core.bare false` "
                "in %s, then rerun." % repo)
    if top is None:
        top = g("rev-parse", "--show-toplevel")
    if not top or not gitrepo.same_dir(top, wt):
        return ("git's top-level folder is %s, not the slot %s" % (top or "(none)", wt),
                "Something redirects git away from the slot. Check `git config --show-origin --list` in %s for "
                "core.worktree or core.bare; `git config --unset core.worktree` in %s if set." % (wt, repo))
    return None


# ---- the engine -----------------------------------------------------------------------------------------------------



class Blocked(Exception):
    """A stop. kind: the outcome.Kind that says what the engine does at the close (POLICY). spec: the AskSpec of an ask kind (what
    the owner is asked, built from facts at the raise site); a stop that is no ask carries none."""

    def __init__(self, why, spec=None, kind=None):
        super().__init__(why)
        self.why, self.spec, self.kind = why, spec, kind


class FixFailed(Blocked):
    """A conflict fix round that could not finish (no rounds left, or the rebase would not continue): a resume salvage starts again."""


@carries_state
class Engine(StateAttrs):
    stop_pending = False  # run_bead sets it when a SIGTERM came during the claim
    tree_memo: Any = None  # (git status, file stats) -> tree hash, of the last tree_hash()
    done: list[str]  # RunState fields the tests assign (the type checker saw them assigned in the moved methods before)
    writer_said: str

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
        d = ident.config_dir() / "engine"
        d.mkdir(exist_ok=True)
        self.reexec = reexec.take_reexec_env()  # this run-task came from an exec into a newer install, or a fallback to the older
        if self.reexec.get("bead") != bead:
            self.reexec = {}
        pause = {} if self.reexec else reexec.take_net_pause(bead)  # a run paused for the network: its run id and counters go on
        stem = self.reexec.get("run") or pause.get("run")  # the same run id: log, run dir and trace go on
        if not stem:  # a fresh run has its own id, also when the last run of this bead began in the same second: the stamp moves on
            t0, n = time.time(), 0
            while True:
                stem = "%s-%s" % (bead, time.strftime("%Y%m%d-%H%M%S", time.localtime(t0 + n)))
                if not ((d / (stem + ".jsonl")).exists() or (ident.config_dir() / "runs" / stem).exists()):
                    break
                n += 1
        self.log_path = d / (stem + ".jsonl")
        self.err_path = d / (stem + ".stderr")
        self.exec_fn, self.newer_fn, self.argv, self.moved, self.os_lock = None, None, None, False, landlock.os_lock  # a test's exec, newer-install lookup, run-task argv, the cross-process lock
        # Engine files (brief, plan, node answers, check results) live outside the worktree, where no worker can write
        # them; in lifesim-vbo a writer's sandbox runs kept in .task/ were read as engine results by four planners.
        self.run_dir = ident.config_dir() / "runs" / self.log_path.stem
        self.run_dir.mkdir(parents=True, exist_ok=True)
        prune_check_rounds(ident.config_dir() / "runs")
        self.task_dir = Path(wt) / ".task" / bead  # the writer's: only evidence/ lives here
        self.task_dir.mkdir(parents=True, exist_ok=True)
        self.brief_file = self.task_dir / "brief.md"  # the brief as the writer can re-read it: the engine's copy stays in run_dir
        self.evidence_dir = self.task_dir / "evidence"  # the writer's proof of what the engine cannot rerun
        self.evidence_dir.mkdir(exist_ok=True)
        self.stores = stores or real_stores(ConfigDir(ident.config_dir()))
        self.ctx = RunContext.open(bead, cfg, Path(wt), stem, self.run_dir, self.stores, store, route, self.clock, self.sessions, self.stats,
                                   opencode.opencode_id, context_tokens, say, verbose, dry_run, lambda: time.time(), self.assert_tree,
                                   lambda text: trail.event("stage", bead, text=text))
        c: Any = self.ctx
        self.log, self.steps, self.budget, self.calls, self.checklog = c.log, c.steps, c.budget, c.calls, c.checklog
        self.checker = Checker(self, lambda secs: self.halt_point(wait=secs))
        self.delegate_route(quiet=True)
        if self.reexec:
            self.reload.restore_run()
        elif pause:
            self.reload.restore_run("pause.json")
            self.log.note("back from a network pause: run %s goes on" % stem)

    # the budget's numbers, read and set as the engine's own (waited: seconds spent waiting for a shared resource, not budget_min's)
    t0, waited, labels, cost = (property(lambda obj, k=k: getattr(obj.budget, k), lambda obj, v, k=k: setattr(obj.budget, k, v))
                                for k in ("t0", "waited", "labels", "spent"))

    def delegate_route(self, quiet=False):
        """The delegate for the next call (tl-6ax): resolved again each call (a configured path, then the pin, then the installed
        one). A refused one (another contract, a pin that is gone) keeps the one in use (noted); with none in use the run says why."""
        new = self.router.resolve(self.cfg.delegate)
        if isinstance(new, dg.Refusal):
            if self.resolved is None:
                self.refusal = new
            elif not quiet:
                self.log.note("delegate not switched: %s %s; keeping %s" % (new.kind, new.detail, self.route))
            return self.route
        if self.resolved is not None and new.route != self.resolved.route and not quiet:
            self.log.note("delegate switched: %s -> %s" % (self.route, new.route))
        self.resolved, self.route, self.contract, self.refusal = new, new.route, new.contract, None
        if not quiet:
            self.log.note("delegate call via %s" % self.route)
        return self.route

    def net_probe(self):
        """The network probe: a test's, else delegate's `route.py net`."""
        return self.probe or dg.RouteProbe(self.route)

    def call_dir(self):
        return ident.config_dir() / "checkpoints"

    def publish_plan(self):
        if self.plan_data:
            (self.run_dir / "plan.json").write_text(json.dumps(checks_to_wire(self.plan_data), indent=1))

    def blocked_for(self, why, kind, stop=None, spec=None, fix=False):
        """The Blocked a step ends with: `kind` is an outcome.Kind name; `stop` the stop that decided it; `spec` the ask it carries;
        `fix`: a conflict fix round that could not finish (a resume salvage starts again)."""
        err = (FixFailed if fix else Blocked)(why, spec, kind=oc.Kind[kind])
        err.stop = stop
        return err

    FixFailed = FixFailed

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

    def wait_start(self, what, holder="", until=None):
        """A wait begins (before the sleep, so a wait still going shows): its id, which add_wait closes."""
        wid = self.log.next_id("w")
        self.log.emit(rec.WaitStart(id=wid, what=what, holder=holder, until=until))
        return wid

    def add_wait(self, secs, what, wid=None):
        """`secs` spent waiting for a shared resource (not the budget's), the end of the wait `wid` (one is written when it was not begun)."""
        secs = self.budget.wait(secs)
        if wid or secs > 0:
            wid = wid or self.wait_start(what)
            if secs > 0:
                self.log.note("waited %d min for %s: not counted in budget_min" % (secs // 60, what.value.replace("_", " ")))
            self.log.emit(rec.WaitEnd(id=wid, secs=round(secs), in_budget=False))

    @contextlib.contextmanager
    def locked(self, what, path, holder=None):
        """landlock.os_lock with a wait recorded as its own segment (tl-9h2): the open step ends before the wait starts (it was
        booked to the step before), and the wait's records name the lock, who held it and how long it took. The lock is a record
        of its own while held. tl-y35: the wait is a wait for a shared resource like any other: it is added to `waited`, so
        budget_min does not count it. Timed on self.clock."""
        who, t_req, wid = [], [self.clock.now()], []

        def waiting(w):
            who.append(w)
            self.steps.end()
            t_req[0] = self.clock.now()  # the wait starts when the step before it has ended
            wid.append(self.wait_start(WaitWhat(what), w))  # a wait still going (or cut off) shows up
            self.log.note("waiting for the %s (held by %s)" % (what.replace("_", " "), w))
        with self.os_lock(path, holder or self.bead, waiting, check=self.halt_point):
            if who:
                secs = max(0.0, self.clock.now() - t_req[0])
                self.waited += secs
                self.log.emit(rec.WaitEnd(id=wid[0], secs=round(secs), in_budget=False))
            held = self.clock.now()
            self.log.emit(rec.Lock(what=what.removesuffix("_lock"), holder=holder or self.bead))
            try:
                yield path
            finally:
                self.log.emit(rec.Unlock(what=what.removesuffix("_lock"), secs=round(self.clock.now() - held, 1)))

    def note_slot_waits(self, text, wall):
        """A check's output says how long it queued for a Unity slot ("unity-slot: x got slot 0 after 686s"). The output
        is not trusted: all the waits in one run together are at most that run's wall time."""
        total = slot_wait_secs(text)
        self.add_wait(min(total, wall), WaitWhat.UNITY_SLOT)

    def budget_check(self):
        over = self.budget.over()
        if over:
            steps = outcomes.run_breakdown(self.log_path, self.steps.cur)
            went = ", ".join("%s %d min (%d round%s)" % (b.step, b.minutes, b.rounds, "" if b.rounds == 1 else "s") for b in steps)
            raise Blocked("over budget: %s%s%s" % (", ".join(over), (". Where it went: " + went) if went else "",
                                                   (" (%d min waiting for shared resources not counted)" % (self.waited // 60))
                                                   if self.waited >= 60 else ""),
                          askspecs.over_budget(over, steps, self.waited // 60), kind=oc.Kind.ASK_BUDGET)

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

    @cached_property
    def worker(self):
        return WorkerCall(self, Ops(summarize, read_only_command, self.blocked_for, stop_why,
                                    stop_say, self.after_call))

    def after_call(self, c, res):
        """A node's answer was taken: its detail lines, then what was odd about it."""
        checks_to_text(res.data)  # from here on a check is its one-line text
        self.detail(details(c.node, res.data))
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
        bad = tree_problem(self.wt)
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
        return self.run_once()

    def run_once(self):
        outcome, why, sha, spec, kind = "failed", "", "", None, oc.Kind.FAULT_ENGINE
        hb = Lease(self.store, self.bead, os.environ.get("TASK_LOOP_SLOT_BEAD", ""))
        ck = self.checkpoints.read()
        self.prev_ck = ck.run if ck else ""
        try:
            if self.stop_pending or self.halt.is_set():  # stopped during the claim (run_bead) or before the engine ran
                raise Blocked("failed: stopped (SIGTERM)", kind=oc.Kind.PAUSE_KILLED)
            bead = beadtools.peek(self.store, self.bead)
            if not bead:
                raise Blocked("failed: bead %s not found" % self.bead, kind=oc.Kind.FAULT_INFRA)
            self.bead_title, self.bead_parent = bead.title, bead.parent
            hb.start()
            self.delegate_route()
            if not self.route:
                why = self.refusal or dg.Refusal("not_installed")
                raise Blocked("failed: the engine needs the iorlas-delegate plugin that speaks contract %d (%s %s); update both: "
                              "claude plugin update iorlas-delegate@iorlas-marketplace" % (dg.CONTRACT, why.kind, why.detail),
                              kind=oc.Kind.FAULT_CONTRACT_SKEW)
            self.log.note("workers: delegate %s (contract %d)" % (self.route, dg.CONTRACT))
            self.log.note("task-loop %s" % (ident.plugin_version() or "(unknown version)"))
            self.tree.reset(bead)
            self.budget.labels = list(bead.labels)
            self.check_ask()
            self.planner.cap.grant()
            written = self.planner.cap.answered_words() if self.answered and self.answered.ask_class == AskClass.MISSING_CRITERIA else ""
            if not AcceptanceText.present(bead) and not written:
                raise Blocked("ticket: the bead has no acceptance criteria", askspecs.missing_criteria(), kind=oc.Kind.ASK_TICKET)
            self.scope = AcceptanceText.text(bead) or written
            plan, i, state = self.resume.point()
            self.records.log_run()
            # tl-fsj: the configured checks come from the base's config, so the tree they run on must have what the base has; every
            # resume rebases first, a plan to make or a stage to go on with (lifesim: 8 beads parked on 'just fmt-check-changed')
            at_land = plan is not None and (i >= len(plan["stages"]) or (state or {}).get("fix"))  # a conflict there is the writer's fix round
            moved = "" if at_land else self.rebase.onto_base(salvage=plan is not None)  # (no plan: nothing accepted to salvage)
            if moved == "conflict-fixable":
                self.plan_data = self.plan_data or plan
                moved = self.rebase.salvage()
            if moved == "conflict" and self.rebase.start_again("Its work: %s" % (self.git("log", "--oneline", "-n", "3", "%s..HEAD" % self.cfg.base) or "").replace("\n", "; ")):
                plan, i, state = None, 0, None
            elif moved == "rebased" and plan is not None:
                self.stage_tree = ""  # the stage's diff starts at the base now: the rebase moved what it was measured from
            if plan is None:  # a move here loses nothing: the new image reads the same checkpoint (or none) and plans
                self.reload.safe_point("plan")
            if plan is None:
                plan, i, state = self.planner.plan(again=self.replan_first), 0, None
            while i < len(plan["stages"]):
                d = self.stage_loop.run(plan, i, state)
                state = None
                if d == "replan":
                    if self.pending_land_validation:
                        self.pending_land_validation += "\n" + self.stuck_why
                        self.checkpoints.save(stage=i, rounds=0, n=0, feedback="", step="write")
                    self.replans += 1
                    self.stats["replans"] = replans = self.replans
                    if replans > int(self.cfg.max_replans) + self.extra:
                        raise self.planner.cap.blocked("stage %d stuck after %s rounds. What failed: %s" % (
                            i + 1, self.cfg.max_rounds, self.stuck_why[:600]))
                    self.accepted = []
                    plan = self.planner.plan(again=True)
                    i = 0
                    continue
                self.accepted.append(i)
                self.done.append(plan["stages"][i]["goal"])
                i += 1
                if i == len(plan["stages"]):
                    self.pending_land_validation = ""  # every recovery stage passed checks and review
                self.checkpoints.save(stage=i, rounds=0, n=0, feedback="", step="write" if i < len(plan["stages"]) else "land")
                if i == len(plan["stages"]):
                    self.reload.safe_point("land")  # the checkpoint says land: the close and the land run on the newest code
            if self.render_stale and self.last_reqs and self.pictures.shot_methods() and not self.dry:
                # code changed after the last render (a fix round past the render rounds): the pictures that land show the tree
                self.log.note("rendering the last shots again: code changed since the pictures were made")
                self.pictures.render_shots(self.last_reqs, self.look_done + 1)
            gaps = self.self_verify([u for u in self.unchecked if u["kind"] in UNCHECKED_KINDS or self.judge.is_look(u)])
            if gaps:
                raise Blocked("verify: before land, the workers could not check: " + "; ".join(
                    "%s (%s%s)" % (u["what"], u["kind"], ("; " + u["why"]) if u.get("why") else "") for u in gaps),
                    askspecs.external_fact([u["what"] for u in gaps]), kind=oc.Kind.ASK_DECISION)
            sha = self.lander.finish(bead)
            outcome = "landed" if sha else "done"
            kind = oc.Kind.LANDED if sha else oc.Kind.DONE
            if sha:
                self.owner_look.file_owner_look()  # before the checkpoint goes: a crash from here on still files it on resume
            self.checkpoints.drop()
        except Blocked as b:
            kind = b.kind
            outcome = outcomes.outcome_for(kind, b.why)
            why, spec = b.why, b.spec
        except Exec:
            pass  # the process image is gone; nothing below runs in a real exec
        except Exception as e:  # the close-out must run whatever broke
            outcome, why, kind = "failed", "failed: engine error %s: %s" % (type(e).__name__, e), oc.Kind.FAULT_ENGINE
        finally:
            if self.moved:
                hb.stop()
            else:
                with self.stop_deferred():  # a stop here would skip the close: no trace, no bead update
                    if self.landed_sha and outcome != "landed":  # stopped after the push: on the base, close it as landed
                        self.warn("%s after the land went through; closing it landed" % (why or outcome))
                        outcome, why, sha, spec, kind = "landed", "", self.landed_sha, None, oc.Kind.LANDED
                    hb.stop()
                    reexec.drop_reexec(self.bead)  # a run that ended is no crash after an exec
                    if kind == oc.Kind.PAUSE_NETWORK and not self.dry:
                        self.reload.save_net_pause()
                    self.outcome, self.why = outcome, why
                    self.closer.close(outcome, why, sha, spec, kind)
        return 0 if self.moved or outcome in ("landed", "done") else 2

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
    def self_verify(self, gaps):
        return self.verifier.run(gaps)

    def ledger_route(self, what):
        return self.routing.ledger_route(what)

    def engine_does(self, what):
        return self.routing.engine_does(what)

    def engine_steps(self, gaps):
        return self.routing.engine_steps(gaps)

    def resolve_kind(self, u, a):
        return self.routing.resolve_kind(u, a)

    def route_left(self, left):
        return self.routing.route_left(left)

    def backed_by_leftover(self, what):
        return self.routing.backed_by_leftover(what)

    def add_unverified(self, u, why):
        self.routing.add_unverified(u, why)









    _probe: PathProbe | None = None

    def shell_probe(self):
        """What the plan lint may ask of this tree: PATH, just, the files (one per engine, so its answers are remembered)."""
        if self._probe is None:
            self._probe = PathProbe(self.wt, sproc.current_env())
        return self._probe

    # -- checkpoints: where a stopped run was, outside the worktree, so the next run goes on from there
    def check_ask(self):
        """An open ask is never asked again: with the bead unchanged the run waits; a change (the owner's comment or edit) or a
        filed answer answers it, and the run goes on from its checkpoint."""
        state, a = raiser.check(self.stores.asks, self.bead, self.brief_hash, self.fresh, time.time())
        if state == "wait" and a:
            raise Blocked(raiser.waiting_line(a), kind=oc.Kind.WAIT_ASK)
        if state == "answer" and a:
            self.answered = a
            self.briefs.export()  # the brief the workers read now carries the owner's answer
            self.log.note("ask %s (%s) is answered: %s" % (a.id, a.kind.value, "the owner's answer is filed on it" if a.answer
                                                           else "the bead changed since it was asked"))

    def raise_ask(self, spec, why, kind):
        """File the ask the stop carries. Lint decides whether it is one an owner can answer: if not, nothing is filed and the stop is
        the engine's own fault, never a prose question. -> the Ask, or None."""
        common = self.git("rev-parse", "--path-format=absolute", "--git-common-dir")
        at = raiser.Asking(bead=self.bead, run=self.log_path.stem, brief_hash=self.brief_hash, now=time.time(), why=why,
                           repo=str(Path(common).parent) if common else str(self.wt), title=self.bead_title)
        a, problems = raiser.raise_ask(self.stores.asks, spec, at)
        if a is None:
            self.warn("the ask is not one an owner can answer (%s): %s" % ("; ".join(problems), spec.decision[:200]))
            return None
        moved = raiser.leave_queue(self.store, self.bead, self.cfg.pick_label or "", self.cfg.needs_info_label or "") if (
            a.kind.value in ("decision", "ticket") and not self.dry) else ""
        self.comment(asktext.comment(a) + moved)
        return a

    def review_cap(self):
        """A run's reviews are counted once for the whole run, a replan does not start them again (engine.max_total_reviews)."""
        cap = int(self.cfg.max_total_reviews)
        if cap and self.stats["reviews"] > cap:
            raise Blocked("%d reviews in this run (the limit is %d, replans included): it needs the owner's hint\n%s" % (
                self.stats["reviews"], cap, self.stuck_why[:600]),
                          askspecs.open_question("%d reviews ran in this run (the limit is %d, replans included). %s" % (
                              self.stats["reviews"], cap, self.stuck_why[:600]), None), kind=oc.Kind.ASK_STUCK)

    def stoppable_checks(self, *a, **kw):  # run_checks, then a stop (it ended a check, which reports itself failed) ends the run here
        run = self.run_checks(*a, **kw)
        self.halt_point()
        return run

    def run_checks(self, st, name, acceptance_first=False, groups=None, conflict_fix=None, **meta):
        """One engine step, no AI: the repo's checks and the stage's acceptance checks (Checker.run). -> the round's CheckRun."""
        try:
            run = self.checker.run(st["checks"], name, markers=self.MARKERS, acceptance_first=acceptance_first, groups=groups,
                                   conflict_fix=conflict_fix, **meta)
        except CheckFault as e:
            raise Blocked(e.text, kind={CheckFaultKind.STALE_BASE: oc.Kind.FAULT_STALE_BASE, CheckFaultKind.KILLED: oc.Kind.PAUSE_KILLED}[e.kind])
        except CheckStuck as e:
            self.assert_tree("checks", "after")
            raise Blocked("the same checks failed with the same output in %d rounds in a row: more writes will not fix them; it needs the "
                          "owner's hint\nsignature: %s\n%s" % (e.rounds, e.signature[:400], check_evidence.failure_brief(self.checker.reds(), self.run_dir)),
                          askspecs.no_progress("the same red checks", e.rounds, e.signature),
                          kind=oc.Kind.ASK_STUCK)
        self.assert_tree("checks", "after")
        return run

    MARKERS_ARGV = ["python3", str(Path(__file__).with_name("markers.py"))]  # exit 1 and the lines when a conflict marker is in the tree
    MARKERS = text_of(MARKERS_ARGV)

    # -- look and feel (tl-bxk.10.23): screenshots for a visual change, judged by the agent, held for the owner's batch
    # -- tl-bxk.13.15: visual work. The engine renders, a look judge judges, the owner decides taste (docs/design/visual-work.md)
    stop_deferred = staticmethod(halting.stop_deferred)



CHECK_ROUNDS_DAYS = 14


def prune_check_rounds(runs, days=CHECK_ROUNDS_DAYS):
    """Every round's check log (NN-id.rK.log) of a run older than `days` goes; plans, briefs and evidence stay."""
    cut = time.time() - days * 86400
    for f in runs.glob("*/checks/*.r*.log"):
        try:
            if re.search(r"\.r\d+\.log$", f.name) and f.stat().st_mtime < cut:
                f.unlink()
        except OSError:
            pass


engine_written = intake.engine_written  # what the engine (or a receipt of ours) wrote into a bead is never the owner's (tl-7y6.6.2)


def question_spec(out):
    """The ask a worker's question makes: its text and the options it offered."""
    return askspecs.open_question(out["question"], out.get("options"))


LINK_CAP = 200  # links opened per review



def context_tokens(path, tail=1 << 20):
    """-> the input tokens (cache included) of the last turn in a worker's transcript, or None: Claude's last assistant message
    usage, Codex's last token_count, OpenCode's last assistant message tokens (`opencode:ses_...`, read from its DB). The
    answer's own `tokens` add up every turn of the call, so they say nothing of the size."""
    if opencode.opencode_id(path):
        return opencode.opencode_context(opencode.opencode_id(path))
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - tail))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except (OSError, TypeError, ValueError):
        return None
    for line in reversed(lines):
        if '"usage"' not in line and '"token_count"' not in line:
            continue
        try:
            rec = json.loads(line)
            if rec.get("type") == "assistant" and not rec.get("isSidechain"):
                u = rec["message"]["usage"]
                return sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
            if (rec.get("payload") or {}).get("type") == "token_count":
                return int(rec["payload"]["info"]["last_token_usage"]["input_tokens"])
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    return None


def say(line):
    """Print whatever the console can show (a console may not print ⚠): never crash on output."""
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(line.encode(enc, "replace").decode(enc), flush=True)


class Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def details(node, d):
    if node == "plan":
        return (["%d. %s%s → checks: %s" % (n + 1, s["goal"], " (hard)" if s["hard"] else "", "; ".join(s["checks"]))
                 for n, s in enumerate(d["stages"])] + ["risk: %s → %s" % (r["what"], r["check"]) for r in d["risks"]])
    if node == "write":
        return ["ran `%s` exit %d" % (c["cmd"], c["exit"]) for c in d["checks_run"]] + (
            ["question: " + d["question"]] if d["question"].strip() else []) + (
            ["decided by: " + d["decided"]] if d["decided"].strip() else [])
    if node == "review":
        return (["%s %s:%s %s" % (f["severity"], f["file"], f["line"], f["fix"]) for f in d["findings"]] +
                ["unmet: " + u for u in d["unmet"]] + ["leftover: " + lo["title"] for lo in d["leftovers"]] +
                (["question: " + d["question"]] if d["question"].strip() else []) +
                (["decided by: " + d["decided"]] if d["decided"].strip() else []))
    if node == "verify":
        return ["%d %s: %s" % (a["n"], a["verdict"], a["evidence"] or a["why"]) for a in d["items"]]
    if node == "look":
        return ["%s %s%s: %s" % (f["verdict"], f["item"], (" (%s)" % f["where"]) if f["where"] else "", f["why"]) for f in d["findings"]]
    return []


def summarize(node, d):
    if node == "plan":
        return "%d stages, %d risks: %s" % (len(d["stages"]), len(d["risks"]), d["summary"][:200])
    if node == "write":
        return d["summary"][:300]
    if node == "review":
        return "%d findings, %d unmet" % (len(d["findings"]), len(d["unmet"]))
    if node == "verify":
        return ", ".join("%d %s" % (sum(a["verdict"] == k for a in d["items"]), k) for k in VERDICTS)
    if node == "look":
        return "%d defects, %d pass: %s" % (sum(f["verdict"] == "defect" for f in d["findings"]),
                                           sum(f["verdict"] == "pass" for f in d["findings"]), d["summary"][:200])
    return ""


# ---- prompts (one copy each; the per-node instructions of the design) -----------------------------------------------


MAX_REBASE_RESETS = 2   # per bead, across runs (tl-19i)
















# ---- entry ----------------------------------------------------------------------------------------------------------

def busy_elsewhere(repo, actor, bead_id, store=None):
    """True when `actor` holds a slot (it is a loop) that a run of ANOTHER bead holds now: then its claim on `bead_id` is a claim
    it left, not one it works on."""
    now_t = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for sb in wslots.slot_beads(repo, store):
        if sb.assignee == actor and sb.status == "in_progress" and (sb.lease_expires_at or now_t) >= now_t:
            held = sb.metadata.get("held_bead")
            if held and held != bead_id:
                return True
    return False


def reclaim(bead_id, repo, store=None, at=None):
    """(ok, why): run-task takes back what the engine itself left, never what a person holds. A claim by a tl- actor
    whose lease ran out is released (a restarted Claude session gets a new actor name). A bead the engine blocked is
    reopened for a plain retry, or when a comment after the block answers the open ask; it stays blocked when a person
    commented after the block with no ask open (they may have parked it), while an ask waits unanswered, or while
    another bead blocks it."""
    store = store or beadtools.bd_store(repo)
    b = beadtools.peek(store, bead_id) or Bead(id=bead_id, title="", status="")
    who, me = b.assignee, ident.actor()
    if intake.held(b.metadata, at or time.time()):
        return False, "held by the owner (%s): `tl hold %s --release` lets it go" % (b.metadata[intake.HOLD], bead_id)
    release = False
    if who and who != me:
        if not who.startswith("tl-"):
            return False, "claimed by %s" % who
        import loop_env  # the queue rule; imports engine itself
        if b.status == "blocked" or busy_elsewhere(repo, who, bead_id, store):
            # tl-159, tl-kwo: the claim is the actor's, and a loop's actor is live while the loop runs, whatever bead it is on:
            # lifesim-o67g was 'a live claim' of the loop that was running fld.27.12, and its answered ask waited an hour. A bead
            # a loop has left (parked, or the loop went on to another) is live only if an engine is running it now.
            live = bead_id in loop_env.running(repo, store)
        else:  # a session working by hand: its lease and heartbeat are the only sign
            live = who in wslots.live_actors(repo, store) or b.lease_expires_at >= time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if live:
            logs = sorted((ident.config_dir() / "engine").glob("%s-*.jsonl" % bead_id))
            return False, "another run of %s is still running as %s (a live claim)%s" % (
                bead_id, who, "; its engine log: %s" % logs[-1] if logs else "")
        release = True
    reopen = False
    if b.status == "blocked":
        held = [d.id for d in b.dependencies if d.type == "blocks" and d.status != "closed"]
        if held:
            return False, "blocked by %s" % ", ".join(held)
        cs = store.comments(bead_id)
        blocks = [c for c in cs if c.text.startswith("Blocked:")]
        if not blocks:
            return False, "blocked by a person, not by the engine"
        after = [c for c in cs if c.created_at > blocks[-1].created_at and not engine_written(c.text)]
        ask = AskStore.at(ConfigDir(ident.config_dir())).get(bead_id)
        asking = ask is not None and ask.consumed is None and ask.status in (AskStatus.OPEN, AskStatus.PARKED, AskStatus.ANSWERED)
        if ask is not None and asking and ask.answer is not None:  # tl-gy4: an answer filed on the ask (dashboard, tl ask answer) is an answer
            after, asking = [], False  # whether or not a comment followed the block; the run's check_ask consumes it
        if asking and not after:
            return False, "waiting for the answer to ask %s (%s)" % (ask.id, ask.kind.value)
        if after and not asking:
            return False, "%s commented after the engine blocked it; read that first" % (after[-1].author or "someone")
        reopen = True
    if reopen or release:
        # tl-kwo: only if the claim is still the one just read (bd applies --if-assignee atomically): two loops looking at one freed bead
        # must not both release and then both claim
        guard = ["--if-assignee", who] if who and who != me else []
        try:
            store.update(bead_id, BeadPatch(status="open" if reopen else "", if_assignee=who if guard else "", assignee=""))
        except BdFailure:
            if guard:
                return False, "the claim of %s changed hands just now (%s no longer holds it): not taken" % (bead_id, who)
    return True, ("reopened" if reopen else "released %s" % who if release else "")


def append_output(stream):
    """Write a stream that is a file at the end of that file, wherever another writer left it: a second
    `run-task ... > log` on the same log truncates it, and a live run writing on at its old offset leaves a hole of NUL
    bytes (lifesim-gfr.31.1). A terminal, a pipe or a stream with no descriptor is left as it is."""
    try:
        fd = stream.fileno()
        regular = stat.S_ISREG(os.fstat(fd).st_mode)
    except (OSError, ValueError):  # no descriptor (a captured stream) or a closed one: nothing to keep in order
        return
    if regular:
        fcntl.fcntl(fd, fcntl.F_SETFL, fcntl.fcntl(fd, fcntl.F_GETFL) | os.O_APPEND)


def pause_line(rec):
    """A paused run's one line for whoever reran it by hand: the exact time the lane is back (tl-bxk.10.6)."""
    if rec.get("outcome") != "paused":
        return ""
    due = float(rec.get("retry_after") or 0)
    if not due:
        return "PAUSED %s: no time the lane frees (login, network or setup); rerun when fixed: tl run-task %s" % (
            rec.get("bead"), rec.get("bead"))
    return "PAUSED %s: the lane is back at %s; rerun then: tl run-task %s" % (
        rec.get("bead"), time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(due)), rec.get("bead"))


def report(a, rec):
    """The outcome as the run's last stdout line, and in --outcome-file when the loop names one."""
    line = json.dumps(rec, ensure_ascii=False)
    if getattr(a, "outcome_file", None):
        tmp = Path(a.outcome_file + ".tmp")
        tmp.write_text(line + "\n", encoding="utf-8")
        os.replace(tmp, a.outcome_file)
    say(line)


def main(a, store=None):
    try:
        rc = run_main(a, store)
    except Blocked as b:  # a stop (SIGTERM) before the engine ran: the slot and the lock are already given back
        rc = {"v": 1, "outcome": "failed", "bead": a.id, "why": b.why, "kind": b.kind.value if b.kind else ""}
    if isinstance(rc, dict):  # stopped before the engine ran: nothing in the bead changed
        report(a, rc)
        return 1
    return rc


def run_main(a, store=None):
    with halting.halt_on_sigterm():
        return run_main_stoppable(a, store)


def run_main_stoppable(a, store=None):
    for f in (sys.stdout, sys.stderr):
        append_output(f)
    if not os.environ.get("TASK_LOOP_SESSION") and not ident.session_id():
        os.environ["TASK_LOOP_SESSION"] = "engine-" + uuid.uuid4().hex[:12]
    repo = gitrepo.repo_root()
    cfg = wslots.load_cfg(repo)
    if a.slot == "any":
        return run_any_slot(a, repo, cfg, store)
    return run_in(a, repo, cfg, store)


def run_any_slot(a, repo, cfg, store=None):
    """--slot any: the next free slot, taken in the repo's slot line (first come, first served; --wait: wait in it),
    run there as `--slot NAME`, given back at the end."""
    if a.dry_run:
        return {"v": 1, "outcome": "failed", "bead": a.id, "why": "failed: --slot any takes a slot; name one for --dry-run"}
    wait = bool(getattr(a, "wait", False))
    told = []

    def waiting(ahead):
        if not told:
            say("no free slot%s; waiting in line" % (" (%d ahead)" % ahead if ahead else ""))
            told.append(1)
    halt = halting.RUN_HALT["ev"] or threading.Event()
    got = wslots.wait_slot(repo, wslots.profile_slots(repo), "run-task " + a.id, stop=lambda: not wait or halt.is_set(), sleep=halt.wait,
                           on_wait=waiting, prio=wslots.bead_priority(repo, a.id, store), store=store)
    if not got and halt.is_set():
        raise Blocked("failed: stopped (SIGTERM)", kind=oc.Kind.PAUSE_KILLED)  # run_bead's caller reports it; no slot was taken
    if not got:
        why = "no free slot (tl slot list); --wait waits in line for one"
        print("TAKEN: %s" % why)
        return {"v": 1, "outcome": "taken", "bead": a.id, "why": why}
    a.slot, a.worktree, sb = got
    os.environ["TASK_LOOP_SLOT_BEAD"] = sb  # run_in sees the slot as taken; the engine heartbeats it
    halting.RUN_SLOT["owned"] = a.slot  # a re-exec hands the slot on (TL_REEXEC) and its next run-task gives it back
    try:
        return run_in(a, repo, cfg, store)
    finally:
        old = signal.signal(signal.SIGTERM, signal.SIG_IGN) if hasattr(signal, "SIGTERM") and \
            threading.current_thread() is threading.main_thread() else None
        try:
            os.environ.pop("TASK_LOOP_SLOT_BEAD", None)
            wslots.release_slot(repo, a.slot, bead=a.id, mine=True, store=store)
        finally:
            if old is not None:
                signal.signal(signal.SIGTERM, old)


def take_area(a, repo, cfg, lock, sb="", store=None):
    """The engine lock, with the area check before it under the area lock (loop_env.area_lock): "" when this run holds the
    worktree, else why not. A bead whose area runs elsewhere: a warning, or refused with --exclusive-area."""
    import loop_env  # the queue rule; imports engine itself

    def mark():  # the slot says which bead runs in it (held_bead makes its area busy): only once the area is decided
        if sb:
            beadtools.attempt((store or beadtools.bd_store(repo)).update, sb, BeadPatch(set_metadata={"held_bead": a.id}))
    if not loop_env.has_areas(cfg):
        why = lock.take()
        if not why:
            mark()
        return why
    with loop_env.area_lock(repo):
        area, busy = loop_env.area_busy(repo, cfg, beadtools.peek(store or beadtools.bd_store(repo), a.id) or Bead(id=a.id, title="", status=""))
        if busy and getattr(a, "exclusive_area", False):
            return busy + " (--exclusive-area)"
        if busy:
            say("⚠ %s: running anyway beside it; --exclusive-area refuses instead" % busy)
        why = lock.take()
        if not why:
            mark()
        return why


def _handed_slot(slot):
    """True when TL_REEXEC (set by the run-task that exec'd into this one, not yet read by the Engine) says it took `slot` itself."""
    try:
        return json.loads(os.environ.get("TL_REEXEC") or "{}").get("owned") == slot
    except (ValueError, AttributeError):
        return False


def run_in(a, repo, cfg, store=None):
    wt = a.worktree
    if not wt and a.slot:  # the slot is the worktree
        wt = wslots.slot_dir(repo, a.slot, wslots.profile_slots(repo))
    if not wt:
        r = subprocess.run([sys.executable, str(Path(__file__).with_name("tl.py")), "worktree", "start"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        wt = r.stdout.strip().splitlines()[-1] if r.returncode == 0 and r.stdout.strip() else ""
        if not wt:
            print("tl: no worktree: " + r.stderr, file=sys.stderr)
            return {"v": 1, "outcome": "failed", "bead": a.id, "why": "failed: no worktree: " + r.stderr[-300:]}
    wt = str(Path(wt).resolve())
    if (Path(wt) / ".git").is_dir():  # the main checkout holds the bead database and the config: never a worker's cwd
        print("tl: %s is the main checkout; run a task in a slot or a worktree (tl slot / tl worktree start)" % wt,
              file=sys.stderr)
        return {"v": 1, "outcome": "failed", "bead": a.id, "why": "failed: %s is the main checkout" % wt}
    if a.dry_run:
        return run_bead(a, repo, cfg, wt, store)
    took = ""
    try:
        # a hand run takes its slot's bead as the loop does (a --worktree that is a slot too); one the loop started has
        # it already: TASK_LOOP_SLOT_BEAD names that very slot's bead
        slot = a.slot or wslots.slot_of(repo, wt, store)
        sb = getattr(wslots.slot_bead(repo, slot, store), "id", "") if slot else ""
        if slot and sb and os.environ.get("TASK_LOOP_SLOT_BEAD") == sb and _handed_slot(slot):
            took = sb  # exec'd by the run-task that took this slot: it is still ours, and this process gives it back
            halting.RUN_SLOT["owned"] = slot
        elif slot and not (sb and os.environ.get("TASK_LOOP_SLOT_BEAD") == sb):
            took, why = wslots.take_named_slot(repo, slot, wslots.profile_slots(repo), "run-task " + a.id, store=store)
            if not took:
                print("TAKEN: %s" % why)
                return {"v": 1, "outcome": "taken", "bead": a.id, "why": why}
            os.environ["TASK_LOOP_SLOT_BEAD"] = took  # the engine's heartbeat keeps it
            halting.RUN_SLOT["owned"] = slot
        lock = engine_lock.EngineLock(wt, a.id, slot)
        busy = take_area(a, repo, cfg, lock, took or sb if slot else "", store)
        if busy:
            why = busy if busy.startswith("area ") else "worktree %s: %s" % (wt, busy)
            print("TAKEN: %s" % why)
            return {"v": 1, "outcome": "taken", "bead": a.id, "why": why}
        engine_lock.LOCK = lock
        return run_bead(a, repo, cfg, wt, store)
    finally:
        old = signal.signal(signal.SIGTERM, signal.SIG_IGN) if hasattr(signal, "SIGTERM") and \
            threading.current_thread() is threading.main_thread() else None
        try:
            if engine_lock.LOCK:
                engine_lock.LOCK.release()
                engine_lock.LOCK = None
            if took:
                os.environ.pop("TASK_LOOP_SLOT_BEAD", None)
                wslots.release_slot(repo, slot, bead=a.id, mine=True, store=store)
        finally:
            if old is not None:
                signal.signal(signal.SIGTERM, old)


defer_stop = halting.stop_deferred  # no state: also before an Engine exists


def run_bead(a, repo, cfg, wt, store=None):
    # a stop during the reclaim and claim waits for them, then the engine closes the run as stopped (trace, bead)
    with defer_stop(None) as stop:
        if not a.dry_run:
            ok, why = reclaim(a.id, repo, store)
            if not ok:
                print("TAKEN: %s" % why)
                return {"v": 1, "outcome": "taken", "bead": a.id, "why": why}
            if why:
                say("%s: %s" % (a.id, why))
        if not a.dry_run and verbs.claim(a.id, wt, a.slot, store=store) != 0:
            # bd lets this session re-claim its own bead (a reopened one); another session's claim stops here
            return {"v": 1, "outcome": "taken", "bead": a.id, "why": "claimed by another session"}
        eng = Engine(a.id, wt, cfg, dry_run=a.dry_run, verbose=not getattr(a, "quiet", False), fresh=bool(getattr(a, "fresh", False)), store=store)
        eng.stop_pending = bool(stop)
        say("engine log: %s" % eng.log_path)
    rc = eng.run()
    with defer_stop(None):  # the outcome line is what the loop reads: a stop waits for it
        rec = eng.result()
        if pause_line(rec):
            say(pause_line(rec))
        report(a, rec)
    return rc
