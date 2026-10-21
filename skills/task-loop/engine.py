#!/usr/bin/env python3
"""The task engine: one bead through reset → plan → (write → checks → review)* per stage → gate → land → close.

    tl.py run-task ID [--worktree DIR] [--dry-run]

Code routes; AI nodes only produce structured outputs (validated against a schema). The close step always runs.
A coordinator session may start it and watch it (attended mode); nothing here needs one. Design:
docs/design/coordinator-less.md. Python 3.8+, standard library only.
"""

import contextlib
import fnmatch
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading

try:
    import fcntl
except ImportError:  # Windows: one land at a time is not enforced
    fcntl = None
import time
import uuid
from pathlib import Path

import tl

DEFAULTS = {
    "gate": "",                       # command run on the rebased tree before landing ("" = the push hook gates)
    "land": "git push origin HEAD:main",
    "base": "origin/main",
    "budget_usd": 15,
    "budget_min": 180,
    "max_rounds": 3,                  # review send-backs per stage before a replan
    "max_check_tries": 3,             # red checks in a row that end a round (checks never reach the reviewer red)
    "max_replans": 1,                 # per bead, across runs; a changed bead (an owner's answer) never counts
    "max_fix_rounds": 2,              # per bead: a red gate, a conflict or what the check before land found wrong
    "pick_label": "",                 # the label an unattended runner picks by (lifesim: auto); a decision or ticket ask removes it
    "needs_info_label": "needs-info", # and adds this one, so the bead leaves the queue until the owner relabels it
    "max_stages": 3,                  # a bigger plan is a split ask (ticket), unless the owner already answered one
    "node_timeout_min": 45,
    "delegate": "",                   # path to delegate's route.py; "" = the newest installed iorlas-delegate
    "lane_wait_min": 10,              # how long a step waits in its slot for a lane; longer: the run pauses (slot freed)
    "checks": [],                     # repo checks: [{id, cmd, group: static|tests|acceptance, when: [globs], retry}]
    "host": False,                    # the work needs the host (Unity, an editor): write steps get delegate's --host
                                      # a bead label `sandbox` turns it off for one bead
    "no_sandbox": False,              # the 0.6 name of `host`, still read
    "worker_rules": "",               # repo file the planner and writer read first (lifesim: docs/agents/codex.md)
    "brief_kb": 5,
    "test_pattern": r"^\s*(def test_|async def test_|\[(Test|Fact|Theory|TestMethod|TestCase)\b|#\[test\]|(it|test)\(|func Test)",                    # a brief bigger than this gets a ⚠ (never cut: the bead may be too big)
}

# ---- output contracts -----------------------------------------------------------------------------------------------

S_STR = {"type": "string"}
S_STRS = {"type": "array", "items": S_STR}
LEFTOVERS = {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                        "properties": {"title": S_STR, "why": S_STR}, "required": ["title", "why"]}}
UNCHECKED_KINDS = ("requirement", "number", "deletion", "link", "case", "tooling")  # one of these unchecked stops the land
UNCHECKED_TEXT = ("\nunchecked: what you could not check yourself, each with its kind: requirement, number, deletion, link "
                  "(a cited link you could not open), case (an acceptance case you could not run), tooling (a change to "
                  "tools or build files the plan did not name), or other. Empty when you checked everything.")

VERDICTS = ("settled", "wrong", "open")  # the verifier's answer per unchecked item, before a verify ask

# a check that runs bd or reads the beads files proves the tracker, not the code: no writer can satisfy it (writers cannot
# run bd), so it burns every round (lifesim-fld.26.12, lifesim-fld.27.9: 3 rounds, 2 replans, 89 min, stuck)
TRACKER_CHECK = re.compile(r"(?:^|[;&|(`!{]|\b(?:then|do|else|xargs|exec|command|env|time)\b)\s*bd(?=\s|$|[;&|)`])|"
                           r"(?<![\w-])\.beads\b")
TRACKER_TEXT = ("\n\nYour plan was sent back: these checks read the issue tracker (they run bd or read .beads/), which "
                "no writer can run and no code change can satisfy:\n%s\nRewrite them to prove the code and the tree only. "
                "Follow-up work the task wants filed goes in leftovers: the engine files it.")


def tracker_checks(plan):
    """The plan's checks (stages, risks, cases) that read the issue tracker instead of the code."""
    cmds = [c for s in plan.get("stages") or [] for c in s["checks"]] + [
        x["check"] for k in ("risks", "cases") for x in plan.get(k) or []]
    return list(dict.fromkeys(c for c in cmds if TRACKER_CHECK.search(c)))


LATER_CASES = ("\nAn acceptance case this stage cannot run is not unchecked: it is checked when the last stage runs it.")
FRESH_WRITER_TEXT = ("\nYou take over from an earlier writer of this task whose model is out for now. Its work is in this "
                     "tree, committed on this branch or not: read `git status` and the diff from main first, then go on "
                     "from there; do not start over.")

