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

from core import enginelock, fmt
from taskloop.adapters import applog
from taskloop.domain.report import matchers as lifecycle
from taskloop.adapters import links
from taskloop.adapters import looks
import loop_health
from types import SimpleNamespace
import outcome as oc
import seams
import tl
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
from taskloop.app.run import trace as runtrace
from taskloop.app.write.handoff import Handoff
from taskloop.app.write.stage_loop import StageLoop
from taskloop.app.run.calls import timing
from taskloop.app.run.resume import Resume
from taskloop.app.land.closer import Closer
from taskloop.app.land.fixer import Fixer
from taskloop.app.land.lander import Lander
from taskloop.app.land.rebase import Rebase
from taskloop.app.land.tree import Tree
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



def plugin_version():
    """This engine's task-loop version, from the plugin.json next to it ('' when it is run from a bare copy)."""
    try:
        return str(json.loads((Path(__file__).resolve().parents[2] / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")).get("version") or "")
    except (OSError, ValueError, IndexError):
        return ""


# ---- moving to a newer install between steps (tl-7y6.9): by exec only, no module is ever reloaded in place ----------------------------
RELOAD_FALLBACK_S = 120  # a run-task that dies this soon after an exec is put back on the version it came from (by the loop)
RUN_SLOT = {"owned": ""}  # the slot this process took itself (run_in, run_any_slot) and gives back at the end


def reexec_path(bead):
    return tl.config_dir() / "reexec" / ("%s.json" % bead)


def read_reexec(bead):
    """The note an engine leaves just before it execs into a newer install: {run, from, to, from_dir, t}; {} when none."""
    try:
        rec = json.loads(reexec_path(bead).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return rec if isinstance(rec, dict) else {}


def drop_reexec(bead):
    with contextlib.suppress(OSError):
        reexec_path(bead).unlink()


def net_pause_path(bead):
    return tl.config_dir() / "pauses" / ("%s.json" % bead)


def take_net_pause(bead):
    """The note a run leaves when it pauses for the network ({run, bead, t}), taken once; {} when there is none, it is older
    than NET_PAUSE_ADOPT_S, or the run it names is gone."""
    p = net_pause_path(bead)
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    with contextlib.suppress(OSError):
        p.unlink()
    if not isinstance(rec, dict) or not isinstance(rec.get("run"), str) or time.time() - float(rec.get("t") or 0) > NET_PAUSE_ADOPT_S:
        return {}
    return rec if (tl.config_dir() / "runs" / rec["run"] / "pause.json").is_file() else {}


def take_reexec_env():
    """The hand-over an exec'd (or fallback) run-task finds in TL_REEXEC: {run, bead, from, owned}; {} on a normal start."""
    raw = os.environ.pop("TL_REEXEC", "")
    try:
        rec = json.loads(raw) if raw else {}
    except ValueError:
        return {}
    return rec if isinstance(rec, dict) and isinstance(rec.get("run"), str) else {}


def reexec_args(argv, slot, wt):
    """run-task's own argv with its slot and worktree made explicit (`--slot any` has resolved to a slot) and --fresh/--wait
    dropped (a re-exec goes on from the checkpoint, never from the start). None when argv is not a run-task command line."""
    if not argv or argv[0] != "run-task":
        return None
    out, skip = [], False
    for x in argv:
        if skip:
            skip = False
        elif x in ("--slot", "--worktree"):
            skip = True
        elif x.startswith(("--slot=", "--worktree=")) or x in ("--fresh", "--wait"):
            pass
        else:
            out.append(x)
    return out + (["--slot", slot] if slot else []) + ["--worktree", str(wt)]


def vet_newer():
    import loop_env  # imports engine itself
    return loop_env.vet_newer()


class Exec(BaseException):
    """Raised after a test's injected exec function returns (the real exec never does): unwinds run() without its close."""


def exec_in_place(argv):
    applog.close_all()
    os.execv(sys.executable, argv)


# tl-bxk.13.16.4: a push that died of the network (lifesim-l4ow: curl 56 broken pipe, after a 17 min hook) is retried with a rest
TRANSIENT_PUSH = re.compile(r"curl \d+|Broken pipe|Connection (?:reset|timed out|refused)|Could not resolve host|early EOF|RPC failed|"
                            r"remote end hung up|SSL_ERROR|TLS|Operation timed out|Network is unreachable|"
                            r"Temporary failure in name resolution|error: 5\d\d|HTTP/\d(?:\.\d)? 5\d\d", re.I)
# tl-fsj: a configured check that fails because the tree lacks what the base's config names is the engine's, never a writer's amend


def same_dir(a, b):
    """The same folder: os.path.samefile, realpath equality when either path is missing."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.realpath(str(a)) == os.path.realpath(str(b))


_TREE_MEMO = {}   # (slot, what the config files and environment are now) -> tree_problem's answer


def tree_problem(wt):
    """(what is wrong, the owner's fix) when git at `wt`, read as ambient config has it, is not that checkout; else None.
    Two git calls, none while the config files are as they were: a run asks eleven times."""
    key = tl.config_key(wt)
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
    if not top or not same_dir(top, wt):
        return ("git's top-level folder is %s, not the slot %s" % (top or "(none)", wt),
                "Something redirects git away from the slot. Check `git config --show-origin --list` in %s for "
                "core.worktree or core.bare; `git config --unset core.worktree` in %s if set." % (wt, repo))
    return None


# ---- the engine -----------------------------------------------------------------------------------------------------

LINT_FILLER = {
    "acceptance criteria": "- The follow-up named in the title is done, and the checks of the code it touches pass.",
    "touches": "Not known yet: the writer who picks this up names the files it changes (found while working on %(bead)s).",
    "steps to reproduce": "See the description above (found while working on %(bead)s); the reproduction is not recorded.",
}


def with_sections(body, headings, bead):
    """The description with each missing section appended (a filler that says so, never an invented fact)."""
    have = {h.lower() for h in re.findall(r"^##\s*(.+?)\s*$", body or "", re.M)}
    add = ["## %s\n%s" % (h, LINT_FILLER.get(h.lower(), "(not recorded: found while working on %(bead)s)") % {"bead": bead})
           for h in headings if h.lower() not in have]
    return (body or "").rstrip() + ("\n\n" + "\n\n".join(add) if add else "")


NET_PAUSE_ADOPT_S = lp.KNOBS["net_pause_max_s"]  # a run paused for the network is taken up again by the next run-task within this long


class TreeHashError(RuntimeError):
    """git could not say what the worktree would commit (read-tree, add or write-tree failed): no hash beats a hash of a half-built index."""


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
        self.bead, self.wt, self.cfg, self.dry, self.verbose, self.store, self.router, self.repo = bead, wt, cfg, dry_run, verbose, store or tl.bd_store(), route, git
        self.stats = {"writes": 0, "rounds": 0, "reviews": 0, "replans": 0, "nodes": 0, "tests_added": 0, "tests_removed": 0,
                      "tokens_in": 0, "tokens_cached": 0, "tokens_out": 0}
        self.session, self.fresh = tl.session_id(), fresh
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
        d = tl.config_dir() / "engine"
        d.mkdir(exist_ok=True)
        self.reexec = take_reexec_env()  # this run-task came from an exec into a newer install, or a fallback to the older
        if self.reexec.get("bead") != bead:
            self.reexec = {}
        pause = {} if self.reexec else take_net_pause(bead)  # a run paused for the network: its run id and counters go on
        stem = self.reexec.get("run") or pause.get("run")  # the same run id: log, run dir and trace go on
        if not stem:  # a fresh run has its own id, also when the last run of this bead began in the same second: the stamp moves on
            t0, n = time.time(), 0
            while True:
                stem = "%s-%s" % (bead, time.strftime("%Y%m%d-%H%M%S", time.localtime(t0 + n)))
                if not ((d / (stem + ".jsonl")).exists() or (tl.config_dir() / "runs" / stem).exists()):
                    break
                n += 1
        self.log_path = d / (stem + ".jsonl")
        self.err_path = d / (stem + ".stderr")
        self.exec_fn, self.newer_fn, self.argv, self.moved = None, None, None, False  # a test's exec, newer-install lookup and run-task argv
        # Engine files (brief, plan, node answers, check results) live outside the worktree, where no worker can write
        # them; in lifesim-vbo a writer's sandbox runs kept in .task/ were read as engine results by four planners.
        self.run_dir = tl.config_dir() / "runs" / self.log_path.stem
        self.run_dir.mkdir(parents=True, exist_ok=True)
        prune_check_rounds(tl.config_dir() / "runs")
        self.task_dir = Path(wt) / ".task" / bead  # the writer's: only evidence/ lives here
        self.task_dir.mkdir(parents=True, exist_ok=True)
        self.brief_file = self.task_dir / "brief.md"  # the brief as the writer can re-read it: the engine's copy stays in run_dir
        self.evidence_dir = self.task_dir / "evidence"  # the writer's proof of what the engine cannot rerun
        self.evidence_dir.mkdir(exist_ok=True)
        self.stores = stores or real_stores(ConfigDir(tl.config_dir()))
        self.ctx = RunContext.open(bead, cfg, Path(wt), stem, self.run_dir, self.stores, store, route, self.clock, self.sessions, self.stats,
                                   tl.opencode_id, context_tokens, say, verbose, dry_run, lambda: time.time(), self.assert_tree,
                                   lambda text: tl.event("stage", bead, text=text))
        c: Any = self.ctx
        self.log, self.steps, self.budget, self.calls, self.checklog = c.log, c.steps, c.budget, c.calls, c.checklog
        self.checker = Checker(self, lambda secs: time.sleep(secs))
        self.delegate_route(quiet=True)
        if self.reexec:
            self.restore_run()
        elif pause:
            self.restore_run("pause.json")
            self.log.note("back from a network pause: run %s goes on" % stem)

    # the budget's numbers, read and set as the engine's own (waited: seconds spent waiting for a shared resource, not budget_min's)
    t0, waited, labels, cost = (property(lambda obj, k=k: getattr(obj.budget, k), lambda obj, v, k=k: setattr(obj.budget, k, v))
                                for k in ("t0", "waited", "labels", "spent"))

    def restore_run(self, name="reexec.json"):
        """The counters of the run that exec'd (run_dir/reexec.json) or paused for the network (pause.json), so the run's cost,
        time and trace go on across the move; the time between is neither spent nor waited."""
        try:
            c = json.loads((self.run_dir / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(c, dict):
            return
        self.t0 = time.time() - float(c.get("elapsed") or 0)
        self.waited, self.cost = float(c.get("waited") or 0), float(c.get("cost") or 0)
        if isinstance(c.get("stats"), dict):
            self.stats.update(c["stats"])
        self.sessions[:] = c.get("sessions") or []
        self.write_rounds = list(c.get("write_rounds") or [])
        self.steps.n = int(c.get("node_n") or 0)

    def save_net_pause(self):
        """The run paused for the network: its counters and a pointer for the next run-task of this bead, which takes the same
        run id, cost and time budget up again (the pause itself is neither spent nor waited)."""
        counters = {"elapsed": time.time() - self.t0, "waited": self.waited, "cost": self.cost, "stats": self.stats,
                    "sessions": self.sessions, "write_rounds": self.write_rounds, "node_n": self.steps.n}
        try:
            (self.run_dir / "pause.json").write_text(json.dumps(counters), encoding="utf-8")
            net_pause_path(self.bead).parent.mkdir(parents=True, exist_ok=True)
            net_pause_path(self.bead).write_text(json.dumps({"run": self.log_path.stem, "bead": self.bead, "t": time.time()}), encoding="utf-8")
        except OSError as e:
            self.warn("could not keep the network pause for the next run: %s" % e)

    def safe_point(self, step):
        """A step boundary whose checkpoint is current (tl-7y6.9): when a newer task-loop is installed and its selftest
        passes, exec into it and go on with this bead and run from the checkpoint. A refused version stays on this one
        with a red event; the refusal is recorded (bad-versions.json), so the next boundary does not test it again."""
        if self.dry:
            return
        try:
            found = (self.newer_fn or vet_newer)()
        except Exception as e:  # looking for a newer install never stops a run
            self.warn("looking for a newer task-loop failed: %s" % e)
            return
        if not found:
            return
        ver, d, why = found
        here = plugin_version() or Path(__file__).resolve().parents[2].name
        if why:
            self.warn("not moving to task-loop %s at %s: %s; staying on %s" % (ver, step, why, here))
            tl.event("reload_refused", self.bead, who="engine", version=ver, why=why[:300], running=here, step=step,
                     run=self.log_path.stem)
            return
        self.switch(step, ver, d, here)

    def switch(self, step, ver, d, here):
        slot = (enginelock.LOCK.data.get("slot") if enginelock.LOCK else "") or ""
        argv = reexec_args(self.argv if self.argv is not None else sys.argv[1:], slot, self.wt)
        if argv is None:
            self.log.note("not moving to task-loop %s: this run was not started by `tl.py run-task`" % ver)
            return
        run = self.log_path.stem
        self.steps.end("moved")
        counters = {"elapsed": time.time() - self.t0, "waited": self.waited, "cost": self.cost, "stats": self.stats,
                    "sessions": self.sessions, "write_rounds": self.write_rounds, "node_n": self.steps.n}
        try:
            (self.run_dir / "reexec.json").write_text(json.dumps(counters), encoding="utf-8")
            reexec_path(self.bead).parent.mkdir(parents=True, exist_ok=True)
            reexec_path(self.bead).write_text(json.dumps({"run": run, "bead": self.bead, "from": here, "to": ver, "step": step,
                                                           "from_dir": str(Path(__file__).resolve().parent), "t": time.time()}), encoding="utf-8")
        except OSError as e:
            self.warn("not moving to task-loop %s: could not write the hand-over: %s" % (ver, e))
            return
        tl.event("reload", self.bead, who="engine", old=here, new=ver, step=step, run=run, code_dir=str(d))
        self.log.note("moving to task-loop %s (was %s) at %s; run %s goes on from its checkpoint" % (ver, here, step, run))
        self.log.emit(rec.Reload(old=here, new=ver, step=step))
        os.environ["TL_REEXEC"] = json.dumps({"run": run, "bead": self.bead, "from": here, "owned": RUN_SLOT["owned"]})
        for f in (sys.stdout, sys.stderr):
            with contextlib.suppress(Exception):
                f.flush()
        try:
            (self.exec_fn or exec_in_place)([sys.executable, str(d / "skills" / "task-loop" / "tl.py"), *argv])
            self.moved = True
            raise Exec()  # reached only when the exec function is a test's
        except OSError as e:  # exec itself failed: this version goes on where it is
            os.environ.pop("TL_REEXEC", None)
            drop_reexec(self.bead)
            self.warn("could not move to task-loop %s: %s" % (ver, e))

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
        return tl.config_dir() / "checkpoints"

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
        return tl.git(*a, cwd=path)

    def record_land(self, sha):
        tl.cmd_land(Args(id=self.bead, sha=sha, worktree=self.wt))

    def land_lock_path(self):
        return tl.land_lock_path(self.git("remote", "get-url", "origin") or str(self.wt))

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
        return Closer(self, SimpleNamespace(oc=oc, loop_health=loop_health, tl=tl, say=say, outcome_for=outcome_for, node_outcome=node_outcome,
                                            close_move=close_move, reflection_text=reflection_text, why_code=runtrace.why_code, Args=Args,
                                            config_dir=tl.config_dir()))

    def lock_worker(self, started):
        """The worker delegate launched (the live file's first line) goes into the engine lock, so a SIGKILLed engine leaves it findable."""
        if enginelock.LOCK:
            enginelock.LOCK.note(workers=[[started.pid, sproc.proc_start(started.pid) or ""]])

    def lock_workers(self, survivors, started):
        """After a call: the pids that outlived its stop keep the slot busy; none: free."""
        if enginelock.LOCK:
            enginelock.LOCK.note(workers=[[pid, sproc.proc_start(pid) or ""] for pid in survivors])

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
    def origin(self):
        """Why this run started and the run before it: the checkpoint's run when there was one, else the bead's previous
        engine log. answer: an owner's answer to an ask; resume: the checkpoint was used; retry: an earlier run, no
        checkpoint used; fresh: --fresh; first: no earlier run."""
        prev = self.ck_run or self.prev_ck
        if not prev:
            mine = self.log_path.name
            older = sorted(p.stem for p in self.log_path.parent.glob("%s-*.jsonl" % self.bead)
                           if p.name < mine and RUN_STEM.match(p.stem[len(self.bead) + 1:]))
            prev = older[-1] if older else ""
        why = ("reexec" if self.reexec else "fresh" if self.fresh else "answer" if self.answered else "resume" if self.resumed
               else "retry" if prev else "first")
        return {"prev_run": prev, "started_because": lifecycle.normalize_started_because(why, prev),
                "ask": self.answered.id if self.answered else ""}

    def log_run(self):
        """The run record: why it started, once that is known (after the checkpoint is read), or at the close."""
        if self.run_logged:
            return
        self.run_logged = True
        if self.reexec:  # the run record is in the log already (the exec kept the log): a note says what happened
            self.log.note("task-loop %s took over run %s from %s%s" % (plugin_version() or "?", self.log_path.stem, self.reexec.get("from"),
                                                                      " (fallback after a crash)" if self.reexec.get("fallback") else ""))
            return
        self.log.emit(rec.RunStart(run=self.log_path.stem, bead=self.bead, worktree=str(self.wt),
                                   slot=(enginelock.LOCK.data.get("slot") if enginelock.LOCK else "") or None, **self.origin()))

    def reflect_run(self, outcome, why):
        """tl-05s: one cheap read-only call that reflects on this run: what went well and badly (each bad item with its cause class
        and the session it comes from), what wasted tokens or minutes, what to change. Never blocks or changes the outcome: any
        failure, a missing lane, a paused run, a stop, is no reflection. -> the answer dict or None."""
        if not self.cfg.reflect or self.dry or not self.route or self.stop_pending:
            return None
        if not any(s.get("node") in ("write", "review", "verify") for s in self.sessions):
            return None  # a run that only planned has nothing to reflect on
        if why.startswith(("paused:", "waiting:", "failed: infrastructure", "failed: stopped")):
            return None
        try:
            prompt = self.reflect_prompt(outcome, why)
            # a short wait: the close step ignores a stop while this runs (route.py adds 120 s to the limit)
            self.delegate_route()
            req = RunRequest(role="reviewer", brief_path="", cwd=str(self.wt), schema_path="", task=self.bead, parent=self.session,
                             title="%s · reflect" % self.bead, timeout_s=45)
            cid = self.calls.start("reflect", "reflect", "reviewer", False, self.live_n)
            res = dg.call(self.resolved, req, prompt, answers.sent_schema("reflect"), self.router.runner(self.err_path, None, None, self.live("reflect"))).res
            saved = {k: v for k, v in self.stats.items() if k.startswith("tokens_")}
            self.calls.end(cid, "reflect", "reviewer", 1, res)
            self.stats.update(saved)  # the run's counts are the run's, as the Reflect comment says them
            if res.data is None or res.stop is not None:
                return None
            data = unstrict(res.data, answers.schema_for("reflect"))
            if answers.check("reflect", False, data):
                return None
            return data
        except Exception as e:  # nothing here may touch the run's outcome
            self.warn("no reflection: %s: %s" % (type(e).__name__, str(e)[:160]))
            return None

    def reflect_prompt(self, outcome, why):
        rows = []
        for s in self.sessions:
            t = s.get("tokens") or {}
            rows.append("- %s (%s) %s %s: in %s, cached %s, out %s, %ss, session %s" % (
                s.get("node"), s.get("role"), s.get("family") or "?", s.get("model") or "?", t.get("in") or 0, t.get("cached") or 0,
                t.get("out") or 0, s.get("secs"), s.get("ref") or "(none)"))
        lines = ["%s: %s" % (it.rec.KIND, fmt.clip(
            "%s -> %s: %s" % (it.rec.cause, it.rec.to, it.rec.detail) if isinstance(it.rec, rec.Transition) else it.rec.text, 200))
                 for it in JsonlStore(self.log_path, rec.decode).read_from().items if isinstance(it.rec, (rec.Transition, rec.Warn))]
        return REFLECT_PROMPT % (self.bead, fmt.clip(self.bead_title, 120), outcome, fmt.clip(why or "(none)", 600),
                                 "; ".join("%s=%s" % kv for kv in self.stats.items()), "\n".join(rows[:40]),
                                 "\n".join(lines[-70:]) or "(none)")

    def file_trace(self, outcome, why, sha):
        """One line per engine run in traces.jsonl, never pruned: bead, repo, branch, every session, the outcome."""
        kind = self.kind.value if self.kind else ""
        try:
            self.stores.traces.append(runtrace.run_trace(self.log_path.stem, dict(
                self.origin(), bead=self.bead, repo_url=self.git("remote", "get-url", "origin") or str(self.wt), worktree=str(self.wt),
                branch=self.git("symbolic-ref", "--short", "-q", "HEAD"), coordinator_session=self.session, version=plugin_version(),
                started=self.t0, ended=time.time(), outcome=outcome, why=(why or "")[:500], sha=sha or "", kind=kind, kfp=self.fp,
                why_code=runtrace.why_code(kind, outcome), fingerprint=lifecycle.run_fingerprint(outcome, why), cost=self.cost,
                stats=self.stats, delegate_path=self.route or "", log=str(self.log_path), stderr=str(self.err_path),
                sessions=self.sessions, verified=self.verified, write_rounds=self.write_rounds, strays=self.strays,
                reflection=self.reflection, lane_notes=self.lane_notes, salvaged=self.salvaged)))
        except (OSError, ValueError) as e:
            self.warn("could not write the trace: %s" % e)

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
        """tl.os_lock with a wait recorded as its own segment (tl-9h2): the open step ends before the wait starts (it was
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
        with tl.os_lock(path, holder or self.bead, waiting):
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
            steps = run_breakdown(self.log_path, self.steps.cur)
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

    def shot_table(self):
        """The shot methods the repo can render, as the planner and the writer are told them."""
        return looks.table_text(self.shot_methods())

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
        """The stop flag of the running command: set it from any thread and sh() ends the command's whole tree."""
        return threading.Event()

    def sh(self, cmd, timeout=3600, check=False, save=None, env=None, pin=False, what="command", cwd=None):
        """A command: an argv list, exec'd as given (no shell, no quoting rules; a string is a programming error), run by stream-proc
        in a group of its own. It ends by itself, at `timeout` seconds of wall time (exit 124; its tree is stopped), or when
        `self.halt` is set. Nothing else stops it: a quiet command may be waiting. pin=True: an engine git command, run with
        GIT_DIR/GIT_WORK_TREE of the slot; checks and gates run unpinned (they may run git on other repos)."""
        if isinstance(cmd, str):
            raise TypeError("a command is an argv list, never a string: %r" % cmd[:80])
        cid = self.log.next_id("m")
        cwd = cwd or self.wt  # a check on the untouched base runs in its own checkout
        self.log.emit(rec.CmdStart(id=cid, text=text_of(cmd), cwd=str(cwd)))
        started, chunks = time.time(), []
        self.killed = self.wall_hit = False
        try:
            res = stream_proc.run(list(cmd), cwd=cwd, env=dict(sproc.current_env(), **(tl.pinned_env(self.wt) if pin else {}), **(env or {})),
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
        if check and rc:
            raise Blocked("failed: `%s` exit %d\n%s" % (text_of(cmd), rc, tail), kind=oc.Kind.FAULT_INFRA)
        return rc, tail

    def slot_status(self):
        """(tracked paths changed, untracked paths, git's result) from the slot's own `git status`."""
        st = tl.run_git(self.wt, "status", "--porcelain", "-z", "--untracked-files=all", capture_output=True)
        parts, paths, new = st.stdout.decode("utf-8", "surrogateescape").split("\0"), [], []
        k = 0
        while k < len(parts):
            e = parts[k]
            k += 1
            if len(e) > 3:
                (new if e[:2] == "??" else paths).append(e[3:])
                if e[0] in "RC":  # the next entry is the path it came from: gone from the tree, staged already
                    k += 1
        return paths, new, st

    def new_file_kind(self, path):
        """tl-bxk.10.24: "ignored" (engine.untracked_ignore: never staged, never listed), "meant" (a plan stage lists it or
        its folder in files, the writer's answer names it, or a review accepted it) or "unexplained" (left out of the
        commit, listed in the review brief). A .meta follows the file it belongs to."""
        p = path.replace("\\", "/")
        if any(fnmatch.fnmatchcase(p, g) for g in self.cfg.untracked_ignore or []):
            return "ignored"
        if p in self.look_paths or p.startswith(".task/"):  # the look flow's own screenshot copies (copy_looks) are meant
            return "meant" if p in self.look_paths else "ignored"
        for q in (p, p[:-5]) if p.endswith(".meta") else (p,):
            if q in self.accepted_new or q + ".meta" in self.accepted_new or self.writer_names(q):
                return "meant"
            for st in (self.plan_data or {}).get("stages") or []:
                for f in st["files"]:
                    f = f.strip().replace("\\", "/")
                    f = "" if f in (".", "./") else f[2:] if f.startswith("./") else f
                    if f and (q == f or q.startswith(f.rstrip("/") + "/") or fnmatch.fnmatchcase(q, f)):
                        return "meant"
        return "unexplained"

    def writer_names(self, path):
        """The writer's answers name this file: its full path or its basename, on word boundaries (not `ab.md` for `b.md`)."""
        for n in dict.fromkeys((path, path.rsplit("/", 1)[-1])):
            if re.search(r"(?<![\w.-])%s(?![\w-]|\.\w)" % re.escape(n), self.writer_said):
                return True
        return False

    def new_by_kind(self):
        out = {"ignored": [], "meant": [], "unexplained": []}
        for p in self.slot_status()[1]:
            out[self.new_file_kind(p)].append(p)
        return out

    STRAY_LINES, STRAY_CHARS = 80, 6000

    def new_file_view(self, path):
        """tl-bxk.10.24: what the review brief shows of an unexplained new file: its first 80 lines, or "binary, N bytes"."""
        f = Path(self.wt) / path
        try:
            data = f.read_bytes()
        except OSError:
            return "(unreadable)"
        if b"\0" in data[:8000]:
            return "binary, %d bytes" % len(data)
        lines = data.decode("utf-8", "replace").splitlines()
        text = "\n".join(lines[:self.STRAY_LINES])[:self.STRAY_CHARS]
        more = len(lines) - self.STRAY_LINES
        return text + ("\n... (%d more lines)" % more if more > 0 else "")

    def new_files_brief(self, unexplained):
        return NEW_FILES_TEXT + "".join("- %s\n<content>\n%s\n</content>\n" % (p, self.new_file_view(p)) for p in unexplained)

    def undecided_new(self, unexplained, review):
        """The unexplained files the review neither accepted nor rejected (a .meta follows the file it belongs to)."""
        said = set(review.get("accept_files") or []) | set(review.get("reject_files") or [])
        return [p for p in unexplained if p not in said and not (p.endswith(".meta") and p[:-5] in said)]

    def quarantine_strays(self):
        """tl-bxk.10.24: before the land gate, every untracked file that is neither meant nor ignored leaves the tree for
        .task/<bead>/evidence/strays/ (kept), so the gate runs on exactly what is committed. Listed in the trace and on the bead."""
        moved = []
        for p in self.new_by_kind()["unexplained"]:
            dst = self.evidence_dir / "strays" / p
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(Path(self.wt) / p), str(dst))
            moved.append(p)
        if moved:
            self.strays += [p for p in moved if p not in self.strays]
            self.log.note("stray untracked files moved out of the tree to %s: %s" % (self.evidence_dir / "strays", ", ".join(moved)))
            self.comment("Land (engine): untracked files no stage or review accepted were left out of the commit and the gate, "
                         "kept in %s: %s" % (self.evidence_dir / "strays", ", ".join(moved)))
        return moved

    STAGE_DIFF_CAP = 40000

    def stage_work(self, unexplained, ignored):
        """tl-bxk.10.18: the review brief's account of the work: this stage's diff (the tree the stage started from to the
        tree now; the task's base for the first stage), inline up to STAGE_DIFF_CAP chars; over it, the --stat and the
        instruction to read only the changed files plus the plan. Untracked files not meant for the commit are left out."""
        tree = self.tree_hash()
        base = self.stage_tree or self.base_sha()
        if not tree:
            return "The work: `git diff %s` and new files." % base
        skip = ["--", "."] + [":(exclude,literal)" + p for p in unexplained + ignored]
        diff = tl.git("diff", base, tree, *skip, cwd=self.wt)
        if len(diff) <= self.STAGE_DIFF_CAP:
            return ("The work of this stage (the diff from where the stage started to now; earlier stages are in the tree "
                    "but not in this diff):\n<diff>\n%s</diff>" % (diff if diff.endswith("\n") or not diff else diff + "\n")
                    if diff else "The work of this stage: no file changed.")
        stat = tl.git("diff", "--stat", base, tree, *skip, cwd=self.wt)
        return ("The work of this stage is too big to inline (%d chars; the cap is %d). Its changed files:\n%s\nRead only "
                "the changed files plus the plan; do not diff the whole task." % (len(diff), self.STAGE_DIFF_CAP, stat))

    def stage_all(self, check=False, everything=False):
        """Stage the slot's own changes: exactly the paths `git status --porcelain` lists under the pinned env, never a
        bare `git add -A` (tl-bxk.10.12). Tracked changes always; an untracked file only when a stage meant it
        (new_file_kind, tl-bxk.10.24). Returns the exit code."""
        self.log.note("git add -A (the slot's own status paths)")
        paths, new, st = self.slot_status()
        if everything:  # a parked bead's work: every new file the base does not ignore goes to its branch, the unexplained ones too
            ignored = self.base_ignored(new)
            paths += [p for p in new if p not in ignored]
        else:
            paths += [p for p in new if self.new_file_kind(p) == "meant"]
        rc = st.returncode
        if rc == 0 and paths:
            r = tl.run_git(self.wt, "--literal-pathspecs", "add", "-A", "--pathspec-from-file=-", "--pathspec-file-nul",
                           input="\0".join(paths).encode("utf-8", "surrogateescape"), capture_output=True)
            rc = r.returncode
            st = r
        if check and rc:
            raise Blocked("failed: staging the slot's paths exit %d\n%s" % (rc, st.stderr.decode("utf-8", "replace")[-600:]), kind=oc.Kind.FAULT_SLOT)
        return rc

    def fetch(self, check=False):
        """git fetch, again while it loses a ref lock to another process's fetch into this repo (tl.REF_RACE)."""
        for i in range(5):
            rc, tail = self.sh(["git", "fetch", "-q", "origin"], pin=True)
            if rc == 0 or not tl.REF_RACE.search(tail):
                break
            time.sleep(0.1 * (i + 1))
        if check and rc:
            raise Blocked("failed: `git fetch -q origin` exit %d\n%s" % (rc, tail), kind=oc.Kind.FAULT_INFRA)
        return rc, tail

    def git_env(self):
        """The environment for a git command on this checkout (pinned to it)."""
        return tl.git_env(self.wt)

    def base_sha(self):
        """Where the task's work starts: an earlier run's commits on the task branch count as the task's diff."""
        return self.git("merge-base", self.cfg.base, "HEAD") or self.cfg.base

    def git(self, *a):
        return tl.git(*a, cwd=self.wt)

    def branch_now(self):
        """The branch HEAD is on; "" when detached."""
        return self.git("symbolic-ref", "--short", "-q", "HEAD")

    def dirty_status(self):
        """`git status --porcelain` of the slot, leaving out what the BASE's .gitignore files ignore (tl-g6a): Unity's client/log.txt
        is untracked on an old branch and ignored on main, and made a slot 'dirty with another branch's work' for 7 beads."""
        out = self.git("status", "--porcelain", "--untracked-files=all")
        if not out:
            return ""
        lines = out.splitlines()
        untracked = [ln[3:] for ln in lines if ln.startswith("?? ")]
        ignored = self.base_ignored(untracked)
        return "\n".join(ln for ln in lines if not (ln.startswith("?? ") and ln[3:] in ignored))

    def base_ignored(self, paths):
        """The subset of `paths` that the BASE's .gitignore files ignore (the user's own global excludes are not replaced)."""
        if not paths:
            return set()
        rules = []
        base = self.cfg.base
        for path in (self.git("ls-tree", "-r", "--name-only", base) or "").splitlines():
            if path.split("/")[-1] != ".gitignore":
                continue
            d = path[:-len(".gitignore")].rstrip("/")
            for ln in (self.git("show", "%s:%s" % (base, path)) or "").splitlines():
                ln = ln.rstrip()
                if not ln or ln.startswith("#"):
                    continue
                neg, pat = ("!", ln[1:]) if ln.startswith("!") else ("", ln)
                if not d:
                    rules.append(ln)
                elif pat.startswith("/"):
                    rules.append(neg + "/" + d + pat)
                elif "/" in pat.rstrip("/"):
                    rules.append(neg + "/" + d + "/" + pat)
                else:
                    rules.append(neg + "/" + d + "/**/" + pat)
        if not rules:
            return set()
        with tempfile.NamedTemporaryFile("w", suffix=".ignore", delete=False, encoding="utf-8") as f:
            f.write("\n".join(rules) + "\n")
            ex = f.name
        try:
            # check-ignore reads only the rules given
            r = subprocess.run(["git", "-C", str(self.wt), "-c", "core.excludesFile=" + ex, "check-ignore", "--no-index", "--stdin", "-z"],
                               input="\0".join(paths) + "\0", capture_output=True, text=True, encoding="utf-8", errors="replace",
                               env=sproc.current_env())
            return set(r.stdout.split("\0")) if r.returncode in (0, 1) else set()
        finally:
            with contextlib.suppress(OSError):
                os.unlink(ex)

    def add_cases(self, new):
        """A writer may add the cases it discovers; it can never remove one (the plan is the engine's)."""
        cases = self.plan_data.setdefault("cases", [])
        have = {c["check"].strip() for c in cases}
        for c in new:
            if c["check"].strip() and c["check"].strip() not in have:
                cases.append(dict(c, by="writer"))
                have.add(c["check"].strip())
                self.log.note("the writer added a case: %s" % c["criterion"][:200])

    def engine_unproven(self, unchecked, checks):
        """The unchecked items the engine does not prove itself: one that names the gate (it runs at land, and a red gate
        goes to a fix round) or a check that passed this round is dropped, and so is every case item once this round ran
        all the plan's cases green (only the last stage and a fix run them). lifesim-5ban.3 and lifesim-fld.27.3 stopped
        on verify asks for the gate; lifesim-gfr.31.1 on 'there is no nographics.out in evidence yet' after the case
        that writes it passed."""
        ran = [c.cmd for c in checks if c.exit == 0]
        names = [" ".join(x.split()).lower() for x in [self.cfg.gate_text] + ran if x.strip()]
        cases = self.case_checks()
        cases_ran = bool(cases) and all(c in ran for c in cases)
        out = []
        for u in unchecked:
            what = " ".join(u["what"].split()).lower()
            if any(x in what for x in names) or (cases_ran and u["kind"] == "case"):
                self.log.note("unchecked item dropped, the engine runs it: %s" % u["what"][:200])
            else:
                out.append(u)
        return out

    def scope_tokens(self):
        plan = self.plan_data or {}
        text = [self.scope] + [st["goal"] for st in plan.get("stages") or []] + [
            c["criterion"] for c in plan.get("cases") or []] + [r["what"] for r in plan.get("risks") or []]
        return word_set(" ".join(text))

    def out_of_scope(self, items):
        """tl-bxk.13.5: a checkable item a review noted that shares nothing with the bead's done-when, the plan's goals, cases
        and risks is a follow-up, not a gap: it is filed as a leftover and the land goes on (lifesim-f2by: a note about two
        poses nobody asked for became two fix rounds, 93 min). Nothing is dropped unseen: the bead is filed. With no
        acceptance text to compare against, nothing moves."""
        if not self.scope.strip():
            return items
        have, keep = self.scope_tokens(), []
        for u in items:
            toks = word_set(u["what"])
            near = len(toks & have)
            if u["kind"] != "checkable" or near >= 2 or (toks and near / len(toks) >= 0.3):
                keep.append(u)
                continue
            self.log.note("unchecked item outside the done-when, filed as a follow-up: %s" % u["what"][:200])
            title = ("Check: " + u["what"])[:120]
            if title in {lo["title"] for lo in self.leftovers}:
                continue
            self.leftovers.append({"title": title, "why": "A review noted this outside the task's "
                                   "done-when, so it was not verified before the land: " + u["what"][:600]})
        return keep


    def case_checks(self):
        return [c["check"] for c in (self.plan_data or {}).get("cases") or []
                if c.get("check", "").strip() and c.get("class", "test") == "test" and c.get("proved_by", "check") in ("check", "stage")]

    def cases_of(self, cls):
        """The criteria of the plan's cases of one class (look-objective, taste)."""
        return [c["criterion"] for c in (self.plan_data or {}).get("cases") or [] if c.get("class") == cls]

    def cases_text(self):
        cases = (self.plan_data or {}).get("cases") or []
        if not cases:
            return ""
        run = [c for c in cases if c.get("class", "test") == "test"]
        looked = [c for c in cases if c.get("class", "test") != "test"]
        return ("\nThe task's acceptance cases (they run on the last stage; judge whether each proves its criterion):\n" + \
            "".join("- %s: `%s`%s\n" % (c["criterion"], c["check"], " (added by the writer: %s; check it does not replace "
                                                                   "a stronger case)" % c.get("why", "") if c.get("by") == "writer" else "")
                    for c in run) if run else "") + (
            "\nCases judged from rendered pictures, not by a command (the engine's look judge sees them; taste goes to the owner):\n" +
            "".join("- [%s] %s\n" % (c["class"], c["criterion"]) for c in looked) if looked else "")

    def rules_text(self):
        """tl-7y6.6.1: the repo's worker rules (engine.worker_rules), inlined; "" when none. A file over RULES_MAX is cut at a line
        and the engine warns: the limit is hard, so the planner and the writer share one text and nobody reads a path."""
        rel = self.cfg.worker_rules
        if not rel:
            return ""
        try:
            text = (Path(self.wt) / rel).read_text(encoding="utf-8").strip()
        except (OSError, ValueError):
            return ""
        if len(text.encode("utf-8")) > RULES_MAX:
            self.warn("worker rules %s are over %d bytes: only the first lines that fit are sent" % (rel, RULES_MAX))
            text = text.encode("utf-8")[:RULES_MAX].decode("utf-8", "ignore").rsplit("\n", 1)[0].rstrip()
        return text

    def plan_text(self, stage=None):
        """The plan as JSON; with `stage` (0-based) the role-sized view a writer or reviewer of that stage reads."""
        plan = self.plan_data or {}
        return json.dumps(checks_to_wire(plan if stage is None else role_view(plan, stage)), indent=1)

    def comment(self, text):
        if not self.dry:
            tl.attempt(self.store.add_comment, self.bead, text)

    # -- tl-bxk.13.8: notes shared by the tasks of one repo (docs/design/stages.md section 6)
    def shared_path(self):
        common = self.git("rev-parse", "--path-format=absolute", "--git-common-dir") or str(self.wt)
        return tl.config_dir() / "shared" / ("%s.json" % hashlib.sha1(common.encode("utf-8")).hexdigest()[:12])

    def known_flakes(self):
        """[{test, note, bead}]: tests known to fail without cause. A writer reports one (flakes); the owner may edit the file."""
        try:
            data = json.loads(self.shared_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        week2 = time.time() - FLAKE_DAYS * 86400  # a writer's word is not a fact for ever: it lapses unless reported again
        return [f for f in (data.get("flakes") if isinstance(data, dict) else None) or []
                if isinstance(f, dict) and str(f.get("test") or "").strip() and (f.get("t") or 0) >= week2]

    def add_flakes(self, new):
        have = {" ".join(str(f["test"]).split()) for f in self.known_flakes()}
        add = [{"test": " ".join(str(f["test"]).split())[:200], "note": " ".join(str(f.get("note") or "").split())[:300],
                "bead": self.bead, "t": int(time.time())}
               for f in [x for x in new if isinstance(x, dict)][:3] if str(f.get("test") or "").strip()]  # three a write
        add = [f for f in add if f["test"] not in have]
        if not add or self.dry:
            return
        path = self.shared_path()
        try:  # read again just before the write: another slot may have added one meanwhile
            path.parent.mkdir(parents=True, exist_ok=True)
            cur = self.known_flakes()
            seen = {f["test"] for f in cur}
            tmp = path.with_name(path.name + ".%d.tmp" % os.getpid())
            tmp.write_text(json.dumps({"flakes": (cur + [f for f in add if f["test"] not in seen])[-40:]}, indent=1), encoding="utf-8")
            os.replace(tmp, path)
            self.log.note("known flaky: %s" % "; ".join(f["test"] for f in add))
        except OSError:
            pass

    def siblings(self):
        """[(bead, summary, files)]: tasks running in other worktrees of this repo right now (a live engine lock)."""
        out = []
        for line in self.git("worktree", "list", "--porcelain").splitlines():
            if not line.startswith("worktree "):
                continue
            wt = line[len("worktree "):]
            if same_dir(wt, self.wt):
                continue
            lock = tl.read_engine_lock(wt)
            if not lock.get("bead") or lock["bead"] == self.bead or not tl.proc_alive(lock.get("pid"), lock.get("start") or ""):
                continue
            ck = self.stores.checkpoints.of(lock["bead"]).read()
            plan = (ck.state.plan_data if ck else None) or {}
            files = list(dict.fromkeys(f for st in plan.get("stages") or [] for f in st.get("files") or []))
            out.append((lock["bead"], " ".join(str(plan.get("summary") or "").split())[:100], files[:6]))
        return out[:5]

    def landed_since(self):
        """Subjects of what landed on the base since this task's branch left it (as far as the last fetch knows)."""
        log = self.git("log", "--format=%s", "-n", "8", "%s..%s" % (self.base_sha(), self.cfg.base))
        return [x[:100] for x in log.splitlines() if x.strip()]

    def flakes_text(self):
        flakes = self.known_flakes()
        if not flakes:
            return ""
        return ("\nKnown flaky tests of this repo (a writer reported each; they fail without a cause in the change). A check red only on one: run it "
                "once more and say so in your summary; do not build a new isolation or fix for it unless the task is about "
                "it:\n" + "".join("- %s%s%s\n" % (f["test"][:120], (": " + f["note"][:160]) if f.get("note") else "",
                                                    (" (found in %s)" % f["bead"]) if f.get("bead") else "") for f in flakes[-8:]))

    def shared_text(self):
        """What the other tasks of this repo are doing, for the planner and a writer's first prompt: running now, landed since
        this branch left the base, known flaky tests. '' when there is nothing to say."""
        out = []
        sib = self.siblings()
        if sib:
            out.append("Running now beside this task (do not edit their files unless this task needs them; do not redo their work):\n" +
                       "".join("- %s%s%s\n" % (b, (": " + sm) if sm else "", (" [files: %s]" % ", ".join(fs)) if fs else "") for b, sm, fs in sib))
        landed = self.landed_since()
        if landed:
            out.append("Landed on %s since this branch left it:\n%s" % (self.cfg.base, "".join("- %s\n" % x for x in landed)))
        flakes = self.flakes_text()
        return ("\n" + "".join(out) + flakes) if (out or flakes) else ""

    def run(self):
        return self.run_once()

    def run_once(self):
        outcome, why, sha, spec, kind = "failed", "", "", None, oc.Kind.FAULT_ENGINE
        hb = Lease(self.store, self.bead, os.environ.get("TASK_LOOP_SLOT_BEAD", ""))
        ck = self.checkpoints.read()
        self.prev_ck = ck.run if ck else ""
        try:
            if self.stop_pending:  # stopped during the claim (run_bead): close it as stopped
                raise Blocked("failed: stopped (SIGTERM)", kind=oc.Kind.PAUSE_KILLED)
            bead = tl.peek(self.store, self.bead)
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
            self.log.note("task-loop %s" % (plugin_version() or "(unknown version)"))
            self.tree.reset(bead)
            self.budget.labels = list(bead.labels)
            self.check_ask()
            self.planner.cap.grant()
            written = self.planner.cap.answered_words() if self.answered and self.answered.ask_class == AskClass.MISSING_CRITERIA else ""
            if not AcceptanceText.present(bead) and not written:
                raise Blocked("ticket: the bead has no acceptance criteria", askspecs.missing_criteria(), kind=oc.Kind.ASK_TICKET)
            self.scope = AcceptanceText.text(bead) or written
            plan, i, state = self.resume.point()
            self.log_run()
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
                self.safe_point("plan")
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
                    self.safe_point("land")  # the checkpoint says land: the close and the land run on the newest code
            if self.render_stale and self.last_reqs and self.shot_methods() and not self.dry:
                # code changed after the last render (a fix round past the render rounds): the pictures that land show the tree
                self.log.note("rendering the last shots again: code changed since the pictures were made")
                self.render_shots(self.last_reqs, self.look_done + 1)
            gaps = self.self_verify([u for u in self.unchecked if u["kind"] in UNCHECKED_KINDS or self.is_look(u)])
            if gaps:
                raise Blocked("verify: before land, the workers could not check: " + "; ".join(
                    "%s (%s%s)" % (u["what"], u["kind"], ("; " + u["why"]) if u.get("why") else "") for u in gaps),
                    askspecs.external_fact([u["what"] for u in gaps]), kind=oc.Kind.ASK_DECISION)
            sha = self.lander.finish(bead)
            outcome = "landed" if sha else "done"
            kind = oc.Kind.LANDED if sha else oc.Kind.DONE
            if sha:
                self.file_owner_look()  # before the checkpoint goes: a crash from here on still files it on resume
            self.checkpoints.drop()
        except Blocked as b:
            kind = b.kind
            outcome = outcome_for(kind, b.why)
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
                    drop_reexec(self.bead)  # a run that ended is no crash after an exec
                    if kind == oc.Kind.PAUSE_NETWORK and not self.dry:
                        self.save_net_pause()
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
        tree = self.tree_hash()
        return (tl.git("diff", self.base_sha(), tree, cwd=self.wt) if tree else "") or ""

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

    def is_look(self, u):
        return bool(self.visual_cfg()) and Wording.is_look(u["what"])

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

    def promised_missing(self, plan, upto):
        """tl-bxk.13.16.2: the index of the earliest accepted stage (before `upto`) that mentions an evidence file which is gone
        now while a check still to run names it, or None."""
        ev = re.compile(r"\.task/%s/evidence/[^\s\"'<>|;&)]+" % re.escape(self.bead))
        stages = plan.get("stages") or []
        pending = [c for st in stages[upto:] for c in st["checks"]] + [
            x["check"] for x in plan.get("cases") or [] if x.get("check", "").strip() and x.get("class", "test") == "test"]
        need = set()
        for c in pending:
            for p in ev.findall(c):
                if not Path(self.wt, p).exists():
                    need.add(p)
        early = [k for k, st in enumerate(stages[:upto]) if any(p in c for c in st["checks"] for p in need)]
        return min(early) if early else None

    def base_red_text(self, run):
        """What the writer is told of the checks that were red on the untouched base too: they are not its to fix."""
        if not run.base_red:
            return ""
        return ("\nThese checks are red on the untouched base too, so they are not yours; the round does not count them:\n%s\n"
                % "\n".join("- `%s` (exit %s)" % (c.cmd, c.exit) for c in run.base_red))

    def review_cap(self):
        """A run's reviews are counted once for the whole run, a replan does not start them again (engine.max_total_reviews)."""
        cap = int(self.cfg.max_total_reviews)
        if cap and self.stats["reviews"] > cap:
            raise Blocked("%d reviews in this run (the limit is %d, replans included): it needs the owner's hint\n%s" % (
                self.stats["reviews"], cap, self.stuck_why[:600]),
                          askspecs.open_question("%d reviews ran in this run (the limit is %d, replans included). %s" % (
                              self.stats["reviews"], cap, self.stuck_why[:600]), None), kind=oc.Kind.ASK_STUCK)

    def stage_checks_text(self, checks, skip=None):
        """The stage's check list split for the writer: the fast ones it may run, the slow ones the engine runs alone (WriterSplit)."""
        return self.checker.split().text(checks, skip)

    def where(self, node, checks=(), failed=None, listed=()):
        """What the step is for, never what its sandbox allows: delegate tells each worker that (worker-run v3).
        For the writer: which checks it may run (fast ones) and which are the engine's (slow ones), minus `listed` (the
        commands the stage's own check list already names)."""
        if node == "write":
            pool = list(dict.fromkeys(checks)) if failed is None else list(dict.fromkeys(failed))
            if failed is None:  # the stage's own checks are in stage_checks_text: name each command once (tl-7y6.6.12)
                have = {norm_cmd(c) for c in listed}
                pool = [c for c in pool if norm_cmd(c) not in have]
            fast, slow = self.checker.split().divide(pool)
            if failed is None:
                text = ("Before you say it is done, run the stage's fast checks so an error never reaches the engine; the "
                        "engine reruns every check after you.")
            else:
                text = "Only the failed checks that are fast are yours to rerun; the engine reruns every check after you."
            if slow:
                text += ("\nThe engine runs these after you; do not run them:\n" if failed is None else
                         "\nThese failed checks are slow: the engine re-runs them; fix from the output above, do not run them:\n"
                         ) + "".join("- %s\n" % c for c in slow).rstrip("\n")
            if fast:
                text += "\nYou may run these:\n" + "\n".join("- %s" % c for c in fast)
            return (text + "\nIf a command is refused, do not reword it to get around the refusal: say which command and "
                    "why you needed it.\nNever start a command you expect to take over a minute; never poll a running "
                    "command more than 3 times.")
        return "You may run commands to check facts (read files, run a linter or a test); never edit, create or delete files."

    def tree_hash(self):
        """The worktree as git would commit it now, untracked files included, without touching the real index."""
        state = self.tree_state()
        memo = self.tree_memo
        if state and memo and memo[0] == state:
            return memo[1]
        with tempfile.TemporaryDirectory() as d:
            env = dict(tl.git_env(self.wt), GIT_INDEX_FILE=os.path.join(d, "index"))
            for args in (["read-tree", "HEAD"], ["add", "-A"], ["write-tree"]):
                r = subprocess.run(["git"] + args, cwd=self.wt, env=env, capture_output=True, text=True)
                if r.returncode != 0:
                    raise TreeHashError("git %s failed (%d): %s" % (args[0], r.returncode, (r.stderr or "").strip()[:300]))
        if state:
            self.tree_memo = (state, r.stdout.strip())
        return r.stdout.strip()

    def tree_state(self):
        """Everything that decides tree_hash, from one `git status`: HEAD, every path that differs from it or is untracked, and the
        size, mtime, ctime, mode, inode and (small files) content hash of each of those files (status alone says 'modified' before and after a second edit). None when git
        cannot say; a run of tree_hash is then never skipped."""
        r = subprocess.run(["git", "--no-optional-locks", "status", "--porcelain=v2", "--branch", "-z", "--untracked-files=all"],
                           cwd=self.wt, env=tl.git_env(self.wt), capture_output=True)
        if r.returncode != 0:
            return None
        recs = r.stdout.split(b"\0")
        paths, i = [], 0
        while i < len(recs):
            rec = recs[i]
            if rec[:2] in (b"1 ", b"u "):
                paths.append(rec.split(b" ", 8 if rec[:1] == b"1" else 10)[-1])
            elif rec[:2] == b"2 ":
                paths.append(rec.split(b" ", 9)[-1])
                i += 1  # the original path follows as its own record
                paths.append(recs[i] if i < len(recs) else b"")
            elif rec[:2] == b"? ":
                paths.append(rec[2:])
            i += 1
        base = os.fsencode(str(self.wt))
        stats = []
        for p in paths:
            try:
                st = os.lstat(os.path.join(base, p))
                # mtime can be set back and two writes can land in one timestamp tick (coarse clocks), so a small file also
                # counts by its content; ctime cannot be set from user space and covers the large ones
                body = None
                if stat.S_ISREG(st.st_mode) and st.st_size <= 1 << 20:
                    with open(os.path.join(base, p), "rb") as fh:
                        body = hashlib.sha1(fh.read()).digest()
                stats.append((st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_mode, st.st_ino, body))
            except OSError:
                stats.append(None)
        return (r.stdout, tuple(stats))

    def task_diff(self):
        """The task's diff against where it started, untracked files included."""
        tree = self.tree_hash()
        return tl.git("diff", self.base_sha(), tree, cwd=self.wt) if tree else self.git("diff", self.base_sha())

    def changed_paths(self):
        """Paths the task changed since it started, untracked files included."""
        tree = self.tree_hash()
        out = tl.git("diff", "--name-only", self.base_sha(), tree, cwd=self.wt) if tree else ""
        return [p for p in out.splitlines() if p]

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
    def visual_cfg(self):
        vp = self.cfg.visual_paths
        return vp if vp and vp.include else None

    def shots(self):
        """The pictures the writer saved under the evidence dir, relative to it."""
        if not self.evidence_dir.is_dir():
            return []
        out = []
        for f in sorted(self.evidence_dir.rglob("*")):
            if not (f.is_file() and f.suffix.lower() in IMAGE_EXT):
                continue
            rel = str(f.relative_to(self.evidence_dir))
            if self.shot_methods() and rel not in self.rendered_names:
                continue  # with a shot table the pictures are the engine's own, of this run: never a writer's or an older run's
            why = ("over %d MB" % (MAX_SHOT_BYTES >> 20)) if f.stat().st_size > MAX_SHOT_BYTES else (
                "more than %d screenshots" % MAX_SHOTS if len(out) >= MAX_SHOTS else "")
            if why:
                if rel not in self.shots_skipped:
                    self.shots_skipped.add(rel)
                    self.log.note("screenshot %s skipped: %s" % (rel, why))
                continue
            out.append(rel)
        return out

    def stage_visual(self, st):
        vp = self.visual_cfg()
        return bool(vp) and visual_hit(vp, list(st.get("files") or []) + self.changed_paths())

    # -- tl-bxk.13.15: visual work. The engine renders, a look judge judges, the owner decides taste (docs/design/visual-work.md)
    def shot_methods(self):
        """{method: entry} from engine.shot_table, read from the base branch (a worker can edit the working copy, not that);
        {} when unset or unreadable (then a visual stage works the old way)."""
        if self.shot_cache is None:
            self.shot_cache = {}
            rel = (self.cfg.shot_table or "").strip()
            if rel:
                text = self.git("show", "%s:%s" % (self.cfg.base, rel))
                methods, err = looks.parse_table(text) if text else ({}, "%s is not on %s" % (rel, self.cfg.base))
                if err:
                    self.warn("engine.shot_table: %s; visual stages work the old way" % err)
                self.shot_cache = methods
        return self.shot_cache

    def look_ready(self, st):
        return bool(self.shot_methods()) and self.stage_visual(st)

    def references_text(self):
        """What the planner is told the task already has to look at: image files its text names, and the last landed shots."""
        found = []
        for rel in dict.fromkeys(re.findall(r"[\w./-]+\.(?:png|jpe?g)\b", self.briefs.text(), re.I)):
            if (Path(self.wt) / rel).is_file():
                found.append(rel)
        dest = (self.cfg.evidence_dir or "").strip("/")
        before = sorted(Path(self.wt, dest).glob("*/*.png"))[-6:] if dest and Path(self.wt, dest).is_dir() else []
        if not (found or before):
            return ("No reference image is in the task or under the repo's look reviews. If the task does not say what it should "
                    "look like (a mockup, a target, a screen to match), plan from the bead text and assume the look; say the assumption in the summary.")
        return "Reference images the task has: %s." % ", ".join(found + [str(b.relative_to(self.wt)) for b in before])

    def before_shot(self, name):
        """A landed picture of the same screen (same file name under evidence_dir, another bead's folder): the newest."""
        dest = (self.cfg.evidence_dir or "").strip("/")
        if not dest or not Path(self.wt, dest).is_dir():
            return None
        cands = [f for f in Path(self.wt, dest).glob("*/" + glob.escape(name)) if f.parent.name != self.bead]
        return max(cands, key=lambda f: f.stat().st_mtime) if cands else None

    def render_shots(self, reqs, rnd):
        """([picture names under the evidence dir], [errors]): the requested shot methods run by the engine, outside any lane's
        sandbox, each built only from the project's table (looks.build). Full-size copies go to the evidence dir; the judge's
        shrunk ones to <run>/looks/r<rnd>/."""
        methods = self.shot_methods()
        base = self.run_dir / "looks" / ("r%d" % rnd)
        names, errs = [], []
        self.last_reqs = [r for r in reqs[:looks.MAX_REQUESTS]]
        self.steps.begin("render", "render shots, round %d" % rnd, round=rnd)
        for k, req in enumerate(reqs[:looks.MAX_REQUESTS]):
            out_dir = base / "raw" / ("%d-%s" % (k, re.sub(r"\W+", "_", str(req.get("method") or "?"))))
            out_dir.mkdir(parents=True, exist_ok=True)
            cmd, m, err = looks.build(methods, req, out_dir)
            if err or m is None:
                errs.append(err)
                continue
            before = looks.snapshot(m, self.wt)
            rc, tail = self.sh(cmd, timeout=m["timeout_min"] * 60, save=self.run_dir / "looks" / ("r%d-%d-%s.log" % (rnd, k, m["method"])))
            files = looks.collect(m, self.wt, out_dir, before) if rc == 0 else []  # a failed run's files are no render
            if not files:
                errs.append("shot method %s %s: %s" % (m["method"], "failed (exit %d)" % rc if rc else "made no pictures",
                                                       tail.strip()[-300:] or "no output"))
                continue
            inside = [f for f in files if str(f).startswith(str(Path(self.wt)) + os.sep)]
            if inside and self.sh(["git", "check-ignore", "-q", str(inside[0])], pin=True)[0] != 0:
                self.warn("shot method %s writes pictures in the worktree (%s) and that folder is not ignored by git: they will "
                          "show up as unexplained new files; add it to .gitignore" % (m["method"], m["out"] or str(inside[0].parent)))
            for f in files:
                name, j = f.name, 1
                while name in names:  # one name per picture within a round
                    name, j = "%d-%s" % (j, f.name), j + 1
                names.append(name)
                self.evidence_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, self.evidence_dir / name)
                looks.downscale(f, base / name, int(self.cfg.look_max_px))
        self.rendered_names |= set(names)
        if names:
            self.render_stale = False
        self.steps.outcome("rendered" if names else "failed", "%d picture%s%s" % (
            len(names), "" if len(names) == 1 else "s", (", %d error%s" % (len(errs), "" if len(errs) == 1 else "s")) if errs else ""))
        return names, errs

    def judge_shots(self, names, rnd, summary, last=True):
        """The look judge's findings: a fresh call from another family, in a folder with only the shrunk pictures, the
        references and the 'before' pictures. -> (defects [{item, where, why}], its summary)."""
        base = self.run_dir / "looks" / ("r%d" % rnd)
        refs = [r for r in re.findall(r"[\w./-]+\.(?:png|jpe?g)\b", self.briefs.text(), re.I) if (Path(self.wt) / r).is_file()]
        shown = []
        for r in dict.fromkeys(refs):
            shutil.copy2(Path(self.wt) / r, base / ("ref-" + Path(r).name))
            shown.append("ref-" + Path(r).name)
        pairs = []
        for n in names:
            b = self.before_shot(n)
            if b:
                shutil.copy2(b, base / ("before-" + n))
                pairs.append((n, "before-" + n))
        # the plan's look items are for the last stage (like the cases); an earlier stage is judged on the general checks only
        prompt = looks.judge_prompt(self.cases_of("look-objective") if last else [], names, shown, pairs, summary)
        try:
            d, _ = self.ai("look", "round %d: %d picture%s" % (rnd, len(names), "" if len(names) == 1 else "s"), prompt,
                           writer_family=self.writer_family, cwd=str(base), round=rnd, at=(self.at_stage, rnd, 0))
        except Blocked as b:
            st = getattr(b, "stop", None)
            if not b.why.startswith("paused: no lane") or (st is not None and st.permanence == "needs_owner" and st.reason != "no_lane"):
                raise  # the network (the step resumes), a crash, a login or credit pause: not this node's to swallow
            self.retry_after, self.pause_role, self.pause_lane = 0.0, "", ""  # the run goes on: _ai had noted a pause for the loop
            self.steps.outcome("skipped", "no lane")
            # no lane for the judge: the pictures go unjudged to the owner-look bead; a look judge never parks the bead
            self.warn("the look judge had no lane, the pictures are not judged: %s" % b.why[:200])
            self.look_unjudged["look judge, round %d" % rnd] = "no lane: " + b.why[:160]
            return [], "(not judged: no lane for the look judge)"
        note = "[same family as the writer: no other lane was free] " if self.last_flag == "same_family" else ""
        return [f for f in d["findings"] if f["verdict"] == "defect"], note + d["summary"]

    def look_step(self, st, w, name, last=True):
        """After a visual write: the cheap checks, the shots the writer asked for, the look judge. -> the feedback that sends the
        writer back with the defects (text and picture paths), or "" to go on to the full checks. At most engine.look_rounds
        render rounds per stage; a defect that comes back is a leftover with the pictures, not another write."""
        if not self.look_ready(st) or self.look_done >= int(self.cfg.look_rounds) or self.dry:
            return ""
        reqs = [r for r in w.get("shots") or [] if isinstance(r, dict)]
        if not reqs:
            return ""
        cheap = self.run_checks(dict(st, checks=[]), name, groups=("static",))
        if cheap.failed:
            return ""  # the full checks show it to the writer; no render over a red static check
        self.look_done += 1
        rnd = self.look_done
        names, errs = self.render_shots(reqs, rnd)
        defects = [{"item": "render", "where": "", "why": e} for e in errs]
        summary = ""
        if names:
            found, summary = self.judge_shots(names, rnd, w.get("summary", ""), last)
            defects += found
        if summary:
            self.look_notes = [summary.strip()]
        self.persist_look()
        prev, self.look_prev = self.look_prev, defects
        again = [d for d in defects if any(looks.same_defect(d["why"] + " " + d["where"], p["why"] + " " + p["where"]) for p in prev)]
        fresh = [d for d in defects if d not in again]
        out_of_rounds = self.look_done >= int(self.cfg.look_rounds)
        for d in again + (fresh if out_of_rounds else []):  # tl-bxk.13.15.5: the same defect twice is not the writer's to fix again
            self.look_leftover(d, names)
        if not fresh or out_of_rounds:
            return ""
        self.steps.move("write", "look_defects", "%d defect%s from the look judge, round %d" % (len(fresh), "" if len(fresh) == 1 else "s", rnd))
        return LOOK_FEEDBACK % ("\n".join("- %s%s: %s" % (d["item"], (" (%s)" % d["where"]) if d["where"] else "", d["why"]) for d in fresh),
                               "\n".join("%s/%s" % (self.evidence_dir, n) for n in names))

    def look_leftover(self, d, names):
        title = ("Look: %s" % d["why"])[:120]
        if title not in {lo["title"] for lo in self.leftovers}:
            self.leftovers.append({"title": title, "why": "The look judge found this on %s (%s); it came back after a fix or the render "
                                   "rounds were used up. Pictures: %s. Defect: %s %s" % (
                                       self.bead_title or self.bead, d["item"], ", ".join(names) or "none", d["where"], d["why"])})
            self.log.note("look defect filed as a follow-up: %s" % d["why"][:200])

    def look_write(self, st):
        if not self.stage_visual(st):
            return ""
        if self.shot_methods():
            return LOOK_WRITE_TABLE % (looks.MAX_REQUESTS, looks.table_text(self.shot_methods()))
        return ("\nThis stage changes how something looks (it touches visual paths). Save a screenshot of every changed "
                "screen or state in %s/ with a descriptive name (screen-state.png), and name them in the summary. If the "
                "change is clearly logic-only and nothing on screen differs, put a one-line reason in logic_only; "
                "otherwise leave logic_only empty." % self.evidence_dir)

    def look_review(self, st, w, fix=False):
        if fix or not self.stage_visual(st):
            return ""
        shots = self.shots()
        text = ("\nThis stage changes how something looks. ")
        if self.shot_methods():  # tl-bxk.13.15: the engine rendered the pictures and a look judge read them
            text += ("The engine rendered the pictures (%s) and a look judge, a fresh call from another family, read them%s. "
                     "Judge from its words against the task's done-when; open a picture only if you doubt them. A mismatch "
                     "is a finding; put your judgement in one paragraph in look." % (
                         ", ".join("%s/%s" % (self.evidence_dir, x) for x in shots) or "none were made",
                         (": " + " ".join(self.look_notes)[:900]) if self.look_notes else ""))
            if (w.get("logic_only") or "").strip():
                text += ("\nThe writer says this change is logic-only: \"%s\". Accept it only if nothing on screen can differ; "
                         "if not, give a medium finding." % w["logic_only"].strip())
            return text + "\nlook: empty when nothing here is visual.\n"
        if shots:
            text += ("Screenshots the writer saved: %s. Open every one and judge it against the task's done-when and any "
                     "linked decision or reference image, honestly: put what you see, and whether it matches, in one "
                     "paragraph in look; a mismatch is a finding." % ", ".join("%s/%s" % (self.evidence_dir, s) for s in shots))
        else:
            text += "The writer saved no screenshots. "
        if (w.get("logic_only") or "").strip():
            text += ("\nThe writer says this change is logic-only: \"%s\". Accept it only if nothing on screen can differ; "
                     "if not, give a medium finding." % w["logic_only"].strip())
        return text + "\nlook: empty when nothing here is visual.\n"

    def link_judged(self, review):
        """tl-bxk.7: every link the task adds to a text file is opened from the engine's host (the writer's sandbox has no network,
        and 'verified' there means nothing). One that does not open is a finding for the writer: replace it, or write `unverified` on
        its line; a link marked unverified lands as an item for the owner with the claim it carries (a bot-blocking site answers
        403 from here and opens for a person). Opened links are not asked again."""
        if not self.cfg.check_links:
            return
        try:
            found = links.added_urls(self.task_diff())
        except Exception as e:  # no diff to read is no check, never a failed run
            self.warn("link check skipped: %s" % e)
            return
        todo = [u for _, _, u in found if u not in self.link_ok]
        if not todo:
            return
        todo = [u for u in todo if self.link_tries.get(u, 0) < 2][:LINK_CAP]  # each link is opened twice at most, 200 per review
        try:
            got = links.check_all(todo, fn=self.link_fn or links.check)
        except Exception as e:  # opening links must never stop a run
            self.warn("link check skipped: %s" % e)
            return
        if len(got) >= 3 and all(not ok and links.network_down(why) for ok, why in got.values()):
            self.warn("link check skipped: none of %d links could be reached at all (%s): this host looks offline" % (len(got), next(iter(got.values()))[1]))
            return
        for url, (ok, why) in got.items():
            self.link_tries[url] = self.link_tries.get(url, 0) + 1
            if ok:
                self.link_ok.add(url)
                self.link_bad.pop(url, None)
            elif why != links.UNKNOWN:  # out of time is no verdict
                self.link_bad[url] = why
        seen = set()
        for path, line, url in found:
            why = self.link_bad.get(url)
            if url in self.link_ok or not why or (path, url) in seen:
                continue
            seen.add((path, url))
            if Wording.marked_unverified(line):
                self.add_unverified({"what": "%s (link: %s)" % (fmt.clip(line, 200), url), "kind": "external_fact", "source": url},
                                    "the engine could not open %s (%s); the owner checks it" % (url, why))
                continue
            review["findings"].append(engine_finding(path, 0, (
                "the link %s did not open from the engine's host (%s). Replace it with a source that opens. If the site only blocks "
                "bots, keep it and write `unverified` on the same line, so the owner is asked about the claim it carries. Never "
                "call a link verified that you could not open." % (url, why)), "a reader who follows %s gets an error (%s)" % (url, why)))

    def look_judged(self, review, st, w, fix):
        """No screenshot and no logic-only reason on a visual stage is a warning; the reviewer's look is kept."""
        if fix or not self.stage_visual(st):
            return
        if (review.get("look") or "").strip() and self.shots():
            self.look_notes = [review["look"].strip()]  # the last round's judgement only
        if not self.shots() and not (w.get("logic_only") or "").strip():  # a warning, never a send-back (tl-7y6.7.24)
            self.warn("this stage changes visual paths but %s" % (
                "asked for no shots (name the shot methods to render in `shots`, or say in logic_only why nothing on screen differs)"
                if self.shot_methods() else "saved no screenshot of any changed screen or state in %s/" % self.evidence_dir))

    def look_verify(self, gaps):
        looks = [n for n, u in enumerate(gaps, 1) if self.is_look(u)]
        if not looks:
            return ""
        shots = self.shots()
        return ("\nItems %s are about how it looks. They are never open: judge them from the screenshots (%s), against "
                "the task's done-when and any linked decision or reference image. Open each one. settled when it matches "
                "(evidence names the screenshot and what you saw); wrong when it does not (why says what differs).\n" % (
                    ", ".join(map(str, looks)), ", ".join("%s/%s" % (self.evidence_dir, s) for s in shots) or "none saved"))

    def look_verdict(self, u, v, a, why):
        """A look item is settled only on evidence that names a screenshot file. Otherwise it goes back to the writer
        once, noted as not judged (a later verify that settles it clears the note); the second time the run moves on.
        The owner-look bead carries the note. The owner is never asked."""
        shots, ev = self.shots(), a.get("evidence") or ""
        if v == "settled" and any(sh in ev or Path(sh).name in ev for sh in shots):
            self.look_unjudged.pop(u["what"], None)
            return v, a, why
        if v == "wrong":
            return v, a, why
        if v == "settled":
            why = "settled, but its evidence names no screenshot file"
        reason = why or ("no screenshot saved" if not shots else "no verdict")
        self.look_unjudged[u["what"]] = "agent could not judge: %s" % reason
        if u["what"] not in self.look_retried:
            self.look_retried.add(u["what"])
            if shots:
                return "wrong", a, ("judge it from the screenshots (%s): open each one and name the file you judged. %s"
                                    % (", ".join(shots), why or "")).strip()
            return "wrong", a, "no screenshot to judge the look from: save them in %s/" % self.evidence_dir
        self.warn("a look item is still not judged; the owner is not asked, it waits in the owner-look bead")
        return "settled", dict(a, evidence="agent could not judge: " + reason), reason

    def lfs_ok(self, shots):
        """False when .gitattributes sends these pictures to LFS and git lfs is not installed."""
        try:
            lines = (Path(self.wt) / ".gitattributes").read_text(errors="replace").splitlines()
        except OSError:
            return True
        lfs = [l.split()[0] for l in lines if l.split() and not l.startswith("#") and "filter=lfs" in l]
        if not any(fnmatch.fnmatch(Path(sh).name, pat.split("/")[-1]) for sh in shots for pat in lfs):
            return True
        rc, _ = self.sh(["git", "lfs", "version"], pin=True)
        return rc == 0

    def persist_look(self):
        """What the owner-look bead needs goes into the checkpoint, so a crash after the land still files it."""
        self.checkpoints.keep_look()

    def copy_looks(self):
        """The screenshots of a visual change go into the repo (engine.evidence_dir/<bead>/), in the land's commit."""
        vp, dest = self.visual_cfg(), (self.cfg.evidence_dir or "").strip("/")
        shots = self.shots()
        if not (vp and shots and visual_hit(vp, self.changed_paths())):
            self.persist_look()
            return
        if not dest:
            self.warn("screenshots saved but engine.evidence_dir is not set: they are not kept in the repo")
            return
        if not self.lfs_ok(shots):
            self.warn("engine.evidence_dir pictures go to git LFS (.gitattributes) but git lfs is not installed: "
                      "no screenshot is copied into the repo")
            return
        self.look_paths = []
        for s in shots:
            to = Path(self.wt) / dest / self.bead / s
            to.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.evidence_dir / s, to)
            self.look_paths.append("%s/%s/%s" % (dest, self.bead, s))
        self.persist_look()

    def look_epic(self):
        """The bead's epic: parents walked up to the first epic, else the direct parent."""
        cur, seen = self.bead_parent, set()
        while cur and cur not in seen and len(seen) < 10:
            seen.add(cur)
            d = tl.peek(self.store, cur)
            if d and d.issue_type == "epic":
                return cur
            cur = d.parent if d else ""
        return self.bead_parent

    def existing_owner_look(self):
        """(id, description) of the owner-look bead to reuse: one already linked (related) to this bead, else the one
        under this bead's epic (tl-bxk.10.28: one review bead per epic, appended to); ('', '') when there is none."""
        try:
            rows = self.store.find(BeadQuery(label=LOOK_LABEL))
        except BdFailure:
            return "", ""
        epic, by_epic = self.look_epic() or self.bead, ("", "")
        for row in rows:
            d = tl.peek(self.store, row.id) or row
            if any(x.id == self.bead for x in d.dependencies):
                return row.id, d.description
            if epic and not by_epic[0] and d.parent == epic and d.status != "closed":
                by_epic = (row.id, d.description)
        return by_epic

    def file_owner_look(self):
        """After the land: one bead per epic for the owner's later round (look and feel, and what no check could prove),
        filed once and appended to by each later bead of the epic (a re-land replaces its own section)."""
        if self.look_filed or not (self.look_paths or self.look_unjudged or self.unverified or self.cases_of("taste")):
            return
        head = "## %s: %s" % (self.bead, self.bead_title)
        parts = [head]
        if self.look_paths or self.look_unjudged or not self.unverified:
            parts.append("Screenshots of %s (%s), committed with its land:\n%s\n\nWhat the agent judged: %s\n%s\nNot automatable: "
                         "the owner reviews the look and feel in a later batch." % (self.bead, self.bead_title, "\n".join(
                             "- " + p for p in self.look_paths) or "(none)", " ".join(self.look_notes) or "(the reviewer gave no judgement)",
                             ("\n" + "\n".join("%s (%s)" % (w, u) for u, w in self.look_unjudged.items()) + "\n") if self.look_unjudged else ""))
        if self.cases_of("taste"):
            parts.append("Taste items (the owner decides; they never blocked the land):\n" + "\n".join("- " + t for t in self.cases_of("taste")))
        if self.unverified:
            parts.append(self.unverified_text())
        section = "\n".join(parts)
        with self.review_lock():  # list + create/update is one step: three beads of an epic landing together file one bead
            self.file_review(section)

    @contextlib.contextmanager
    def review_lock(self):
        """One filer at a time per (repo, epic), across slots and sessions."""
        key = "%s|%s" % (self.git("remote", "get-url", "origin") or str(self.wt), self.look_epic() or self.bead)
        with self.locked("review_lock", tl.config_dir() / "locks" / ("review-%s.lock" % hashlib.sha1(key.encode()).hexdigest()[:12])):
            yield

    def create_checked(self, new):
        """bd create that is known to have worked: when bd's lint refuses the body for missing sections (lifesim: Touches and
        Acceptance Criteria), the sections are added and it is tried once more. -> (the new id, "") or ("", why not): nothing
        was created then (tl-7y6.7.9: 98 follow-ups were called filed and none existed)."""
        try:
            return self.store.create(new), ""
        except BdFailure as e:
            need = e.error.missing_sections
            if not need or not new.description:
                return "", e.error.text
        self.log.note("bd refused the create (%s): trying again with the sections it names" % ", ".join(need))
        try:
            return self.store.create(dataclasses.replace(new, description=with_sections(new.description, need, self.bead))), ""
        except BdFailure as e:
            return "", e.error.text

    def file_review(self, section):
        head = section.split("\n", 1)[0]
        have, old = self.existing_owner_look()
        made, err = have, ""
        if have:
            kept = [x for x in re.split(r"\n\n(?=## )", old.strip()) if x and not x.startswith(head.split(":")[0] + ":")]
            if not tl.attempt(self.store.update, have, BeadPatch(description="\n\n".join(kept + [section]))):
                err = "bd refused the update"
        else:
            made, err = self.create_checked(NewBead(
                title=("Look review: " if self.look_paths or self.look_unjudged else "Owner review: ") + (self.bead_title or self.bead),
                labels=[LOOK_LABEL], no_inherit_labels=True, description=section, deps=["related:" + self.bead],
                parent=self.look_epic() or self.bead))  # no epic: the review bead sits under the bead itself
        if err:
            self.warn("owner-look bead %s failed: %s" % ("update" if have else "create", err[:300]))
        else:
            self.look_filed = True
            if self.cases_of("taste"):
                if made:
                    self.write_looks(made)
                else:
                    self.warn("owner-look bead filed, but its id was not in bd's answer: no looks metadata")

    def write_looks(self, bead_id):
        """tl-bxk.13.15: the gallery's data on the owner-look bead, as metadata `looks` (one entry per taste item: id, bead,
        title, note, shots[{path, role before|after, label}], status). A re-land of this bead replaces its own entries and
        keeps one the owner already answered (good or redo)."""
        after = [p for p in self.look_paths]
        shots = []
        for p in after:
            b = self.before_shot(Path(p).name)
            if b:
                shots.append({"path": str(b.relative_to(self.wt)), "role": "before", "label": Path(p).stem})
            shots.append({"path": p, "role": "after", "label": Path(p).stem})
        mine = [{"id": "%s#%d" % (self.bead, k), "bead": self.bead, "title": t, "note": " ".join(self.look_notes)[:600],
                 "shots": shots, "status": "open"} for k, t in enumerate(self.cases_of("taste"), 1)]
        shown = tl.peek(self.store, bead_id)
        meta = dict(shown.metadata) if shown else {}
        old = meta.get("looks") if isinstance(meta.get("looks"), list) else []
        answered = {e.get("id"): e for e in old if isinstance(e, dict) and e.get("bead") == self.bead and e.get("status") in ("good", "redo")}
        meta["looks"] = [e for e in old if isinstance(e, dict) and e.get("bead") != self.bead] + [answered.get(e["id"], e) for e in mine]
        if not tl.attempt(self.store.update, bead_id, BeadPatch(metadata=meta)):
            self.warn("owner-look bead %s: looks metadata failed" % bead_id)

    def unverified_text(self):
        return "Unverified, for the owner:\n" + "\n".join(
            "- %s (%s%s)%s" % (u["what"], u["kind"], (", source: " + u["source"]) if u.get("source") else "",
                               (": " + u["why"]) if u.get("why") else "") for u in self.unverified)

    def keep_evidence(self):
        """Pictures the writer saved as proof outlive the worktree: copied to the run dir, named on the bead."""
        kept = []
        if not self.evidence_dir.is_dir():
            return kept
        out = self.run_dir / "evidence"
        for f in sorted(self.evidence_dir.rglob("*")):
            if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                dst = out / f.relative_to(self.evidence_dir)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dst)
                kept.append(dst)
        return kept

    @contextlib.contextmanager
    def stop_deferred(self):
        """SIGTERM inside this block is only noted (the yielded list gets an item); the caller stops after it."""
        got = []
        if not (hasattr(signal, "SIGTERM") and threading.current_thread() is threading.main_thread()):
            yield got
            return
        old = signal.signal(signal.SIGTERM, lambda *_: got.append(True))
        try:
            yield got
        finally:
            signal.signal(signal.SIGTERM, old)

RUN_STEM = re.compile(r"^\d{8}-\d{6}$")  # <bead>-<YYYYMMDD-HHMMSS>: an engine log of that bead, not of a child bead


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


def outcome_for(kind, why):
    """The trace's `outcome` word: landed, done, failed (a fault) or blocked (an ask, a pause, a wait). kind None: the
    verify-gaps ask, read from its prefix."""
    if kind in oc.FINISH:
        return kind.value
    if kind:  # a stop keeps the word `failed` in the trace (the reports count it); its `loop` field says paused
        return "failed" if oc.POLICY[kind].loop == "failed" or kind == oc.Kind.PAUSE_KILLED else "blocked"
    return "failed" if why.startswith("failed:") else "blocked"


def node_outcome(outcome, why, kind=None):
    """What a node still open at the close came to: the run's own end."""
    if outcome in ("landed", "done"):
        return outcome
    if kind:
        return ("stopped" if kind == oc.Kind.PAUSE_KILLED else "paused" if kind.name.startswith("PAUSE_")
                else "waiting" if kind == oc.Kind.WAIT_ASK else "failed" if outcome == "failed" else "asks")
    if why.startswith("paused:"):
        return "paused"
    if why.startswith("waiting:"):
        return "waiting"
    if why.startswith("failed: stopped"):
        return "stopped"
    if outcome == "failed":
        return "failed"
    return "blocked"


def close_move(outcome, why, kind=None):
    """(to, cause) of the last move, when no decision point logged one: landed, an ask, a pause, a wait, a failure."""
    if outcome in ("landed", "done"):
        return "close", outcome
    if kind:
        if kind == oc.Kind.PAUSE_KILLED:
            return "pause", "stopped"
        if kind.name.startswith("PAUSE_"):
            return "pause", "paused"
        if kind == oc.Kind.WAIT_ASK:
            return "ask", "waiting"
        return ("ask", oc.ASK_NAME[kind]) if kind in oc.ASKS else ("close", "failed")
    if why.startswith("paused:"):
        return "pause", "paused"
    if why.startswith("waiting:"):
        return "ask", "waiting"
    return "close", "stopped" if why.startswith("failed: stopped") else "failed"


engine_written = intake.engine_written  # what the engine (or a receipt of ours) wrote into a bead is never the owner's (tl-7y6.6.2)


def run_breakdown(log_path, open_node=None, top=4):
    """Where a run's minutes went, from its engine log, longest first: BudgetLine(step, minutes, rounds). Steps under a minute are
    left out; the open step counts up to now."""
    tot = {}
    for it in JsonlStore(Path(log_path), rec.decode).read_from().items:
        if isinstance(it.rec, rec.StepEnd):
            t = tot.setdefault(it.rec.step, [0.0, 0])
            t[0] += it.rec.secs
            t[1] += 1
    if open_node:
        t = tot.setdefault(open_node.step, [0.0, 0])
        t[0] += max(0.0, time.time() - open_node.t)
        t[1] += 1
    return [BudgetLine(step=k, minutes=float(v[0] // 60), rounds=int(v[1])) for k, v in sorted(tot.items(), key=lambda kv: -kv[1][0]) if v[0] >= 60][:top]





def question_spec(out):
    """The ask a worker's question makes: its text and the options it offered."""
    return askspecs.open_question(out["question"], out.get("options"))


LINK_CAP = 200  # links opened per review



def reflection_text(r):
    """The reflection as one line for the bead's Reflect comment ('' when there is none)."""
    if not r:
        return ""
    bad = "; ".join("[%s] %s (session %s)" % (b["cause"], fmt.clip(b["what"], 160), b["session"]) for b in r.get("went_badly") or []) or "none"
    return " reflection: badly: %s%s%s;" % (fmt.clip(bad, 500), (" | wasted: " + fmt.clip("; ".join(r["wasted"]), 200)) if r.get("wasted") else "",
                                           (" | change: " + fmt.clip("; ".join(r["change"]), 200)) if r.get("change") else "")


def context_tokens(path, tail=1 << 20):
    """-> the input tokens (cache included) of the last turn in a worker's transcript, or None: Claude's last assistant message
    usage, Codex's last token_count, OpenCode's last assistant message tokens (`opencode:ses_...`, read from its DB). The
    answer's own `tokens` add up every turn of the call, so they say nothing of the size."""
    if tl.opencode_id(path):
        return tl.opencode_context(tl.opencode_id(path))
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

def cfg_source(repo):
    """(the RepoProfile, the base hint, the pinned commit: empty for a local fallback). A bad .task-loop.json exits loudly."""
    base = tl.load_profile(tl.profile(repo)).engine.base
    data, commit = tl.profile_source(repo, base)
    return tl.load_profile(data), base, commit


def load_cfg(repo):
    """The `engine` block of the repo's .task-loop.json as committed on the base branch (tl.profile), defaults for what it leaves out.
    The base is itself a key: the working tree names it, then the base's copy is read. A caller fetches first (the loop's queue
    does; run-task reads the last fetch, and resets onto the base anyway)."""
    return cfg_source(repo)[0].engine


def busy_elsewhere(repo, actor, bead_id, store=None):
    """True when `actor` holds a slot (it is a loop) that a run of ANOTHER bead holds now: then its claim on `bead_id` is a claim
    it left, not one it works on."""
    now_t = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for sb in tl.slot_beads(repo, store):
        if sb.assignee == actor and sb.status == "in_progress" and (sb.lease_expires_at or now_t) >= now_t:
            held = sb.metadata.get("held_bead")
            if held and held != bead_id:
                return True
    return False


def reclaim(bead_id, repo, store=None):
    """(ok, why): run-task takes back what the engine itself left, never what a person holds. A claim by a tl- actor
    whose lease ran out is released (a restarted Claude session gets a new actor name). A bead the engine blocked is
    reopened for a plain retry, or when a comment after the block answers the open ask; it stays blocked when a person
    commented after the block with no ask open (they may have parked it), while an ask waits unanswered, or while
    another bead blocks it."""
    store = store or tl.bd_store(repo)
    b = tl.peek(store, bead_id) or Bead(id=bead_id, title="", status="")
    who, me = b.assignee, tl.actor()
    if intake.held(b.metadata, time.time()):
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
            live = who in tl.live_actors(repo, store) or b.lease_expires_at >= time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if live:
            logs = sorted((tl.config_dir() / "engine").glob("%s-*.jsonl" % bead_id))
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
        ask = AskStore.at(ConfigDir(tl.config_dir())).get(bead_id)
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


def main(a):
    try:
        rc = run_main(a)
    except Blocked as b:  # a stop (SIGTERM) before the engine ran: the slot and the lock are already given back
        rc = {"v": 1, "outcome": "failed", "bead": a.id, "why": b.why, "kind": b.kind.value if b.kind else ""}
    if isinstance(rc, dict):  # stopped before the engine ran: nothing in the bead changed
        report(a, rc)
        return 1
    return rc


def run_main(a):
    """The SIGTERM handler lives only as long as the run: an engine called in a process that goes on (a test runner, a
    host) must not leave it behind, turning any later stray SIGTERM there into a Blocked."""
    old = None
    if hasattr(signal, "SIGTERM") and threading.current_thread() is threading.main_thread():
        old = signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(Blocked("failed: stopped (SIGTERM)", kind=oc.Kind.PAUSE_KILLED)))
    try:
        return run_main_stoppable(a)
    finally:
        if old is not None:
            signal.signal(signal.SIGTERM, old)


def run_main_stoppable(a):
    for f in (sys.stdout, sys.stderr):
        append_output(f)
    if not os.environ.get("TASK_LOOP_SESSION") and not tl.session_id():
        os.environ["TASK_LOOP_SESSION"] = "engine-" + uuid.uuid4().hex[:12]
    repo = tl.repo_root()
    cfg = load_cfg(repo)
    if a.slot == "any":
        return run_any_slot(a, repo, cfg)
    return run_in(a, repo, cfg)


def run_any_slot(a, repo, cfg):
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
    got = tl.wait_slot(repo, tl.profile_slots(repo), "run-task " + a.id, stop=lambda: not wait,
                       on_wait=waiting, prio=tl.bead_priority(repo, a.id))
    if not got:
        why = "no free slot (tl slot list); --wait waits in line for one"
        print("TAKEN: %s" % why)
        return {"v": 1, "outcome": "taken", "bead": a.id, "why": why}
    a.slot, a.worktree, sb = got
    os.environ["TASK_LOOP_SLOT_BEAD"] = sb  # run_in sees the slot as taken; the engine heartbeats it
    RUN_SLOT["owned"] = a.slot  # a re-exec hands the slot on (TL_REEXEC) and its next run-task gives it back
    try:
        return run_in(a, repo, cfg)
    finally:
        old = signal.signal(signal.SIGTERM, signal.SIG_IGN) if hasattr(signal, "SIGTERM") and \
            threading.current_thread() is threading.main_thread() else None
        try:
            os.environ.pop("TASK_LOOP_SLOT_BEAD", None)
            tl.release_slot(repo, a.slot, bead=a.id, mine=True)
        finally:
            if old is not None:
                signal.signal(signal.SIGTERM, old)


def take_area(a, repo, cfg, lock, sb=""):
    """The engine lock, with the area check before it under the area lock (loop_env.area_lock): "" when this run holds the
    worktree, else why not. A bead whose area runs elsewhere: a warning, or refused with --exclusive-area."""
    import loop_env  # the queue rule; imports engine itself

    def mark():  # the slot says which bead runs in it (held_bead makes its area busy): only once the area is decided
        if sb:
            tl.attempt(tl.bd_store(repo).update, sb, BeadPatch(set_metadata={"held_bead": a.id}))
    if not loop_env.has_areas(cfg):
        why = lock.take()
        if not why:
            mark()
        return why
    with loop_env.area_lock(repo):
        area, busy = loop_env.area_busy(repo, cfg, tl.peek(tl.bd_store(repo), a.id) or Bead(id=a.id, title="", status=""))
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


def run_in(a, repo, cfg):
    wt = a.worktree
    if not wt and a.slot:  # the slot is the worktree
        wt = tl.slot_dir(repo, a.slot, tl.profile_slots(repo))
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
        return run_bead(a, repo, cfg, wt)
    took = ""
    try:
        # a hand run takes its slot's bead as the loop does (a --worktree that is a slot too); one the loop started has
        # it already: TASK_LOOP_SLOT_BEAD names that very slot's bead
        slot = a.slot or tl.slot_of(repo, wt)
        sb = getattr(tl.slot_bead(repo, slot), "id", "") if slot else ""
        if slot and sb and os.environ.get("TASK_LOOP_SLOT_BEAD") == sb and _handed_slot(slot):
            took = sb  # exec'd by the run-task that took this slot: it is still ours, and this process gives it back
            RUN_SLOT["owned"] = slot
        elif slot and not (sb and os.environ.get("TASK_LOOP_SLOT_BEAD") == sb):
            took, why = tl.take_named_slot(repo, slot, tl.profile_slots(repo), "run-task " + a.id)
            if not took:
                print("TAKEN: %s" % why)
                return {"v": 1, "outcome": "taken", "bead": a.id, "why": why}
            os.environ["TASK_LOOP_SLOT_BEAD"] = took  # the engine's heartbeat keeps it
            RUN_SLOT["owned"] = slot
        lock = enginelock.EngineLock(wt, a.id, slot)
        busy = take_area(a, repo, cfg, lock, sb=took or sb if slot else "")
        if busy:
            why = busy if busy.startswith("area ") else "worktree %s: %s" % (wt, busy)
            print("TAKEN: %s" % why)
            return {"v": 1, "outcome": "taken", "bead": a.id, "why": why}
        enginelock.LOCK = lock
        return run_bead(a, repo, cfg, wt)
    finally:
        old = signal.signal(signal.SIGTERM, signal.SIG_IGN) if hasattr(signal, "SIGTERM") and \
            threading.current_thread() is threading.main_thread() else None
        try:
            if enginelock.LOCK:
                enginelock.LOCK.release()
                enginelock.LOCK = None
            if took:
                os.environ.pop("TASK_LOOP_SLOT_BEAD", None)
                tl.release_slot(repo, slot, bead=a.id, mine=True)
        finally:
            if old is not None:
                signal.signal(signal.SIGTERM, old)


defer_stop = Engine.stop_deferred  # it uses no state: also before an Engine exists, as defer_stop(None)


def run_bead(a, repo, cfg, wt):
    # a stop during the reclaim and claim waits for them, then the engine closes the run as stopped (trace, bead)
    with defer_stop(None) as stop:
        if not a.dry_run:
            ok, why = reclaim(a.id, repo)
            if not ok:
                print("TAKEN: %s" % why)
                return {"v": 1, "outcome": "taken", "bead": a.id, "why": why}
            if why:
                say("%s: %s" % (a.id, why))
        if not a.dry_run and tl.cmd_claim(Args(id=a.id, worktree=wt, slot=a.slot)) != 0:
            # bd lets this session re-claim its own bead (a reopened one); another session's claim stops here
            return {"v": 1, "outcome": "taken", "bead": a.id, "why": "claimed by another session"}
        eng = Engine(a.id, wt, cfg, dry_run=a.dry_run, verbose=not getattr(a, "quiet", False), fresh=bool(getattr(a, "fresh", False)))
        eng.stop_pending = bool(stop)
        say("engine log: %s" % eng.log_path)
    rc = eng.run()
    with defer_stop(None):  # the outcome line is what the loop reads: a stop waits for it
        rec = eng.result()
        if pause_line(rec):
            say(pause_line(rec))
        report(a, rec)
    return rc