SCHEMAS = {
    "plan": {"type": "object", "additionalProperties": False,
             "required": ["summary", "stages", "risks", "question", "cases", "leftovers"],
             "properties": {
                 "summary": S_STR,
                 "stages": {"type": "array", "items": {
                     "type": "object", "additionalProperties": False, "required": ["goal", "files", "checks", "hard"],
                     "properties": {"goal": S_STR, "files": S_STRS, "checks": S_STRS, "hard": {"type": "boolean"}}}},
                 "risks": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                      "required": ["what", "check"],
                                                      "properties": {"what": S_STR, "check": S_STR}}},
                 "question": S_STR,
                 "cases": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                      "required": ["criterion", "check"],
                                                      "properties": {"criterion": S_STR, "check": S_STR}}},
                 "leftovers": LEFTOVERS}},
    "write": {"type": "object", "additionalProperties": False,
              "required": ["summary", "checks_run", "question", "decided", "bad_checks", "new_cases", "unchecked"],
              "properties": {"summary": S_STR, "question": S_STR, "decided": S_STR,
                             "unchecked": {"type": "array", "items": {
                                 "type": "object", "additionalProperties": False, "required": ["what", "kind"],
                                 "properties": {"what": S_STR, "kind": {"type": "string", "enum": list(UNCHECKED_KINDS) + ["other"]}}}},
                             "new_cases": {"type": "array", "items": {
                                 "type": "object", "additionalProperties": False, "required": ["criterion", "check", "why"],
                                 "properties": {"criterion": S_STR, "check": S_STR, "why": S_STR}}},
                             "bad_checks": {"type": "array", "items": {
                                 "type": "object", "additionalProperties": False, "required": ["cmd", "why"],
                                 "properties": {"cmd": S_STR, "why": S_STR}}},
                             "checks_run": {"type": "array", "items": {
                                 "type": "object", "additionalProperties": False, "required": ["cmd", "exit"],
                                 "properties": {"cmd": S_STR, "exit": {"type": "integer"}}}}}},
    "review": {"type": "object", "additionalProperties": False,
               "required": ["findings", "unmet", "question", "decided", "leftovers", "unchecked"],
               "properties": {"unchecked": {"type": "array", "items": {
                       "type": "object", "additionalProperties": False, "required": ["what", "kind"],
                       "properties": {"what": S_STR, "kind": {"type": "string", "enum": list(UNCHECKED_KINDS) + ["other"]}}}},
                   "findings": {"type": "array", "items": {
                   "type": "object", "additionalProperties": False, "required": ["file", "line", "severity", "fix"],
                   "properties": {"file": S_STR, "line": {"type": "integer"},
                                  "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                                  "fix": S_STR}}},
                   "unmet": S_STRS, "question": S_STR, "decided": S_STR, "leftovers": LEFTOVERS}},
    "verify": {"type": "object", "additionalProperties": False, "required": ["items"],
               "properties": {"items": {"type": "array", "items": {
                   "type": "object", "additionalProperties": False, "required": ["n", "verdict", "evidence", "why"],
                   "properties": {"n": {"type": "integer"}, "verdict": {"type": "string", "enum": list(VERDICTS)},
                                  "evidence": S_STR, "why": S_STR}}}}},
}


def validate(data, schema, path="$"):
    """The subset of JSON Schema the contracts above use. Returns a list of errors."""
    t = schema.get("type")
    ok = {"object": dict, "array": list, "string": str, "boolean": bool}.get(t)
    if t == "integer":
        if not isinstance(data, int) or isinstance(data, bool):
            return ["%s: expected integer" % path]
    elif ok and not isinstance(data, ok):
        return ["%s: expected %s" % (path, t)]
    errs = []
    if "enum" in schema and data not in schema["enum"]:
        errs.append("%s: %r not in %s" % (path, data, schema["enum"]))
    if t == "object":
        for k in schema.get("required", []):
            if k not in data:
                errs.append("%s.%s: missing" % (path, k))
        for k, v in data.items():
            if k in schema.get("properties", {}):
                errs += validate(v, schema["properties"][k], path + "." + k)
    if t == "array":
        for i, v in enumerate(data):
            errs += validate(v, schema.get("items", {}), "%s[%d]" % (path, i))
    return errs


# ---- workers --------------------------------------------------------------------------------------------------------

def child_env():
    """Workers never inherit the launcher's session (a leaked CLAUDE_* broke claude children in the factory)."""
    drop = ("CLAUDE_CODE_", "CLAUDECODE", "ANTHROPIC_", "DELEGATE_", "CODEX_COMPANION", "CLAUDE_PID",
            "CLAUDE_AGENT_SDK", "CLAUDE_PLUGIN", "TASK_LOOP_")
    env = {k: v for k, v in os.environ.items() if not k.startswith(drop)}
    env["TASK_LOOP_WORKER"] = "1"
    env["DELEGATE_DEPTH"] = "1"  # a worker never delegates further
    return env


class Result:
    def __init__(self, data=None, text="", ref="", cost=0.0, secs=0.0, error="", backend=""):
        self.data, self.text, self.ref, self.cost, self.secs, self.error, self.backend = (
            data, text, ref, cost, secs, error, backend)


def run_proc(cmd, cwd, timeout, log_path, on_line=None):
    t = time.time()
    lines = []
    with open(log_path, "ab") as log:
        p = subprocess.Popen(cmd, cwd=cwd, env=child_env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=log, start_new_session=(os.name != "nt"))

        def read():
            for raw in p.stdout:
                ln = raw.decode("utf-8", "replace")
                lines.append(ln)
                if on_line:
                    try:
                        on_line(ln)
                    except Exception:
                        pass
        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        try:
            p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_tree(p)
            return None, time.time() - t
        except BaseException:  # stopped: never leave the worker running
            kill_tree(p)
            raise
        reader.join(10)
    return (p.returncode, "".join(lines)), time.time() - t


def kill_tree(p):
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
        else:
            os.killpg(p.pid, 9)
    except OSError:
        pass
    p.wait()


ROLES = {"plan": "planner", "write": "worker", "review": "reviewer", "verify": "reviewer"}  # reviewer: read-only rungs


def find_route(path=""):
    """delegate's route.py: `path` when given (engine.delegate), else the newest installed delegate. Whether it speaks
    worker-run v2 is the handshake's to say (contract)."""
    if path:
        return path if os.path.exists(path) else None
    found = []
    for p in (Path.home() / ".claude" / "plugins" / "cache").glob("*/iorlas-delegate/*/skills/delegate/route.py"):
        found.append((tuple(int(x) for x in re.findall(r"\d+", p.parents[2].name)[:3]), str(p)))
    return max(found)[1] if found else None


def contract(route):
    """delegate's worker-run handshake (`route.py contract --json`): the answer when it speaks v2, else None."""
    try:
        r = subprocess.run([sys.executable, route, "contract", "--json"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60, env=child_env())
        j = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 and r.stdout.strip() else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return j if isinstance(j, dict) and j.get("worker_run") == 2 else None


def access(wanted):
    """The flag that gives a step the host, when the task was granted it (worker-run v2: every step takes `--host`)."""
    return "--host" if wanted else ""


def call_delegate(route, role, prompt, schema, cwd, resume, timeout, log_path, writer=None, parent="", task="",
                  title="", access=""):
    """One AI step through `route.py run` (worker-run v2). Returns (Result, the answer object or None)."""
    with tempfile.TemporaryDirectory() as d:
        bf, sf = os.path.join(d, "brief.md"), os.path.join(d, "schema.json")
        Path(bf).write_text(prompt, encoding="utf-8")
        Path(sf).write_text(json.dumps(schema))
        cmd = [sys.executable, route, "run", role, "--brief", bf, "--cwd", cwd, "--schema", sf,
               "--unattended", "--parent", parent, "--task", task, "--title", title[:120]]
        if resume:
            cmd += ["--resume", resume]
        if writer:
            cmd += ["--authored-by", writer]
        if access:
            cmd.append(access)
        res, secs = run_proc(cmd, cwd, timeout + 120, log_path)
    if res is None:
        return Result(secs=secs, error="timeout", backend="delegate", ref=resume or ""), None
    code, out = res
    try:
        j = json.loads(out.strip().splitlines()[-1]) if out.strip() else None
    except ValueError:
        j = None
    if not isinstance(j, dict):
        return Result(text=out[-2000:], secs=secs, error="route.py exit %d, no answer object" % code,
                      backend="delegate"), None
    st = j.get("status")
    err = "" if st == "done" else "%s: %s" % (st, j.get("say") or "")
    return Result(j.get("data"), j.get("text") or "", j.get("ref") or "", float(j.get("cost") or 0),
                  float(j.get("secs") or secs), err, j.get("family") or "delegate"), j


# ---- the engine -----------------------------------------------------------------------------------------------------

class Blocked(Exception):
    def __init__(self, why, question=""):
        super().__init__(why)
        self.why, self.question = why, question


class Engine:
    def __init__(self, bead, wt, cfg, dry_run=False, verbose=True):
        self.bead, self.wt, self.cfg, self.dry, self.verbose = bead, wt, cfg, dry_run, verbose
        self.t0 = time.time()
        self.cost = 0.0
        self.stats = {"writes": 0, "rounds": 0, "reviews": 0, "replans": 0, "nodes": 0, "tests_added": 0, "tests_removed": 0,
                      "tokens_in": 0, "tokens_cached": 0, "tokens_out": 0}
        self.session = tl.session_id()
        self.leftovers = []
        self.filed = []       # leftover titles filed by an earlier run on this checkpoint: a replan naming one again is no new bead
        self.done = []        # goals of the stages accepted on this branch, across plans and runs
        self.accepted = []    # their indices in the current plan
        self.brief_hash = ""
        self.replans = 0
        self.fixes = 0
        self.denials = []     # commands refused to this bead's writers, across lanes and runs
        self.unchecked = []   # what the last review of this run says nobody checked (each review re-judges it)
        self.answered = None  # the owner ask this run starts from, once answered
        self.verify_answer = ""  # the owner's answer to a verify ask, when it asks for more than a yes
        self.stuck_why = ""
        self.host = False  # granted after reset, from the base branch's .task-loop.json only (granted_host)
        self.contract = None  # delegate's worker-run v2 handshake: features, reasons, what each lane's workers see
        self.budget_warned = set()
        self.writer = {}  # backend -> thread/session id, so later rounds of a task resume the same writer
        self.writer_family = None  # the family of the last write: the verifier comes from another one when it can
        self.verified = []  # the verifier's answer per unchecked item at land: in the trace and on the bead
        self.sessions = []  # every AI call of this run: the trace a later reflection reads (traces.jsonl)
        d = tl.config_dir() / "engine"
        d.mkdir(exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.log_path = d / ("%s-%s.jsonl" % (bead, stamp))
        self.err_path = d / ("%s-%s.stderr" % (bead, stamp))
        # Engine files (brief, plan, node answers, check results) live outside the worktree, where no worker can write
        # them; in lifesim-vbo a writer's sandbox runs kept in .task/ were read as engine results by four planners.
        self.run_dir = tl.config_dir() / "runs" / self.log_path.stem
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.task_dir = Path(wt) / ".task" / bead  # the writer's: only evidence/ lives here
        self.task_dir.mkdir(parents=True, exist_ok=True)
        self.evidence_dir = self.task_dir / "evidence"  # the writer's proof of what the engine cannot rerun
        self.evidence_dir.mkdir(exist_ok=True)
        self.route = find_route(cfg.get("delegate", ""))

    # -- records
    def log(self, kind, text, **kw):
        rec = {"t": time.time(), "kind": kind, "text": text}
        rec.update(kw)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if kind == "node":
            tl.event("stage", self.bead, text=text)
        if kind == "warn" or not (kind == "cmd" and not self.verbose):
            say("[%s] %s%s" % (time.strftime("%H:%M:%S"), "⚠ " if kind == "warn" else "", text))

    def trace_call(self, node, role, attempt, r, j, host=False):
        """One AI call into the run's trace: which worker session did what, and where its transcript is."""
        j = j or {}
        rec = {"node": node, "role": role, "attempt": attempt, "status": j.get("status") or r.error or "none",
               "ref": j.get("ref") or r.ref or "", "run_id": j.get("run_id") or "", "transcript": j.get("transcript") or "",
               "family": j.get("family") or "", "lane": j.get("lane") or "", "model": j.get("model") or "",
               "effort": j.get("effort") or "", "secs": round(r.secs or 0), "cost": r.cost or 0.0, "t": time.time(),
               "host": host, "tokens": j.get("tokens"), "denied": j.get("denied") or [],  # tokens {in, cached, out}
               "reason": j.get("reason"), "next": j.get("next"), "context": j.get("context")}
        for k in ("in", "cached", "out"):
            self.stats["tokens_" + k] += int((rec["tokens"] or {}).get(k) or 0)
        self.sessions.append(rec)
        self.log("session", "%s: %s %s" % (node, rec["family"] or "?", rec["ref"] or "(no session)"), **rec)

    def write_trace(self, outcome, why, sha):
        """One line per engine run in traces.jsonl, never pruned: bead, repo, branch, every session, the outcome."""
        rec = {"v": 1, "run": self.log_path.stem, "bead": self.bead,
               "repo": self.git("remote", "get-url", "origin") or str(self.wt), "worktree": str(self.wt),
               "branch": self.git("symbolic-ref", "--short", "-q", "HEAD"), "coordinator_session": self.session,
               "started": self.t0, "ended": time.time(), "outcome": outcome, "why": (why or "")[:500], "sha": sha or "",
               "cost": self.cost, "stats": self.stats, "host": self.host, "delegate": self.route or "", "log": str(self.log_path),
               "stderr": str(self.err_path), "lanes": (self.contract or {}).get("lanes"), "sessions": self.sessions,
               "verified": self.verified}
        try:
            with open(tl.config_dir() / "traces.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError as e:
            self.warn("could not write the trace: %s" % e)

    def warn(self, text):
        """Something a watching coordinator should look at: printed with ⚠, kept in the log, shown on the dashboard."""
        self.log("warn", text)

    def detail(self, lines):
        """Verbose mode (the default): the facts behind a step, indented under it."""
        if self.verbose:
            for ln in lines:
                if ln:
                    say("           %s" % ln[:400])

    def budget_check(self):
        mins = (time.time() - self.t0) / 60
        if self.cost > float(self.cfg["budget_usd"]) or mins > float(self.cfg["budget_min"]):
            raise Blocked("over budget: $%.2f of $%s, %d of %s min" % (self.cost, self.cfg["budget_usd"], mins,
                                                                        self.cfg["budget_min"]))

    # -- AI node
    def ai(self, node, title, prompt, resume_key=None, writer_family=None):
        """One AI node through delegate (worker-run v1): it picks lane and model, limits apply, it records the run."""
        self.budget_check()
        self.stats["nodes"] += 1
        role = ROLES[node]
        writer = writer_family if node in ("review", "verify") else None
        resume = self.writer.get("delegate") if resume_key else None
        if getattr(self, "plan_data", None):  # an unsandboxed worker can write here: every step reads the engine's plan
            (self.run_dir / "plan.json").write_text(json.dumps(self.plan_data, indent=1))
        flag = access(self.host)
        self.log("node", "%s: %s" % (node, title), node=node, backend="delegate", role=role, resume=bool(resume))
        timeout = float(self.cfg["node_timeout_min"]) * 60
        waited, attempt_prompt, attempt, errs = 0.0, prompt, 1, ["not run"]
        while attempt <= 2:
            r, j = call_delegate(self.route, role, attempt_prompt, SCHEMAS[node], self.wt, resume, timeout,
                                 self.err_path, writer, self.session, self.bead, "%s · %s: %s" % (self.bead, node, title),
                                 access=flag)
            if j is not None and j.get("v") != 2:
                raise Blocked("failed: delegate answered worker-run v%s, this engine speaks v2 (update task-loop or "
                              "delegate)" % j.get("v"))
            self.trace_call(node, role, attempt, r, j, bool(flag))
            j = j or {}
            nxt, reason, said = j.get("next"), j.get("reason") or "", (j.get("say") or r.error or "").strip()
            if j and j.get("status") == "done":
                nxt = None
            elif not j:
                nxt, reason = "fail", "no_answer"  # route.py crashed, printed nothing, or the node timeout killed it
            if reason == "lane_out" and nxt in ("retry", "owner") and resume:
                # delegate never moves a resumed thread to another lane; a new thread gets the role's next rung at once.
                # next is owner when delegate cannot say when the lane frees (no retry_after): the same move (lifesim-5ar.6)
                self.log("note", "%s: the resumed writer's lane is out (%s); going on at once as a new thread"
                         % (node, said[:160]))
                resume, attempt_prompt = None, attempt_prompt + FRESH_WRITER_TEXT
                continue
            if nxt == "retry":  # worker-run v2: delegate says when; how long a slot waits is this engine's policy
                due = float(j.get("retry_after") or 0)
                wait = max(60.0, due - time.time())
                if waited + wait > float(self.cfg["lane_wait_min"]) * 60:  # a long wait frees the slot; the checkpoint resumes
                    raise Blocked("paused: %s for %s until %s (%s: %s)" % (
                        "no network" if reason == "network" else "no lane", node,
                        time.strftime("%H:%M", time.localtime(due)) if due > time.time() else "a lane frees",
                        reason, said[:200]))
                wait = min(600.0, wait)
                self.warn("%s waits %d min (%s): %s" % (node, wait // 60, reason, said[:160]))
                time.sleep(wait)
                waited += wait
                continue
            self.cost += r.cost
            denied = "; ".join("`%s`" % (d.get("input") or d.get("tool")) for d in j.get("denied") or [])
            if nxt == "owner" and not denied:
                if reason == "lane_out":  # a new thread found no lane either and no time it frees: the bead waits, no ask
                    raise Blocked("paused: no lane for %s (lane_out, no time it frees): %s" % (node, said[:200]))
                if reason in ("logged_out", "setup"):  # the machine's to fix, not the bead's: it stays open, no ask
                    fix = ("run `codex login`" if j.get("family") == "openai" else "run `claude auth login`") \
                        if reason == "logged_out" else "set up delegate (/iorlas-delegate:init)"
                    raise Blocked("paused: %s on %s; %s on this machine, then rerun. (%s)" % (reason, node, fix, said[:200]))
                raise Blocked("needs a human: delegate stopped the %s step (%s): %s" % (node, reason, said[:400]))
            if j.get("git_violation"):
                self.warn("%s changed git: %s" % (node, "; ".join(j["git_violation"])))
            if resume_key and r.ref and j.get("status") == "done":
                self.writer["delegate"] = resume = r.ref
            errs = validate(r.data, SCHEMAS[node]) if (r.data is not None and nxt is None) else [
                "%s: %s" % (reason or "no structured output", said[:300])]
            if denied and errs:  # asking again meets the same refusal
                raise Blocked("needs a human: the %s step was denied %s and gave no answer; run it or allow it, then "
                              "rerun. (%s)" % (node, denied, (j.get("text") or said or "")[:200]))
            if denied and node == "write":  # once is a warning; twice in a bead is a pattern the owner must see
                self.denials.append(denied)
                if len(self.denials) >= 2:
                    raise Blocked("needs a human: the writer was refused commands %d times in this task (a reworded "
                                  "command may be a way around a refusal): %s. Run or allow them, then rerun."
                                  % (len(self.denials), " | ".join(self.denials)))
            if denied:
                self.warn("%s was denied %s and found another way" % (node, denied))
            if not errs:
                break
            self.log("note", "%s output invalid (try %d): %s" % (node, attempt, "; ".join(errs[:4])))
            if resume:  # one more try as a new thread: a refused or broken resume is not worth a second attempt
                resume, attempt_prompt = None, prompt
            attempt += 1
        if errs:
            raise Blocked("failed: %s node produced no valid output (%s)" % (node, "; ".join(errs[:3])))
        self.last_flag = (j or {}).get("flag")  # same_family | degraded | ...: delegate could not give the usual lane
        fam = r.backend  # openai | claude: the family that wrote, for the reviewer
        model = "%s %s on %s" % ((j or {}).get("model"), (j or {}).get("effort"), (j or {}).get("lane"))
        (self.run_dir / ("%s-%d.json" % (node, self.stats["nodes"]))).write_text(json.dumps(r.data, indent=1))
        self.log("msg", "%s → %s  [%s%s, %ds, $%.2f, total $%.2f]" % (
            node, summarize(node, r.data), fam, (":" + model) if model else "", r.secs, r.cost, self.cost),
            node=node, data=r.data, cost=r.cost, secs=round(r.secs), backend=fam)
        self.detail(details(node, r.data))
        self.anomalies(node, r, attempt)
        return r.data, fam

    def anomalies(self, node, r, attempt):
        d = r.data
        if attempt > 1:
            self.warn("%s needed a retry to produce valid output" % node)
        if r.secs > float(self.cfg["node_timeout_min"]) * 60 * 0.6:
            self.warn("%s took %d min, close to the %s min limit" % (node, r.secs // 60, self.cfg["node_timeout_min"]))
        spent = max(self.cost / float(self.cfg["budget_usd"]), (time.time() - self.t0) / 60 / float(self.cfg["budget_min"]))
        for mark in (0.5, 0.8):
            if spent > mark and mark not in self.budget_warned:
                self.budget_warned.add(mark)
                self.warn("%.0f%% of the task's budget is used" % (spent * 100))
        if node == "review" and any(f["severity"] == "high" for f in d["findings"]):
            self.warn("the reviewer found a high-severity problem")

    # -- script helpers
    def sh(self, cmd, timeout=3600, check=False, save=None, env=None):
        """A command: a string goes through bash with -e and pipefail (checks, profile commands), so a red command in a
        `;` list or a pipe fails it (lifesim-gfr.31.1: `just unity-check > log; ! grep ...` passed with unity-check
        red); `! cmd` and `cmd || true` still pass. A list runs as is (no quoting rules)."""
        self.log("cmd", cmd if isinstance(cmd, str) else " ".join(cmd))
        # Its own process group, so a timeout stops the whole tree (dotnet build nodes, Unity) and not just the shell;
        # the worker env, so a check never inherits this launcher's Claude session.
        bash = shutil.which("bash") if isinstance(cmd, str) and os.name != "nt" else None  # plans write bash
        run = [bash, "-e", "-o", "pipefail", "-c", cmd] if bash else cmd  # Windows: cmd.exe, as before
        p = subprocess.Popen(run, shell=isinstance(run, str), cwd=self.wt,
                             env=dict(child_env(), **(env or {})),
                             stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=(os.name != "nt"))
        try:
            out, _ = p.communicate(timeout=timeout)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            kill_tree(p)
            out, _ = p.communicate()
            out += b"\n(timed out after %d s: the engine stopped it and everything it started)" % int(timeout)
            rc = 124
        except BaseException:  # stopped: never leave a check (just check, Unity) running
            kill_tree(p)
            raise
        text = out.decode("utf-8", "replace")
        if save:
            Path(save).write_text(text, encoding="utf-8")
        tail = "\n".join(text.strip().splitlines()[-15:])
        self.log("note", "exit %d%s" % (rc, (": " + tail[-600:]) if rc else ""), exit=rc)
        if check and rc:
            raise Blocked("failed: `%s` exit %d\n%s" % (cmd, rc, tail))
        return rc, tail

    def base_sha(self):
        """Where the task's work starts: an earlier run's commits on the task branch count as the task's diff."""
        return self.git("merge-base", self.cfg["base"], "HEAD") or self.cfg["base"]

    def git(self, *a):
        return tl.git(*a, cwd=self.wt)

    # -- nodes
    def reset(self, bead):
        self.log("node", "reset")
        branch = (bead.get("metadata") or {}).get("branch") or "task/" + self.bead
        self.sh(["git", "fetch", "-q", "origin"], check=True)
        exclude = Path(self.git("rev-parse", "--path-format=absolute", "--git-common-dir")) / "info" / "exclude"
        if ".task/" not in (exclude.read_text() if exclude.exists() else ""):
            with open(exclude, "a") as f:
                f.write("\n.task/\n")
        exists = bool(self.git("rev-parse", "--verify", "-q", "refs/heads/" + branch))
        self.left_dirty = False
        if self.git("status", "--porcelain"):
            if self.git("symbolic-ref", "--short", "-q", "HEAD") != branch:
                raise Blocked("failed: worktree %s has uncommitted work of another branch" % self.wt)
            self.wip("left from an earlier run")
            self.left_dirty = True
        if exists:
            self.free_branch(branch)
            self.sh(["git", "checkout", "-q", branch], check=True)
        else:
            self.sh(["git", "checkout", "-q", "-B", branch, self.cfg["base"]], check=True)
        for old in self.task_dir.iterdir():  # earlier runs' files are no facts; only the writer's evidence carries over
            if old.name != "evidence":
                shutil.rmtree(old) if old.is_dir() else old.unlink()
        self.export_brief()
        self.branch = branch
        return branch

    def free_branch(self, branch):
        """A paused bead resumes in any free slot: the slot that last held its branch lets go of it (detached there),
        unless that slot has uncommitted work, which is never touched."""
        here, path = str(Path(self.wt).resolve()), None
        for line in (self.git("worktree", "list", "--porcelain") or "").splitlines():
            if line.startswith("worktree "):
                path = line[len("worktree "):]
            elif line == "branch refs/heads/" + branch and path and str(Path(path).resolve()) != here:
                if tl.git("status", "--porcelain", cwd=path):
                    raise Blocked("failed: %s is checked out in %s with uncommitted work; commit or clean it there" % (
                        branch, path))
                tl.git("checkout", "-q", "--detach", cwd=path)
                self.log("note", "%s was checked out in %s: detached it there to resume here" % (branch, path))

    def export_brief(self):
        """The task as workers read it: the bead's own text and the people's comments, never the engine's own records
        (plans, reviews, reflects pile up on every rerun: 40 of lifesim-vbo's 45 KB brief)."""
        bead, comments = tl.show(self.bead) or {"id": self.bead}, tl.comments(self.bead)
        text = brief_digest(bead, comments)
        (self.run_dir / "brief.md").write_text(text, encoding="utf-8")
        # the hash is what tells a rerun the owner changed something: the engine's own close line and labels are not that
        ours = [x for x in (self.cfg.get("pick_label"), self.cfg.get("needs_info_label")) if x]
        self.brief_hash = hashlib.sha1(brief_digest(bead, comments, owner_only=True, ignore=ours).encode("utf-8")).hexdigest()
        kb = len(text.encode("utf-8")) / 1024
        if kb > float(self.cfg["brief_kb"]):
            self.warn("the brief is %.0f KB (over %s KB): the bead may be too big for one task" % (kb, self.cfg["brief_kb"]))

    def granted_host(self, labels):
        """Whether write steps get the host. Only the committed config on the base branch grants it (engine.host for the
        repo, engine.host_beads for listed beads): a worker with Bash can label its own bead, or edit a checkout's
        .task-loop.json, but not origin/main without review and the gate. The label `sandbox` still turns it off."""
        try:
            base = json.loads(self.git("show", "%s:.task-loop.json" % self.cfg["base"]) or "{}").get("engine") or {}
        except ValueError:
            base = {}
        granted = bool(base.get("host") or base.get("no_sandbox")) or self.bead in (base.get("host_beads") or [])
        for label in ("host", "no-sandbox"):
            if label in labels and not granted:
                self.warn("label %s is ignored: the host is granted only by engine.host or engine.host_beads in "
                          ".task-loop.json on %s" % (label, self.cfg["base"]))
        if "sandbox" in labels and granted:
            self.log("note", "bead label sandbox: the write step runs sandboxed")
            granted = False
        if granted:
            self.log("note", "the write step gets the host (.task-loop.json on %s)" % self.cfg["base"])
        return granted

    def add_cases(self, new):
        """A writer may add the cases it discovers; it can never remove one (the plan is the engine's)."""
        cases = self.plan_data.setdefault("cases", [])
        have = {c["check"].strip() for c in cases}
        for c in new:
            if c["check"].strip() and c["check"].strip() not in have:
                cases.append(dict(c, by="writer"))
                have.add(c["check"].strip())
                self.log("note", "the writer added a case: %s" % c["criterion"][:200])

    def engine_unproven(self, unchecked, checks):
        """The unchecked items the engine does not prove itself: one that names the gate (it runs at land, and a red gate
        goes to a fix round) or a check that passed this round is dropped, and so is every case item once this round ran
        all the plan's cases green (only the last stage and a fix run them). lifesim-5ban.3 and lifesim-fld.27.3 stopped
        on verify asks for the gate; lifesim-gfr.31.1 on 'there is no nographics.out in evidence yet' after the case
        that writes it passed."""
        ran = [c["cmd"] for c in checks if c["exit"] == 0]
        names = [" ".join(x.split()).lower() for x in [self.cfg["gate"]] + ran if x.strip()]
        cases = self.case_checks()
        cases_ran = bool(cases) and all(c in ran for c in cases)
        out = []
        for u in unchecked:
            what = " ".join(u["what"].split()).lower()
            if any(x in what for x in names) or (cases_ran and u["kind"] == "case"):
                self.log("note", "unchecked item dropped, the engine runs it: %s" % u["what"][:200])
            else:
                out.append(u)
        return out

    def case_checks(self):
        return [c["check"] for c in (getattr(self, "plan_data", None) or {}).get("cases") or []]

    def cases_text(self):
        cases = (getattr(self, "plan_data", None) or {}).get("cases") or []
        if not cases:
            return ""
        return "\nThe task's acceptance cases (they run on the last stage; judge whether each proves its criterion):\n" + \
            "".join("- %s: `%s`%s\n" % (c["criterion"], c["check"], " (added by the writer: %s; check it does not replace "
                                                                   "a stronger case)" % c.get("why", "") if c.get("by") == "writer" else "")
                    for c in cases)

    def brief_text(self):
        """Inline, never a path: a worker's file tools reach only its worktree (delegate 0.23), and the engine's files
        live outside it so the worker cannot change them."""
        return (self.run_dir / "brief.md").read_text(encoding="utf-8")

    def plan_text(self):
        return json.dumps(getattr(self, "plan_data", None) or {}, indent=1)

    def comment(self, text):
        if not self.dry:
            tl.bd("comments", "add", self.bead, text)

    def run(self):
        outcome, why, sha, question = "failed", "", "", ""
        hb = Heartbeat(self.bead)
        try:
            bead = tl.show(self.bead)
            if not bead:
                raise Blocked("failed: bead %s not found" % self.bead)
            self.bead_title = bead.get("title") or ""
            hb.start()
            if not self.route:
                raise Blocked("failed: the engine needs the iorlas-delegate plugin (0.14.0 or later): "
                              "claude plugin install iorlas-delegate@iorlas-marketplace")
            self.contract = contract(self.route)
            if not self.contract:
                raise Blocked("failed: delegate at %s does not speak worker-run v2; update delegate (claude plugin "
                              "update iorlas-delegate@iorlas-marketplace) or this engine" % self.route)
            self.log("note", "workers: delegate %s (worker-run v2)" % self.route)
            self.reset(bead)
            self.host = self.granted_host(bead.get("labels") or [])
            self.check_ask()
            if not has_criteria(bead):
                raise Blocked("ticket: the bead has no acceptance criteria", "What proves this bead done? Add acceptance "
                              "criteria (the field, or a ## Acceptance Criteria section), then rerun.")
            plan, i, state = self.resume_point()
            if plan is None:
                plan, i, state = self.plan(again=self.replan_first), 0, None
            while i < len(plan["stages"]):
                d = self.stage(plan, i, state)
                state = None
                if d == "replan":
                    self.replans += 1
                    self.stats["replans"] = replans = self.replans
                    if replans > int(self.cfg["max_replans"]):
                        raise Blocked("stage %d stuck after %s rounds and %d re-plan(s): it needs the owner's hint, "
                                      "a split, or more budget. What failed: %s" % (
                                          i + 1, self.cfg["max_rounds"], replans - 1, self.stuck_why[:600]))
                    self.accepted = []
                    plan = self.plan(again=True)
                    i = 0
                    continue
                self.accepted.append(i)
                self.done.append(plan["stages"][i]["goal"])
                i += 1
                self.save_checkpoint(stage=i, rounds=0, n=0, feedback="", step="write" if i < len(plan["stages"]) else "land")
            gaps = self.self_verify([u for u in self.unchecked if u["kind"] in UNCHECKED_KINDS])
            if gaps:
                raise Blocked(VERIFY_GAPS + "the workers could not check: " + "; ".join(
                    "%s (%s%s)" % (u["what"], u["kind"], ("; " + u["why"]) if u.get("why") else "") for u in gaps),
                    "Check these yourself, then comment on the bead (right, or wrong and why): " + "; ".join(
                        u["what"] for u in gaps))
            sha = self.finish(bead)
            outcome = "landed" if sha else "done"
            self.drop_checkpoint()
        except Blocked as b:
            outcome = "failed" if b.why.startswith("failed:") else "blocked"
            why, question = b.why, b.question
        except Exception as e:  # the close-out must run whatever broke
            outcome, why = "failed", "failed: engine error %s: %s" % (type(e).__name__, e)
        finally:
            hb.stop()
            self.close(outcome, why, sha, question)
        return 0 if outcome in ("landed", "done") else 2

    def self_verify(self, gaps):
        """One read-only verifier call before a verify ask; returns the items that still go to the owner. Per item:
        settled with quoted evidence drops it, wrong goes to one fix round at land (max_fix_rounds; none left: to the
        owner, naming the defect), open goes to the owner. The 2026-10-21 lifesim night: lifesim-d5f.46 (a hand-written
        .meta against its siblings), lifesim-fld.26.15 (a call site) and lifesim-gfr.31.1 (an evidence file that proved
        it) each waited hours for an ask a supervisor settled in a minute by reading."""
        if not gaps:
            return gaps
        items = "".join("%d. %s (%s)\n" % (n, u["what"], u["kind"]) for n, u in enumerate(gaps, 1))
        try:
            d, _ = self.ai("verify", "%d unchecked item(s) before land" % len(gaps), VERIFY_PROMPT.format(
                brief=self.brief_text(), work=self.work_summary(), evidence=self.evidence_dir,
                where=self.where("verify"), items=items), writer_family=self.writer_family)
        except Blocked as b:  # no verifier now is no reason to land unchecked: the owner checks them, as before
            self.warn("could not self-verify before land, the owner checks every item: %s" % b.why[:300])
            return gaps
        if self.last_flag == "same_family":
            self.warn("the check before land is from the writer's own model family (no other lane was free)")
        said = {}
        for a in d["items"]:
            said.setdefault(a["n"], a)
        still, wrong = [], []
        for n, u in enumerate(gaps, 1):
            a = said.get(n) or {"verdict": "open", "evidence": "", "why": "the verifier did not answer it"}
            v, why = a["verdict"], a["why"]
            if v == "settled" and not a["evidence"].strip():
                v, why = "open", "settled without quoted evidence"
            self.verified.append({"what": u["what"], "kind": u["kind"], "verdict": v, "evidence": a["evidence"], "why": why})
            if v != "settled":
                (wrong if v == "wrong" else still).append(dict(u, why=why))
        self.log("verify", "before land: %s" % ", ".join("%d %s" % (sum(x["verdict"] == k for x in self.verified), k)
                                                         for k in VERDICTS), verified=self.verified)
        self.comment("Verify (engine): what the workers could not check, self-verified read-only before land: " + "; ".join(
            "%s: %s, %s" % (x["verdict"], x["what"], ('"%s"' % x["evidence"]) if x["verdict"] == "settled" else x["why"])
            for x in self.verified))
        if not wrong:
            return still
        if self.fixes >= int(self.cfg["max_fix_rounds"]):
            return still + [dict(u, why="found wrong: %s; no fix round left" % u["why"]) for u in wrong]
        # the wrong items stay unchecked in the fix's checkpoint: a fix round that pauses resumes at land and verifies
        # them again, never lands them; the fix's review adds what it leaves unproven
        self.unchecked = [u for u in self.unchecked if u["kind"] not in UNCHECKED_KINDS] + still + wrong
        done = self.fix("verify", "".join("- %s: %s\n" % (u["what"], u["why"]) for u in wrong))
        fixed = {u["what"] for u in wrong}
        self.unchecked = [u for u in self.unchecked if u["what"] not in fixed]
        left = [u for u in self.unchecked if u["kind"] in UNCHECKED_KINDS]
        if done != "accept":
            left += [dict(u, why="found wrong: %s; the fix round did not pass" % u["why"]) for u in wrong]
        return left

    def work_summary(self):
        """The task's changed files with their line counts, untracked files included."""
        tree = self.tree_hash()
        return (tl.git("diff", "--stat", self.base_sha(), tree, cwd=self.wt) if tree else "") or "(no files changed)"

    def plan(self, again=False):
        why = ""
        if again:
            try:
                why = (self.run_dir / "replan.md").read_text(encoding="utf-8")[-6000:]
            except OSError:
                pass
        extra = ("\n\nThe previous plan did not work. What failed:\n<failed>\n%s\n</failed>\nPlan again." % why) if again else ""
        rules = []
        if self.cfg["worker_rules"]:
            rules.append("Read %s: this repo's rules for workers (what runs where, known pitfalls of its tools); the "
                         "checks you write must follow them." % (Path(self.wt) / self.cfg["worker_rules"]))
        rules.append("Proof files that a check reads or a reviewer looks at (screenshots, logs, probe output) go under "
                     "%s: it is kept across runs, and nothing else under %s is." % (self.evidence_dir, self.task_dir))
        rules.append("Checks run on the uncommitted working tree after each write. The engine runs the gate%s once, on "
                     "the rebased tree at land: never put %s in a stage's checks, and a criterion that names it is proven "
                     "by that land gate: write no case for it." % (
                         (" (`%s`)" % self.cfg["gate"]) if self.cfg["gate"] else "",
                         ("`%s`" % self.cfg["gate"]) if self.cfg["gate"] else "it"))
        if self.verify_answer:
            extra += ("\n\nEvery stage was accepted, then the owner checked the work and answered:\n<answer>\n%s\n</answer>\n"
                      "Plan only the work this answer asks for. If it asks for nothing more (it says the work is right), "
                      "return no stages: the engine then lands." % self.verify_answer)
        if self.done:
            extra += ("\n\nThese stages are already accepted on this branch (reviewed, their work is in the tree): "
                      "do not plan them again; plan only what the task still needs.\n" +
                      "".join("- %s\n" % g for g in self.done))
        prompt = (PLAN_PROMPT.format(brief=self.brief_text(), wt=self.wt) + extra + "\n\n" + "\n".join(rules) +
                  ("\n\n" + self.where("plan") if self.where("plan") else ""))
        data, _ = self.ai("plan", "re-plan" if again else "plan", prompt)
        bad = tracker_checks(data)
        if bad:  # asked once to rewrite them, like an invalid answer
            self.warn("the plan's checks read the issue tracker, sent back: %s" % "; ".join(bad)[:300])
            data, _ = self.ai("plan", "rewrite tracker checks", prompt + TRACKER_TEXT % "\n".join("- `%s`" % c for c in bad))
            bad = tracker_checks(data)
            if bad:
                raise Blocked("failed: the plan's checks still read the issue tracker after one rewrite: %s"
                              % "; ".join(bad)[:400])
        data = json.loads(json.dumps(data))  # the engine's own copy: cases are added to it as the task runs
        if self.verify_answer and not data["stages"] and not data["question"].strip():
            self.log("note", "the planner finds the owner's answer asks for nothing more: landing")
            self.plan_leftovers(data)
            return data
        self.plan_summary = data["summary"]
        for c in data.get("cases") or []:
            c.setdefault("by", "plan")
        self.plan_data = data
        if data["question"].strip():
            raise Blocked("owner decision needed", data["question"])
        if not data["stages"]:
            raise Blocked("failed: the plan has no stages")
        big = int(self.cfg["max_stages"])
        if len(data["stages"]) > big and (self.answered or {}).get("kind") != "ticket":
            raise Blocked("ticket: the plan has %d stages (more than %d): the bead may be too big for one task" % (
                len(data["stages"]), big), "Split the bead into these, or comment that it stays one bead:\n" + "\n".join(
                "%d. %s" % (k + 1, s["goal"]) for k, s in enumerate(data["stages"])))
        self.plan_leftovers(data)
        lines = ["Plan (engine): " + data["summary"]]
        lines += ["%d. %s%s [files: %s] [checks: %s]" % (n + 1, s["goal"], " (hard)" if s["hard"] else "",
                                                          ", ".join(s["files"]), "; ".join(s["checks"]))
                  for n, s in enumerate(data["stages"])]
        lines += ["Risk: %s → %s" % (r["what"], r["check"]) for r in data["risks"]]
        self.comment("\n".join(lines))
        (self.run_dir / "plan.json").write_text(json.dumps(data, indent=1))
        self.export_brief()
        self.save_checkpoint(stage=0, rounds=0, n=0, feedback="", step="write")
        return data

    def plan_leftovers(self, data):
        """The follow-up work the plan wants filed: filed at the close with the reviews' leftovers. Only a plan the run
        goes on with adds them, so a plan that asks the owner is not filed twice by the plan after the answer."""
        have = {lo["title"] for lo in self.leftovers}
        self.leftovers += [lo for lo in data["leftovers"] if lo["title"] not in have]

    # -- checkpoints: where a stopped run was, outside the worktree, so the next run goes on from there
    def ask_path(self):
        return tl.config_dir() / "asks" / ("%s.json" % self.bead)

    def check_ask(self):
        """An open ask is never asked again: with the bead unchanged the run waits; a change (the owner's comment or
        edit) answers it, and the run goes on from its checkpoint."""
        try:
            a = json.loads(self.ask_path().read_text())
        except (OSError, ValueError):
            return
        if a.get("status") != "open":
            return
        if a.get("brief") == self.brief_hash and not self.cfg.get("fresh"):
            raise Blocked("waiting: for the owner's answer to ask %s (%s): %s" % (a["id"], a["kind"], a["question"][:200]))
        a.update(status="answered", answered=time.time())
        self.ask_path().write_text(json.dumps(a, indent=1))
        self.answered = a
        self.log("note", "ask %s (%s) is answered: the bead changed since it was asked" % (a["id"], a["kind"]))

    def answer_text(self, a):
        """The owner's answer to ask a: the dashboard's, else the people's comments after the engine's ask comment."""
        if (a.get("answer") or "").strip():
            return a["answer"].strip()
        comments = tl.comments(self.bead)
        start = max([k + 1 for k, c in enumerate(comments)
                     if (c.get("text") or "").startswith("Ask (engine) %s " % a["id"])] or [0])
        return "\n".join((c.get("text") or "").strip() for c in comments[start:]
                         if not (c.get("text") or "").startswith(ENGINE_NOTES)).strip()

    def raise_ask(self, kind, why, question):
        try:
            n = int(json.loads(self.ask_path().read_text()).get("n", 0)) + 1
        except (OSError, ValueError):
            n = 1
        a = {"v": 1, "id": "%s-%d" % (self.bead, n), "n": n, "bead": self.bead, "kind": kind,
             "question": (question or why)[:4000], "why": why[:4000], "run": self.log_path.stem, "t": time.time(),
             "parks_at": time.time() + 3 * 86400, "brief": self.brief_hash, "status": "open"}
        common = self.git("rev-parse", "--path-format=absolute", "--git-common-dir")
        a.update(repo=str(Path(common).parent) if common else str(self.wt),
                 title=(getattr(self, "bead_title", "") or "")[:200])
        self.ask_path().parent.mkdir(exist_ok=True)
        self.ask_path().write_text(json.dumps(a, indent=1))
        moved = self.leave_queue() if kind in ("decision", "ticket") else ""
        self.comment("Ask (engine) %s (%s): %s%s" % (a["id"], kind, a["question"][:1500], moved))
        self.notify(a)
        return a

    def leave_queue(self):
        """A decision or ticket ask means the bead lacks what it needs to be done unattended: drop the pick label so no
        runner takes it again, add needs-info. Answering does not put it back; the owner relabels it (an answer can
        split the bead). Verify and stuck asks keep it: the work is there, a fact or a hint is missing."""
        pick, info = self.cfg.get("pick_label") or "", self.cfg.get("needs_info_label") or ""
        if not pick or self.dry or pick not in ((tl.show(self.bead) or {}).get("labels") or []):
            return ""
        tl.bd("label", "remove", self.bead, pick)
        if info:
            tl.bd("label", "add", self.bead, info)
        return "\n(Out of the %s queue: label %s removed%s; relabel it %s once it can be done unattended.)" % (
            pick, pick, ", %s added" % info if info else "", pick)

    def notify(self, a):
        """The owner's push: ~/.config/task-loop/notify holds one shell command (ntfy, Pushover, a Telegram bot...);
        it gets TL_ASK_KIND, TL_ASK_BEAD, TL_ASK_ID and TL_ASK_TEXT. Which service is the owner's choice."""
        f = tl.config_dir() / "notify"
        try:
            cmd = f.read_text(encoding="utf-8").strip()
        except OSError:
            return
        if not cmd:
            return
        env = dict(os.environ, TL_ASK_KIND=a["kind"], TL_ASK_BEAD=a["bead"], TL_ASK_ID=a["id"],
                   TL_ASK_TEXT=a["question"][:500])
        try:
            subprocess.Popen(cmd, shell=True, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=(os.name != "nt"))
        except OSError as e:
            self.warn("notify failed: %s" % e)

    def checkpoint_path(self):
        return tl.config_dir() / "checkpoints" / ("%s.json" % self.bead)

    def save_checkpoint(self, **at):
        # mid-rebase (a conflict fix) HEAD is detached: the checkpoint names the task branch the close goes back to
        branch = self.git("symbolic-ref", "--short", "-q", "HEAD") or getattr(self, "task_branch", "")
        rec = {"v": 1, "bead": self.bead, "branch": branch,
               "plan": self.plan_data, "done": self.done, "accepted": self.accepted, "replans": self.replans, "fixes": self.fixes, "denials": self.denials,
               "writer": self.writer.get("delegate") or "", "brief": self.brief_hash, "head": self.git("rev-parse", "HEAD"),
               "unchecked": self.unchecked, "filed": self.filed,
               "closed": False,
               "run": self.log_path.stem, "t": time.time(), **at}
        p = self.checkpoint_path()
        p.parent.mkdir(exist_ok=True)
        p.write_text(json.dumps(rec, indent=1))

    def mark_checkpoint_closed(self, why=""):
        """The close step committed everything: the checkpoint's head is now exactly what the next run should find. A
        red gate at land is no stop: the next run re-plans with the gate's output, or it would rerun the same red gate."""
        try:
            ck = json.loads(self.checkpoint_path().read_text())
        except (OSError, ValueError):
            return
        ck.update(head=self.git("rev-parse", "HEAD"), closed=True, filed=self.filed)
        if why.startswith("gate red"):
            ck.update(step="gate-red", gate_tail=why[-3000:])
        self.checkpoint_path().write_text(json.dumps(ck, indent=1))

    def drop_checkpoint(self):
        try:
            self.checkpoint_path().unlink()
        except OSError:
            pass

    def resume_point(self):
        """(plan, stage index, stage state) from the last run's checkpoint, or (None, 0, None) to plan afresh. A tree
        changed since (someone edited the branch) starts over; a changed bead keeps the accepted stages and re-plans
        the rest; otherwise the run goes on at the same stage and round, with the same writer thread, or straight to
        land when every stage was accepted."""
        self.replan_first = False
        if self.cfg.get("fresh"):
            self.drop_checkpoint()
        try:
            ck = json.loads(self.checkpoint_path().read_text())
        except (OSError, ValueError):
            return None, 0, None
        branch = self.git("symbolic-ref", "--short", "-q", "HEAD")
        if ck.get("v") != 1 or ck.get("branch") != branch or not ck.get("plan"):
            self.drop_checkpoint()
            return None, 0, None
        head = self.git("rev-parse", "HEAD")
        ours = head == ck["head"] or (self.left_dirty and not ck["closed"] and self.git("rev-parse", "HEAD~1") == ck["head"])
        if not ours:  # a commit, or an edit after a clean close, that is not this engine's: the plan may not fit it
            self.log("note", "the branch changed since the checkpoint of %s: planning again from the start" % ck["run"])
            self.drop_checkpoint()
            return None, 0, None
        self.done = list(ck["done"])
        self.replans, self.fixes = int(ck.get("replans") or 0), int(ck.get("fixes") or 0)
        self.denials = list(ck.get("denials") or [])
        self.filed = list(ck.get("filed") or [])
        if ck["writer"]:
            self.writer["delegate"] = ck["writer"]
        if ck["step"] == "gate-red":
            self.log("note", "the gate was red at land in %s: re-planning with its output, keeping %d accepted stage(s)"
                     % (ck["run"], len(self.done)))
            (self.run_dir / "replan.md").write_text(
                "Every stage was accepted, then the gate failed on the tree rebased onto the latest base (often "
                "another task landed first). Plan the fix.\n\n" + ck.get("gate_tail", ""))
            self.replan_first = True
            return None, 0, None
        if ck["brief"] != self.brief_hash and ck["step"] == "land" and (self.answered or {}).get("kind") == "verify":
            self.plan_data, self.plan_summary = ck["plan"], ck["plan"]["summary"]
            answer = self.answer_text(self.answered)
            gaps = (self.answered.get("why") or "").startswith(VERIFY_GAPS)  # not a denial's ask: its answer is a rerun
            if not gaps or confirms(answer):
                self.log("note", "the owner answered verify ask %s (%s): going straight to land" % (
                    self.answered["id"], answer))
                return ck["plan"], len(ck["plan"]["stages"]), None
            # lifesim-fld.26.15: 'add a test that ..., then land' landed without the test; any answer but a plain yes
            # goes to the planner, which plans what it asks for, or nothing (then the run lands)
            self.verify_answer = answer or "(no comment: the owner edited the bead)"
            self.log("note", "the owner answered verify ask %s with more than a yes: planning what it asks, keeping %d "
                             "accepted stage(s)" % (self.answered["id"], len(self.done)))
            return None, 0, None
        if ck["brief"] != self.brief_hash:
            self.log("note", "the bead changed since the checkpoint of %s: keeping %d accepted stage(s), planning the rest"
                     % (ck["run"], len(self.done)))
            return None, 0, None
        self.plan_data, self.plan_summary, self.accepted = ck["plan"], ck["plan"]["summary"], list(ck["accepted"])
        (self.run_dir / "plan.json").write_text(json.dumps(ck["plan"], indent=1))
        stages = ck["plan"]["stages"]
        if ck["step"] == "land" or ck["stage"] >= len(stages):
            self.unchecked = list(ck.get("unchecked") or [])  # still unproven: verified again before land
            self.log("note", "resuming %s: every stage was accepted, going straight to land" % ck["run"])
            return ck["plan"], len(stages), None
        self.log("note", "resuming %s at stage %d/%d, round %d (write %d)" % (
            ck["run"], ck["stage"] + 1, len(stages), ck["rounds"] + 1, ck["n"] + 1))
        return ck["plan"], ck["stage"], {"rounds": ck["rounds"], "n": ck["n"], "feedback": ck["feedback"]}

    def stage(self, plan, i, state=None):
        """Write → checks → review until the review is clean. A red check goes straight back to the writer (it never
        reaches the reviewer); max_check_tries red in a row, or a review that sends it back, use up a round; when the
        rounds are used up the stage asks for a re-plan. Accept is a rule: checks green and nothing blocking in the
        review (high/medium findings, unmet requirements). The writer's or the reviewer's question is the owner's."""
        st = plan["stages"][i]
        last = i == len(plan["stages"]) - 1
        state = state or {}
        fix = state.get("fix")
        name = state.get("name") or "stage %d/%d" % (i + 1, len(plan["stages"]))
        feedback, rounds, red, n = state.get("feedback", ""), state.get("rounds", 0), 0, state.get("n", 0)
        while True:
            if not fix:  # a fix runs at land: its checkpoint stays at land, and a resume lands again
                self.save_checkpoint(stage=i, rounds=rounds, n=n, feedback=feedback, step="write")
            n += 1
            self.stats["writes"] += 1
            if n >= 2:
                self.warn("%s: write %d (round %d)" % (name, n, rounds + 1))
            w, wfam = self.ai("write", "%s write %d" % (name, n), WRITE_PROMPT.format(
                brief=self.brief_text(), plan=self.plan_text(), n=i + 1, goal=st["goal"],
                files=", ".join(st["files"]), checks="\n".join("- " + c for c in st["checks"]) or "- (none named)",
                feedback=feedback, evidence=self.evidence_dir, where=self.where("write"), gate=(" (`%s`)" % self.cfg["gate"]) if self.cfg["gate"] else "",
                rules=("\nRead %s first: this repo's rules for work in your sandbox (what runs there, what does not)."
                       % (Path(self.wt) / self.cfg["worker_rules"])) if self.cfg["worker_rules"] else "") +
                "\nThe plan's acceptance cases run on the last stage. If you find a case they miss, add it to new_cases (the "
                "criterion it proves, the check, why); never remove or weaken one." + ("" if last else LATER_CASES) +
                UNCHECKED_TEXT, resume_key="writer")
            self.writer_family = wfam
            wrote_unchecked = w.get("unchecked") or []  # the review decides what is still unproven after the checks
            if w["question"].strip() and w["decided"].strip():  # lifesim-d5f.58: an accepted requirement is no question
                rounds += 1
                self.stats["rounds"] += 1
                self.stuck_why = "the writer asked what an accepted requirement decides: %s" % w["decided"]
                self.warn("%s: %s" % (name, self.stuck_why[:300]))
                if rounds >= int(self.cfg["max_rounds"]):
                    (self.run_dir / "replan.md").write_text(self.stuck_why + "\n\nThe question: " + w["question"])
                    return "replan"
                feedback = DECIDED_TEXT % (w["question"], w["decided"])
                continue
            if w["question"].strip():
                raise Blocked("owner decision needed", w["question"])
            self.add_cases(w.get("new_cases") or [])
            checks = self.run_checks(dict(st, checks=st["checks"] + (self.case_checks() if last else [])), name)
            (self.run_dir / "engine-checks.json").write_text(json.dumps(checks, indent=1))
            self.stats["tests_added"], self.stats["tests_removed"] = count_tests(self.task_diff(), self.cfg["test_pattern"])
            if self.stats["tests_removed"]:
                self.warn("the task's diff removes %d tests" % self.stats["tests_removed"])
            failed = [c for c in checks if c["exit"] not in (0, None)]
            flagged = {b["cmd"].strip(): b["why"] for b in w["bad_checks"]}
            wrong = [c for c in failed if c["cmd"].strip() in flagged]
            if wrong:  # a check no code change can satisfy: retrying it is waste, the plan must change
                self.stuck_why = "the writer says these stage checks are wrong: " + "; ".join(
                    "`%s` (exit %s): %s" % (c["cmd"], c["exit"], flagged[c["cmd"].strip()]) for c in wrong)
                self.warn("%s: %s" % (name, self.stuck_why[:300]))
                (self.run_dir / "replan.md").write_text(self.stuck_why + "\n\nTheir output:\n" + compact(wrong))
                return "replan"
            if failed:
                red += 1
                feedback = ("\nThese checks fail (run by the engine, outside your sandbox). Fix exactly this:\n%s\n"
                            % compact(failed))
                if red < int(self.cfg["max_check_tries"]):
                    continue
                red, rounds = 0, rounds + 1
                self.stats["rounds"] += 1
                self.stuck_why = "checks still red after %s tries: %s" % (self.cfg["max_check_tries"], compact(failed))
                if rounds >= int(self.cfg["max_rounds"]):
                    (self.run_dir / "replan.md").write_text(self.stuck_why)
                    return "replan"
                continue
            red = 0
            self.stats["reviews"] += 1
            open_items = list({u["what"]: u for u in ([] if fix else self.unchecked) + wrote_unchecked}.values())
            review, _ = self.ai("review", name, REVIEW_PROMPT.format(
                brief=self.brief_text(), plan=self.plan_text(), n=i + 1, goal=st["goal"],
                base=self.base_sha(), checks=compact(checks), summary=w["summary"], evidence=self.evidence_dir,
                gate=(" (`%s`)" % self.cfg["gate"]) if self.cfg["gate"] else "",
                added=self.stats["tests_added"], removed=self.stats["tests_removed"],
                scope=(state["scope"] if fix else
                       "the stage goal and every requirement and acceptance criterion of the task" if last else
                       "the stage goal (later stages cover the rest of the task)")) +
                ("\n" + self.where("review") if self.where("review") else "") + self.cases_text() +
                ("The engine ran every case above with the checks, so a case is never an unchecked item; a case whose "
                 "check does not prove its criterion is a finding.\n" if last and self.case_checks() else "") +
                ("\nNobody has checked these yet (earlier stages or the writer could not; the engine's checks above ran "
                 "after them); put in your unchecked only what is still unproven:\n" + "".join(
                     "- %s (%s)\n" % (u["what"], u["kind"]) for u in open_items) if open_items else "") +
                ("" if last else LATER_CASES) + UNCHECKED_TEXT,
                writer_family=wfam)
            # lifesim-gfr.31.1: a stage-1 item that stage 2 ran green still stopped the land; each review re-judges what
            # is open, so its list replaces it. A fix at land reviews only the fix: it adds, never clears.
            judged = self.engine_unproven(review.get("unchecked") or [], checks)
            self.unchecked = self.unchecked + judged if fix else judged
            same = self.last_flag == "same_family"
            if same:
                self.warn("%s: the review is from the writer's own model family (no other lane was free)" % name)
            if review["findings"] or review["unmet"] or same:
                self.comment("Review (engine, %s%s): " % (name, ", same family as the writer" if same else "") + "; ".join(
                    ["%s:%s [%s] %s" % (f["file"], f["line"], f["severity"], f["fix"]) for f in review["findings"]] +
                    ["unmet: " + u for u in review["unmet"]]) or "no findings")
            self.leftovers += review["leftovers"]
            if review["question"].strip() and review["decided"].strip():  # lifesim-d5f.58: a fix round, not an ask
                self.log("note", "%s: the review asked what an accepted requirement decides (%s): sending it back"
                         % (name, review["decided"][:200]))
                review["unmet"] = review["unmet"] + ["%s (an accepted requirement decides it: meet it) %s" % (
                    review["decided"], review["question"])]
            elif review["question"].strip():
                raise Blocked("owner decision needed", review["question"])
            blocking = [f for f in review["findings"] if f["severity"] in ("high", "medium")]
            if not blocking and not review["unmet"]:
                return "accept"
            rounds += 1
            self.stats["rounds"] += 1
            self.stuck_why = "the review still sends it back: %s" % "; ".join(
                review["unmet"] + ["%s:%s %s" % (f["file"], f["line"], f["fix"]) for f in blocking])
            if rounds >= int(self.cfg["max_rounds"]):
                (self.run_dir / "replan.md").write_text(self.stuck_why)
                return "replan"
            feedback = ("\nThe reviewer sent the stage back. Fix exactly this:\n%s%s\n" % (
                "".join("- unmet: %s\n" % u for u in review["unmet"]),
                "".join("- %s:%s [%s] %s\n" % (f["file"], f["line"], f["severity"], f["fix"]) for f in blocking)))

    def where(self, node):
        """What the step is for, never what its sandbox allows: delegate tells each worker that (worker-run v2)."""
        if node == "write":
            return ("Before you say it is done, run the stage's checks you can (the build, the tests the stage names), so "
                    "an error never reaches the engine; the engine reruns every check after you. If a command is "
                    "refused, do not reword it to get around the refusal: say which command and why you needed it.")
        return "You may run commands to check facts (read files, run a linter or a test); never edit, create or delete files."

    def tree_hash(self):
        """The worktree as git would commit it now, untracked files included, without touching the real index."""
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, GIT_INDEX_FILE=os.path.join(d, "index"))
            for args in (["read-tree", "HEAD"], ["add", "-A"]):
                subprocess.run(["git"] + args, cwd=self.wt, env=env, capture_output=True)
            r = subprocess.run(["git", "write-tree"], cwd=self.wt, env=env, capture_output=True, text=True)
            return r.stdout.strip()

    def task_diff(self):
        """The task's diff against where it started, untracked files included."""
        tree = self.tree_hash()
        return tl.git("diff", self.base_sha(), tree, cwd=self.wt) if tree else self.git("diff", self.base_sha())

    def changed_paths(self):
        """Paths the task changed since it started, untracked files included."""
        tree = self.tree_hash()
        out = tl.git("diff", "--name-only", self.base_sha(), tree, cwd=self.wt) if tree else ""
        return [p for p in out.splitlines() if p]

    def run_checks(self, st, name):
        """One engine step, no AI: the repo's checks (engine.checks) and the stage's acceptance checks, grouped
        static → tests → acceptance; a red group skips the groups after it. A repo check with `when` runs only when the
        task changed a matching path; `retry` reruns a red one (known flaky). A repo check that passed on the same tree
        and base is not run again, unless it says `"cache": false`; a stage check always runs, since a plan's check can
        read what git cannot see (a running editor, a log, a bead comment). The gate is not here: it runs once, on the rebased tree, at land."""
        self.log("node", "checks: %s" % name)
        items = [{"id": c.get("id") or c["cmd"], "cmd": c["cmd"], "group": c.get("group") or "tests",
                  "when": c.get("when") or [], "retry": int(c.get("retry") or 0),
                  "cache": c.get("cache", True) is not False} for c in self.cfg["checks"]]
        items += [{"id": c, "cmd": c, "group": "acceptance", "when": [], "retry": 0, "cache": False} for c in st["checks"]]
        items.sort(key=lambda c: GROUPS.index(c["group"]) if c["group"] in GROUPS else 1)
        cache_path = tl.config_dir() / "check-cache" / ("%s.json" % self.bead)
        try:
            cache = json.loads(cache_path.read_text())
        except (OSError, ValueError):
            cache = {}
        key = "%s %s" % (self.tree_hash(), self.git("rev-parse", self.cfg["base"]))
        logs = self.run_dir / "checks"
        logs.mkdir(exist_ok=True)
        out, red, changed, passed = [], None, None, set()
        for n, c in enumerate(items):
            base = {"cmd": c["cmd"], "id": c["id"], "group": c["group"]}
            if red and c["group"] != red:
                out.append(dict(base, exit=None, status="skipped", why="%s failed first" % red, tail=""))
                continue
            if c["when"]:
                changed = self.changed_paths() if changed is None else changed
                if not any(fnmatch.fnmatch(p, g) for p in changed for g in c["when"]):
                    out.append(dict(base, exit=None, status="skipped", tail="",
                                    why="no change under %s" % ", ".join(c["when"])))
                    continue
            cmd = c["cmd"]
            if c["group"] == "acceptance":  # a repo check that passed this round is not run again inside a stage check
                cmd, used = reuse_passed(c["cmd"], passed)
                if used:
                    self.log("note", "`%s` already passed this round: not run again in `%s`" % ("`, `".join(used), c["cmd"][:120]))
            hit = c["cache"] and cache.get(key, {}).get(c["cmd"])
            if hit:
                res = dict(base, **hit)
                res.update(cached=True, status=hit.get("status") or ("ran" if hit["exit"] == 0 else "failed"))
            else:
                t, tries = time.time(), 0
                while True:
                    tries += 1
                    rc, tail = self.sh(cmd, timeout=float(self.cfg["node_timeout_min"]) * 60,
                                       save=logs / ("%02d-%s.log" % (n, re.sub(r"[^\w.-]+", "_", c["id"])[:40])))
                    if rc == 0 or tries > c["retry"]:
                        break
                    self.warn("`%s` failed (exit %d), retrying: it is marked flaky" % (c["id"], rc))
                res = dict(base, exit=rc, status="ran" if rc == 0 else "failed", tries=tries, tail=tail[-1500:],
                           secs=round(time.time() - t))
                if rc == 0 and c["cache"]:  # only a pass is a fact about the tree; a failure can come from outside git (stale
                    cache.setdefault(key, {})[c["cmd"]] = res  # build output, a held editor, a flake) and must rerun
            out.append(res)
            if res["exit"] == 0 and c["group"] != "acceptance" and not res.get("cached"):  # its output files are fresh
                passed.add(" ".join(c["cmd"].split()))
            if res["exit"] != 0:
                red = c["group"]
        for c in out:
            mark = {"ran": "✓", "failed": "✗", "skipped": "–"}[c["status"]]
            self.detail(["%s [%s] `%s` %s%s" % (mark, c["group"], c["id"], c["status"] if c["exit"] is None else
                                                "exit %d" % c["exit"], " (" + c["why"] + ")" if c.get("why") else
                                                " (same tree and base: earlier result)" if c.get("cached") else "")] +
                        (c["tail"].splitlines()[-3:] if c["status"] == "failed" else []))
        cache_path.parent.mkdir(exist_ok=True)
        cache_path.write_text(json.dumps({key: cache[key]} if key in cache else {}))  # only the latest tree is worth keeping
        return out

    def finish(self, bead):
        if not self.git("status", "--porcelain"):
            if self.git("rev-list", "--count", "%s..HEAD" % self.cfg["base"]) in ("", "0"):
                self.log("note", "nothing changed")
                return ""
        # one commit per task, titled after the bead: earlier runs' wip commits are folded in
        base = self.git("merge-base", "HEAD", self.cfg["base"])
        if base:
            self.sh(["git", "reset", "-q", "--soft", base], check=True)
        self.sh(["git", "add", "-A"], check=True)
        msg = "%s (%s)" % (bead.get("title", self.bead)[:72], self.bead)
        rc, tail = self.sh(["git", "commit", "-q", "-m", msg])
        if rc:
            raise Blocked("failed: commit refused (hooks)\n" + tail)
        if self.dry:
            self.log("note", "dry run: not landing")
            return ""
        pushes = 0
        self.task_branch = self.git("symbolic-ref", "--short", "-q", "HEAD")
        while True:  # one land at a time per repo: rebase, gate and push see the latest base; a fix runs outside the lock
            problem = None
            with self.land_lock():
                self.log("node", "land (try %d)" % (pushes + 1))
                rc, tail = self.sh(["git", "fetch", "-q", "origin"])
                if rc == 0:
                    rc, tail = self.sh(["git", "rebase", "-q", self.cfg["base"]])
                if rc:
                    unmerged = self.git("diff", "--name-only", "--diff-filter=U")
                    if not unmerged:
                        self.sh(["git", "rebase", "--abort"])
                        raise Blocked("failed: fetch or rebase onto %s failed; branch kept\n%s" % (self.cfg["base"], tail))
                    problem = ("conflict", "Conflicted files: %s\n%s" % (", ".join(unmerged.split()), tail))
                elif self.cfg["gate"]:
                    rc, tail = self.sh(self.cfg["gate"])
                    if rc:
                        problem = ("gate", tail)
                if not problem:
                    rc, tail = self.sh(self.cfg["land"], env={"TASK_LOOP_GATED_TREE": self.git("rev-parse", "HEAD^{tree}")}
                                       if self.cfg["gate"] else None)  # a pre-push hook may skip a gate this tree passed
                    if rc == 0:
                        sha = self.git("rev-parse", "HEAD")
                        tl.cmd_land(Args(id=self.bead, sha=sha, worktree=self.wt))
                        return sha
                    if not re.search(r"rejected|non-fast-forward|fetch first|stale info", tail):
                        raise Blocked("land failed\n" + tail)
                    pushes += 1
                    if pushes >= 5:
                        raise Blocked("land rejected 5 times: main moves too fast")
                    self.warn("push rejected (main moved), try %d of 5" % pushes)
                    continue
            self.fix(*problem)

    FIX = {"gate": ("make the gate pass on the tree rebased onto the latest base",
                    "\nAll stages were accepted, then the gate%s failed on the tree rebased onto the latest base (another "
                    "task may have landed first). Fix exactly this, without undoing what the stages built:\n%s\n"),
           "conflict": ("resolve the merge conflict with the latest base",
                        "\nAll stages were accepted, then rebasing onto the latest base hit a merge conflict (another task "
                        "landed first)%s. The conflict markers are in the files: resolve every one, keeping both changes' "
                        "intent. Do not run git.\n%s\n"),
           "verify": ("fix what the check before land found wrong",
                      "\nAll stages were accepted; then a check before land found these wrong. Fix exactly this, without "
                      "undoing what the stages built:\n%s\n")}
    MARKERS = "! git grep -n -I -E '^(<<<<<<<|>>>>>>>)( |$)' -- ."

    def fix(self, kind, tail):
        """One fix round at land: write → checks (every stage's checks, again) → a review of the fix only. A gate fix is
        folded into the task's commit; a conflict fix continues the rebase; a verify fix (what the verifier found wrong,
        before the task's commit) stays in the tree. max_fix_rounds per bead, then stuck. Returns the fix stage's end."""
        self.fixes += 1
        limit = int(self.cfg["max_fix_rounds"])
        what = {"gate": "gate red on the rebased tree", "conflict": "merge conflict with main",
                "verify": "the check before land found defects"}[kind]
        if self.fixes > limit:
            if kind == "conflict":
                self.sh(["git", "rebase", "--abort"])
            raise Blocked("%s after %d fix rounds: it needs the owner's hint\n%s" % (what, limit, tail[-3000:]))
        self.warn("land: %s, fix round %d of %d" % (what, self.fixes, limit))
        self.save_checkpoint(stage=len((self.plan_data or {}).get("stages") or []), rounds=0, n=0, feedback="", step="land")
        checks = list(dict.fromkeys(c for s in (self.plan_data or {}).get("stages") or [] for c in s["checks"]))
        if kind == "conflict":
            checks.append(self.MARKERS)
        goal, text = self.FIX[kind]
        st = {"goal": "Fix: " + goal, "files": [], "checks": checks, "hard": False}
        d = self.stage({"stages": [st]}, 0, {
            "fix": True, "name": "fix %d/%d" % (self.fixes, limit),
            "feedback": text % tail if kind == "verify" else text % (
                (" (`%s`)" % self.cfg["gate"]) if kind == "gate" and self.cfg["gate"] else "",
                compact([{"cmd": self.cfg["gate"] or "rebase", "exit": 1, "status": "failed", "group": "gate",
                          "tail": tail[-4000:]}])),
            "scope": "the fix only: it must %s without breaking what the accepted stages built" % goal})
        if kind == "conflict":
            if self.sh(self.MARKERS)[0]:
                return self.fix("conflict", "conflict markers are still in the tree after the fix")
            self.sh(["git", "add", "-A"], check=True)
            rc, out = self.sh(["git", "-c", "core.editor=true", "rebase", "--continue"])
            if rc:
                self.sh(["git", "rebase", "--abort"])
                raise Blocked("failed: the rebase did not continue after the conflict fix\n" + out)
        elif kind == "gate" and self.git("status", "--porcelain"):
            self.sh(["git", "add", "-A"], check=True)
            self.sh(["git", "commit", "-q", "--amend", "--no-edit"], check=True)
        if d != "accept" and kind != "verify":
            self.warn("land: the fix round did not pass its checks and review; landing tries the gate again")
        return d

    @contextlib.contextmanager
    def land_lock(self):
        """One land at a time per repo, across slots and sessions: an flock the OS drops when the process dies."""
        d = tl.config_dir() / "locks"
        d.mkdir(exist_ok=True)
        url = self.git("remote", "get-url", "origin") or str(self.wt)
        path = d / ("land-%s.lock" % hashlib.sha1(url.encode()).hexdigest()[:12])
        f = open(path, "a+")
        try:
            if fcntl:
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    self.log("note", "waiting for the land lock (held by %s)" % (path.read_text().strip() or "?"))
                    fcntl.flock(f, fcntl.LOCK_EX)
            f.seek(0)
            f.truncate()
            f.write(self.bead)
            f.flush()
            yield path
        finally:
            if fcntl:
                fcntl.flock(f, fcntl.LOCK_UN)
            f.close()

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

    def wip(self, why):
        self.sh(["git", "add", "-A"])
        rc, _ = self.sh(["git", "commit", "-q", "-m", "wip (%s): %s" % (self.bead, why)])
        return rc == 0

    def close(self, outcome, why, sha, question):
        old = None
        if hasattr(signal, "SIGTERM") and threading.current_thread() is threading.main_thread():
            old = signal.signal(signal.SIGTERM, signal.SIG_IGN)  # a second stop must not break the close-out
        try:
            self._close(outcome, why, sha, question)
        finally:  # what the process starts after this (a notify command, the next test) must stay stoppable
            if old is not None:
                signal.signal(signal.SIGTERM, old)

    def _close(self, outcome, why, sha, question):
        why = why or ("stopped before a reason was recorded" if outcome == "failed" else "")
        mins = (time.time() - self.t0) / 60
        gd = Path(self.git("rev-parse", "--absolute-git-dir") or ".")
        if (gd / "rebase-merge").exists() or (gd / "rebase-apply").exists():  # stopped mid-conflict-fix: back to the branch
            self.sh(["git", "rebase", "--abort"])
        branch = self.git("symbolic-ref", "--short", "-q", "HEAD")
        new = [lo for lo in self.leftovers if lo["title"] not in self.filed]
        self.filed += [lo["title"] for lo in new]  # into the checkpoint before it is marked closed
        if outcome not in ("landed", "done") and branch and branch == getattr(self, "branch", None):
            if self.git("status", "--porcelain"):
                self.wip(outcome)  # the next run continues this branch
            self.mark_checkpoint_closed(why)
        stats = "cost=$%.2f; minutes=%d; %s" % (self.cost, mins, "; ".join("%s=%s" % kv for kv in self.stats.items()))
        self.log("node", "close: %s" % outcome, outcome=outcome, why=why)
        self.write_trace(outcome, why, sha)
        self.detail([stats] + ([why[:400]] if why else []) + (["question: " + question[:400]] if question else []))
        if outcome == "failed":
            self.warn("task failed: %s" % why.splitlines()[0][:200])
        if self.dry:
            self.log("note", "dry run: bead left as it was. %s" % stats)
            return
        if why.startswith("waiting:"):  # asked already: the bead stays as the ask left it, nothing is said twice
            self.log("note", why)
            return
        kind = ask_kind(why) if outcome not in ("landed", "done") else None
        if kind:
            self.raise_ask(kind, why, question)
        elif outcome in ("landed", "done") and self.ask_path().exists():
            try:
                a = json.loads(self.ask_path().read_text())
                if a.get("status") == "open":
                    a.update(status="closed", closed=time.time())
                    self.ask_path().write_text(json.dumps(a, indent=1))
            except (OSError, ValueError):
                pass
        look = [u for u in self.unchecked if u["kind"] == "other"]
        if look and outcome in ("landed", "done"):
            tl.bd("label", "add", self.bead, "needs-owner-check")
            self.comment("Look (engine): landed, but nobody checked: " + "; ".join(u["what"] for u in look))
        shots = self.keep_evidence()
        if shots:
            self.comment("Evidence (engine): %s" % ", ".join(str(p) for p in shots))
        for lo in new:
            tl.bd("create", lo["title"], "--type", "task", "--description", lo["why"],
                  "--deps", "discovered-from:" + self.bead)
        verified = ("; self-verified=" + ", ".join("%d %s" % (sum(x["verdict"] == k for x in self.verified), k)
                                                   for k in VERDICTS)) if self.verified else ""
        self.comment("Reflect (engine): outcome=%s; filed=%d; %s%s%s; trace=%s (tl trace %s)" % (
            outcome, len(new), stats, verified, ("; why=" + why) if why else "", self.log_path.stem, self.bead))
        summary = (getattr(self, "plan_summary", "") or "")[:300]
        if outcome == "landed":
            rc = tl.cmd_close(Args(id=self.bead, reason="merged %s to %s: %s; %s" % (
                sha[:12], self.cfg["base"].split("/")[-1], summary or "the task's stages passed", stats)))
        elif outcome == "done":
            rc = tl.cmd_close(Args(id=self.bead, reason="done with nothing to land: " + (summary or stats)))
        elif why.startswith("paused:"):  # the machine's problem (login, network, lanes), not the bead's: keep it open
            self.warn(why)
            r = tl.bd("update", self.bead, "--status", "open", "--append-notes", "Engine paused: " + why[:400])
            rc = getattr(r, "returncode", 0)
        else:
            text = why + (("\n\nQuestion: " + question) if question else "")
            rc = tl.cmd_block(Args(id=self.bead, why=text))
        if rc:  # a repo's bd rules can refuse (e.g. a minimum reason length): say so, never report a clean close
            self.warn("bd refused to %s %s (exit %s): close it by hand" % ("block" if outcome not in ("landed", "done")
                                                                          else "close", self.bead, rc))


def count_tests(diff, pattern):
    """Tests added and removed in a unified diff: lines matching the repo's test pattern (engine.test_pattern)."""
    rx = re.compile(pattern)
    added = removed = 0
    for ln in diff.splitlines():
        if ln.startswith(("+++", "---")):
            continue
        if ln.startswith("+") and rx.search(ln[1:]):
            added += 1
        elif ln.startswith("-") and rx.search(ln[1:]):
            removed += 1
    return added, removed


ENGINE_NOTES = ("Plan (engine)", "Review (engine", "Reflect (engine)", "Blocked:", "Ask (engine)", "Evidence (engine)")


VERIFY_GAPS = "verify: before land, "  # the ask for what the workers could not check; its answer may ask for work
CONFIRM_WORDS = {"right", "yes", "yep", "yeah", "y", "is", "ok", "okay", "k", "correct", "confirmed", "confirm", "lgtm", "land",
                 "it", "ship", "go", "ahead", "good", "fine", "looks", "all", "approved", "verified", "checked", "sure",
                 "true", "done", "please", "works", "thanks"}


# a yes followed by these asks for work: a turn ('but', 'though', 'missing') anywhere, or a work verb opening a clause
TURN_WORDS = {"but", "however", "except", "instead", "though", "although", "also", "still", "wrong", "missing", "should",
              "must", "need", "needs", "never", "don", "dont", "yet", "unless", "todo"}
WORK_VERBS = {"add", "fix", "change", "rename", "remove", "drop", "delete", "replace", "move", "update", "rewrite",
              "revert", "undo", "make", "use", "write", "run", "keep", "split", "do", "try", "test", "check"}
LEAD_WORDS = {"please", "now", "just", "and", "then", "so"}


def confirms(answer):
    """True when an answer says yes and asks for nothing: a few words, every one of them a yes ('right', 'ok, land
    it', 'LGTM'), or such a yes first and then only evidence or reasons ('Right. The log shows X.'). A first clause
    that is not a yes ('wrong: ...', 'not right'), a question mark, a turn word anywhere ('right, but ...') or a work
    verb opening a clause ('Right. Fix ...') means the owner may want work done. When in doubt it is work: a needless
    re-plan costs one planner call, a wrong land ships without what was asked."""
    words = re.findall(r"[a-z]+", answer.lower())
    if 0 < len(words) <= 6 and all(w in CONFIRM_WORDS for w in words):
        return True
    clauses = [re.findall(r"[a-z]+", c) for c in re.split(r"[.!;:,\n]", answer.lower())]
    clauses = [c for c in clauses if c]
    if not clauses or "?" in answer or not all(w in CONFIRM_WORDS for w in clauses[0]):
        return False
    if any(w in TURN_WORDS for w in words):
        return False
    for c in clauses[1:]:
        lead = [w for w in c if w not in LEAD_WORDS]
        if not c or c[0] in WORK_VERBS or (lead and lead[0] in WORK_VERBS):
            return False
    return True


def has_criteria(bead):
    """Acceptance criteria in the bead's field, or in a ## Acceptance Criteria section of its description."""
    if (bead.get("acceptance_criteria") or "").strip():
        return True
    m = re.search(r"^##\s*Acceptance Criteria\s*$(.*?)(?=^##\s|\Z)", bead.get("description") or "", re.M | re.S | re.I)
    return bool(m and m.group(1).strip())


def ask_kind(why):
    """The owner ask a block is, or None for the machine's own trouble (paused, waiting) and engine failures."""
    if why.startswith(("paused:", "waiting:", "failed:")):
        return None
    if why.startswith("owner decision needed"):
        return "decision"
    if why.startswith(("needs a human", "verify:")):
        return "verify"
    if why.startswith("ticket:"):
        return "ticket"
    return "stuck"


ENGINE_LABELS = ("needs-owner-check",)


def brief_digest(bead, comments, owner_only=False, ignore=()):
    """Markdown brief: title, the bead's text fields whole, related beads by title, people's comments whole, and one
    line on how the last engine run ended. owner_only leaves out what the engine writes itself (that line, its
    labels): the checkpoint compares that text, so an engine run never looks like the owner's edit."""
    out = ["# %s: %s" % (bead.get("id", ""), bead.get("title", ""))]
    labels = [x for x in bead.get("labels") or [] if not (owner_only and (x in ENGINE_LABELS or x in ignore))]
    meta = [bead.get("issue_type"), "P%s" % bead["priority"] if bead.get("priority") is not None else "",
            ", ".join(labels)]
    if any(meta):
        out.append(" · ".join(m for m in meta if m))
    for key, head in (("description", "Description"), ("acceptance_criteria", "Acceptance criteria"),
                      ("design", "Design"), ("notes", "Notes")):
        if (bead.get(key) or "").strip():
            out += ["", "## " + head, bead[key].strip()]
    rel = [d for d in (bead.get("dependencies") or []) if isinstance(d, dict)]
    if rel:
        out += ["", "## Related beads (titles only)"] + ["- %s %s [%s]" % (d.get("id"), d.get("title"),
                                                                           d.get("status") or "?") for d in rel]
    people = [c for c in comments if not (c.get("text") or "").startswith(ENGINE_NOTES)]
    if people:
        out += ["", "## Comments"] + ["- %s: %s" % (c.get("author") or "?", (c.get("text") or "").strip())
                                      for c in people]
    last = [c for c in comments if (c.get("text") or "").startswith(("Reflect (engine)", "Blocked:"))]
    if last and not owner_only:
        out += ["", "## Last engine run", last[-1]["text"].strip()[:400]]
    return "\n".join(out) + "\n"


class Heartbeat:
    def __init__(self, bead):
        self.bead, self.stop_ev = bead, threading.Event()
        self.th = threading.Thread(target=self.loop, daemon=True)

    def start(self):
        self.th.start()

    def loop(self):
        while not self.stop_ev.wait(60):
            tl.bd("heartbeat", self.bead)

    def stop(self):
        self.stop_ev.set()


GROUPS = ("static", "tests", "acceptance")


def split_top(cmd):
    """A shell command's top-level parts and the `&&` or `;` after each, or None when quoting or nesting makes it
    unclear (then nothing is reused)."""
    parts, cur, sep, depth, q, i = [], "", [], 0, "", 0
    while i < len(cmd):
        ch = cmd[i]
        if q:
            if ch == "\\" and q == '"' and i + 1 < len(cmd):
                cur += cmd[i:i + 2]
                i += 2
                continue
            if ch == q:
                q = ""
        elif ch in "'\"":
            q = ch
        elif ch == "`":
            return None
        elif ch in "({":
            depth += 1
        elif ch in ")}":
            depth -= 1
        elif depth == 0 and (cmd.startswith("&&", i) or ch == ";"):
            parts.append(cur)
            sep.append("&&" if ch == "&" else ";")
            cur, i = "", i + (2 if ch == "&" else 1)
            continue
        cur += ch
        i += 1
    if q or depth:
        return None
    parts.append(cur)
    return list(zip(parts, sep + [""]))


def reuse_passed(cmd, passed):
    """cmd with each top-level part that is a repo check already passed this round replaced by `true`; an earlier
    part that deletes files (rm) may remove that check's output, so from there on nothing is replaced."""
    split = split_top(cmd)
    if not split or not passed:
        return cmd, []
    out, used, deleting = [], [], False
    for part, sep in split:
        p = " ".join(part.split())
        deleting = deleting or re.match(r"(?:\S*/)?rm\b", p) is not None
        if p in passed and not deleting:
            used.append(p)
            out.append(" true " + sep)
        else:
            out.append(part + sep)
    return "".join(out).strip(), used
NOTABLE = re.compile(r"(?i)\b(skip|skipped|steps run|passed|failed|warnings?|errors?)\b")


def compact(checks):
    """Check results for a prompt: command, exit code, and the lines that say what ran (a passing gate that skipped
    its Unity steps must not look like one that ran them), or the tail of a failure."""
    out = []
    for c in checks:
        if c.get("exit") is None:
            out.append("- `%s` skipped: %s" % (c["cmd"], c.get("why") or ""))
            continue
        lines = [ln.strip() for ln in c["tail"].splitlines() if ln.strip()]
        if c["exit"]:
            body = " | ".join(lines)[-400:]
        else:
            body = " | ".join(([ln for ln in lines[:-1] if NOTABLE.search(ln)][-3:] + lines[-1:]))[-300:]
        out.append("- `%s` exit %d%s" % (c["cmd"], c["exit"], (": " + body) if body else ""))
    return "\n".join(out) or "- (no checks)"


def say(line):
    """Print whatever the console can show (a Windows cp1252 console cannot print ⚠): never crash on output."""
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
    return ""


# ---- prompts (one copy each; the per-node instructions of the design) -----------------------------------------------

COMMON = ("You are one step of an unattended task engine. Nobody is watching; do not ask for confirmation. "
          "Work only in {wt}. Never commit, push, branch, or change git state. Never add suppressions or weaken, skip "
          "or delete tests. Answer with the structured result only.")

PLAN_PROMPT = COMMON + """

The task (the bead, with its acceptance criteria and comments: review findings, the owner's answers):
<task>
{brief}
</task>
Read the code it names. Then plan.

- Split the work into stages, each one coherent piece that its checks can judge (often one stage is enough).
- For each stage: goal, the files it changes, the exact commands that prove it (tests, linters), and hard=true only
  when it is risky or subtle. Every check is a shell command that exits 0 when it proves the goal and non-zero when it
  does not: the engine reads only the exit code. "Expect empty" is `test -z "$(...)"` or `! grep ...`, never a bare
  grep; a count is `test "$(... | wc -l)" -eq 25`, never a comment saying what to expect. A check runs under
  `bash -e -o pipefail`: a red command before a `;` or inside a pipe fails it; `cmd || true` for one whose exit does
  not matter. Grep a command's output from a file (`cmd > f 2>&1 && grep -q x f`), not a pipe: `grep -q` ends the
  pipe early and the command dies of SIGPIPE (exit 141).
- The engine sets every time limit and runs checks one at a time; never write timeouts, "run alone" or similar notes
  into a check.
- cases: the acceptance cases. At least one per acceptance criterion of the task, each with the criterion it proves
  (quote it) and a check. They run on the last stage and again after any fix at land. A case about what users see uses
  the host's tools and a fact the tool reports (a scenario script, a screenshot saved under the evidence folder, a count
  the editor prints), never only "a screenshot exists".
- Name the risks ahead of time: what could break something users or other code rely on (a saved format, a public
  member, shared files), each with the check that proves it safe. None is fine.
- A check proves the code and the tree only: it never reads the tracker (no `bd`, nothing under `.beads/`) nor
  anything outside the worktree; the writers cannot run bd, so such a check fails whatever they do. Follow-up work the
  task wants filed (a new bead, a later task) goes in leftovers, each a title and why: the engine files them itself,
  and no check or case asks for them.
- question: empty, unless the task cannot be done without a decision only the owner can make (product direction,
  scope, a hard-to-reverse architecture choice). Decide technical choices yourself. If you ask, write the question
  so it can be answered from a phone: what you found, the decision, 2-3 options with costs, your recommendation."""

DECIDED_RULE = ("A change that contradicts an accepted requirement (in the task, its acceptance criteria, or a "
                "requirement it cites) is never the owner's question: the fix is to meet the requirement. decided: the "
                "accepted requirement, quoted, that already answers your question (the engine then sends the stage "
                "back to meet it instead of asking the owner); empty when you have no question, when two accepted "
                "requirements conflict, or when no requirement decides it yet (those are the owner's).")
DECIDED_TEXT = ("\nYou asked: %s\nAn accepted requirement already decides it: %s\nMeet that requirement: change the "
                "work, never the requirement.\n")

WRITE_PROMPT = """You are the writer for one stage of a task, in an unattended engine. Nobody is watching.

<task>
{brief}
</task>
<plan>
{plan}
</plan>
Your stage: {n}: {goal}{rules}
Files: {files}
The stage's checks (the engine runs all of them after you):
{checks}
{where}
Never run the gate{gate} or the issue tracker (bd): the engine runs the gate, and its run is the one that counts.
Repo instructions that say a change is done only when the full gate passes are for people working by hand; here the
engine does that part.
{feedback}
bad_checks: a stage check that fails for a reason no code change can fix (wrong arguments, a guard that rejects the
uncommitted work this stage must leave, a pattern that matches harmless text), each with why; else empty. The engine
then asks for a new plan instead of retrying.
A check that times out or fails only where you run it is not yours to retry; note it once and move on.
Proof the engine cannot rerun (a test seen failing after a planted fault, then passing once restored; a manual
measurement): save the exact commands and their output as files in {evidence}/ and name those files in the summary.
Only that proof goes there, never your own runs of the checks.
Rules: no suppressions; do not weaken, skip or delete tests; stay inside the
stage. question: empty unless only the owner can decide something about the task itself (then explain it for a
phone); never a question about tools or access.""" + "\n" + DECIDED_RULE

REVIEW_PROMPT = """You review one stage of a task, from another model family than the writer. Do not edit files.
<task>
{brief}
</task>
<plan>
{plan}
</plan>
Stage {n}: {goal}
The work: `git diff {base}` and new files (the task's work since main, committed or not).
The engine ran the checks outside any sandbox, one at a time, and they all pass; these results are facts:
{checks}
The engine runs the gate{gate} once, at land, on the tree rebased onto the latest base, before anything merges; a red
gate (coverage included) goes to a fix round. The gate, the checks above and what they prove are never an unchecked item.
The writer says: {summary}
Proof the engine cannot rerun (a test seen failing after a planted fault) is in {evidence}/: a requirement shown
there is met. The engine counted tests in the task's diff: {added} added, {removed} removed.
Return:
- findings: bugs, broken contracts, risky changes (a public member, a test weakened or removed, a suppression, a file
  outside what the stage names), each with file, line, severity and the fix. high and medium send the stage back; low
  is noted only. No style nits.
- unmet: what in {scope} the work does not do yet, each saying what is missing. A requirement shown met by a check or
  by the evidence is met; never list a remark that something is fine.
- question: empty, unless only the owner can decide something about the task itself (then explain it for a phone:
  what you found, the options, your recommendation).
- leftovers: real follow-up work you noticed outside this task, else empty.""" + "\n" + DECIDED_RULE

VERIFY_PROMPT = """Before a task lands, you check what its workers could not check themselves. Do not edit files.
<task>
{brief}
</task>
The work (files the task changed, with line counts):
{work}
Proof the workers saved (command output, logs, pictures) is in {evidence}/.
{where}
Nobody has checked these items yet:
{items}
Settle each one yourself where you can: read the code, its call sites, sibling files and the saved proof, and run
read-only commands (search, list, compare, count). Answer one entry per item, n its number:
- settled: you proved it right; evidence quotes exactly what proves it (the file and lines, or the command and its
  output).
- wrong: you found a real defect; why says what is wrong and where, so a writer can fix it.
- open: only a person can judge it (taste, a device or a screen you cannot reach, the owner's call); why says what they
  must look at.
When in doubt, it is open: never settle an item you did not prove."""


# ---- entry ----------------------------------------------------------------------------------------------------------

def load_cfg(repo):
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        user = json.loads((Path(repo) / ".task-loop.json").read_text(encoding="utf-8")).get("engine") or {}
    except (OSError, ValueError):
        user = {}
    cfg.update(user)
    return cfg


def reclaim(bead_id, repo):
    """(ok, why): run-task takes back what the engine itself left, never what a person holds. A claim by a tl- actor
    whose lease ran out is released (a restarted Claude session gets a new actor name). A bead the engine blocked is
    reopened for a plain retry, or when a comment after the block answers the open ask; it stays blocked when a person
    commented after the block with no ask open (they may have parked it), while an ask waits unanswered, or while
    another bead blocks it."""
    b = tl.show(bead_id) or {}
    who, me = b.get("assignee") or "", tl.actor()
    release = False
    if who and who != me:
        if not who.startswith("tl-"):
            return False, "claimed by %s" % who
        if who in tl.live_actors(repo) or (b.get("lease_expires_at") or "") >= time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()):
            logs = sorted((tl.config_dir() / "engine").glob("%s-*.jsonl" % bead_id))
            return False, "another run of %s is still running as %s (a live claim)%s" % (
                bead_id, who, "; its engine log: %s" % logs[-1] if logs else "")
        release = True
    reopen = False
    if b.get("status") == "blocked":
        held = [d.get("id") for d in b.get("dependencies") or [] if isinstance(d, dict)
                and d.get("dependency_type") == "blocks" and d.get("status") != "closed"]
        if held:
            return False, "blocked by %s" % ", ".join(held)
        cs = tl.comments(bead_id)
        blocks = [c for c in cs if (c.get("text") or "").startswith("Blocked:")]
        if not blocks:
            return False, "blocked by a person, not by the engine"
        after = [c for c in cs if (c.get("created_at") or "") > (blocks[-1].get("created_at") or "")
                 and not (c.get("text") or "").startswith(ENGINE_NOTES)]
        try:
            ask = json.loads((tl.config_dir() / "asks" / ("%s.json" % bead_id)).read_text())
        except (OSError, ValueError):
            ask = {}
        asking = ask.get("status") == "open"
        if asking and not after:
            return False, "waiting for the answer to ask %s (%s)" % (ask.get("id"), ask.get("kind"))
        if after and not asking:
            return False, "%s commented after the engine blocked it; read that first" % (after[-1].get("author") or "someone")
        reopen = True
    if reopen:
        tl.bd("update", bead_id, "--status", "open", "--assignee", "")
    elif release:
        tl.bd("update", bead_id, "--assignee", "")
    return True, ("reopened" if reopen else "released %s" % who if release else "")


def append_output(stream):
    """Write a stream that is a file at the end of that file, wherever another writer left it: a second
    `run-task ... > log` on the same log truncates it, and a live run writing on at its old offset leaves a hole of NUL
    bytes (lifesim-gfr.31.1). A terminal, a pipe or a stream with no descriptor is left as it is."""
    try:
        import fcntl
    except ImportError:  # Windows: no file status flags
        return
    try:
        fd = stream.fileno()
        regular = stat.S_ISREG(os.fstat(fd).st_mode)
    except (OSError, ValueError):  # no descriptor (a captured stream) or a closed one: nothing to keep in order
        return
    if regular:
        fcntl.fcntl(fd, fcntl.F_SETFL, fcntl.fcntl(fd, fcntl.F_GETFL) | os.O_APPEND)


def main(a):
    for f in (sys.stdout, sys.stderr):
        append_output(f)
    if hasattr(signal, "SIGTERM"):  # a stop (kill switch, coordinator) still runs the close step
        signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(Blocked("failed: stopped (SIGTERM)")))
    if not os.environ.get("TASK_LOOP_SESSION") and not tl.session_id():
        os.environ["TASK_LOOP_SESSION"] = "engine-" + uuid.uuid4().hex[:12]
    repo = tl.repo_root()
    cfg = load_cfg(repo)
    wt = a.worktree
    if not wt:
        r = subprocess.run([sys.executable, str(Path(__file__).with_name("tl.py")), "worktree", "start"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        wt = r.stdout.strip().splitlines()[-1] if r.returncode == 0 and r.stdout.strip() else ""
        if not wt:
            sys.exit("tl: no worktree: " + r.stderr)
    wt = str(Path(wt).resolve())
    if (Path(wt) / ".git").is_dir():  # the main checkout holds the bead database and the config: never a worker's cwd
        print("tl: %s is the main checkout; run a task in a slot or a worktree (tl slot / tl worktree start)" % wt,
              file=sys.stderr)
        return 1
    if not a.dry_run:
        ok, why = reclaim(a.id, repo)
        if not ok:
            print("TAKEN: %s" % why)
            return 1
        if why:
            say("%s: %s" % (a.id, why))
    if not a.dry_run and tl.cmd_claim(Args(id=a.id, worktree=wt, slot=a.slot)) != 0:
        return 1  # bd lets this session re-claim its own bead (a reopened one); another session's claim stops here
    cfg["fresh"] = bool(getattr(a, "fresh", False))
    eng = Engine(a.id, wt, cfg, dry_run=a.dry_run, verbose=not getattr(a, "quiet", False))
    say("engine log: %s" % eng.log_path)
    return eng.run()
