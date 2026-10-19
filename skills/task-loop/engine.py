#!/usr/bin/env python3
"""The task engine: one bead through reset → plan → (write → checks → review)* per stage → gate → land → close.

    tl.py run-task ID [--worktree DIR] [--dry-run]

Code routes; AI nodes only produce structured outputs (validated against a schema). The close step always runs.
A coordinator session may start it and watch it (attended mode); nothing here needs one. Design:
docs/design/coordinator-less.md. Python 3.8+, standard library only.
"""

import fnmatch
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
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
    "max_replans": 1,
    "node_timeout_min": 45,
    "delegate": "",                   # path to delegate's route.py; "" = the newest installed iorlas-delegate
    "lane_wait_min": 60,              # how long a step waits for a lane that is out before the task is blocked
    "checks": [],                     # repo checks: [{id, cmd, group: static|tests|acceptance, when: [globs], retry}]
    "no_sandbox": False,              # workers run outside delegate's sandbox (delegate --no-sandbox); a bead label
                                      # no-sandbox / sandbox overrides it for one bead
    "worker_rules": "",               # repo file the writer reads first: what its sandbox can and cannot run
    "brief_kb": 5,
    "test_pattern": r"^\s*(def test_|async def test_|\[(Test|Fact|Theory|TestMethod|TestCase)\b|#\[test\]|(it|test)\(|func Test)",                    # a brief bigger than this gets a ⚠ (never cut: the bead may be too big)
}

# ---- output contracts -----------------------------------------------------------------------------------------------

S_STR = {"type": "string"}
S_STRS = {"type": "array", "items": S_STR}
LEFTOVERS = {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                        "properties": {"title": S_STR, "why": S_STR}, "required": ["title", "why"]}}
SCHEMAS = {
    "plan": {"type": "object", "additionalProperties": False, "required": ["summary", "stages", "risks", "question"],
             "properties": {
                 "summary": S_STR,
                 "stages": {"type": "array", "items": {
                     "type": "object", "additionalProperties": False, "required": ["goal", "files", "checks", "hard"],
                     "properties": {"goal": S_STR, "files": S_STRS, "checks": S_STRS, "hard": {"type": "boolean"}}}},
                 "risks": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                      "required": ["what", "check"],
                                                      "properties": {"what": S_STR, "check": S_STR}}},
                 "question": S_STR}},
    "write": {"type": "object", "additionalProperties": False, "required": ["summary", "checks_run", "question"],
              "properties": {"summary": S_STR, "question": S_STR,
                             "checks_run": {"type": "array", "items": {
                                 "type": "object", "additionalProperties": False, "required": ["cmd", "exit"],
                                 "properties": {"cmd": S_STR, "exit": {"type": "integer"}}}}}},
    "review": {"type": "object", "additionalProperties": False, "required": ["findings", "unmet", "question", "leftovers"],
               "properties": {"findings": {"type": "array", "items": {
                   "type": "object", "additionalProperties": False, "required": ["file", "line", "severity", "fix"],
                   "properties": {"file": S_STR, "line": {"type": "integer"},
                                  "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                                  "fix": S_STR}}},
                   "unmet": S_STRS, "question": S_STR, "leftovers": LEFTOVERS}},
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


ROLES = {"plan": "planner", "write": "worker", "review": "reviewer"}


def find_route(path=""):
    """delegate's route.py: `path` when given (engine.delegate), else the newest installed delegate with worker-run v1."""
    if path:
        return path if os.path.exists(path) else None
    found = []
    for p in (Path.home() / ".claude" / "plugins" / "cache").glob("*/iorlas-delegate/*/skills/delegate/route.py"):
        ver = tuple(int(x) for x in re.findall(r"\d+", p.parents[2].name)[:3])
        if ver >= (0, 14):  # worker-run v1 starts at delegate 0.14.0
            found.append((ver, str(p)))
    return max(found)[1] if found else None


def delegate_version(route):
    """(major, minor) of the installed delegate the route.py belongs to; None for a checkout (counts as newest)."""
    m = re.search(r"iorlas-delegate[/\\](\d+)\.(\d+)", route)
    return (int(m.group(1)), int(m.group(2))) if m else None


def unsandboxed(route, node, wanted):
    """Whether this step runs with delegate's --no-sandbox: the write step from delegate 0.20.0, every step (plan and
    review get Bash and the network) from 0.21.0. Returns (flag, the reason it is off although wanted, or "")."""
    if not wanted:
        return False, ""
    v = delegate_version(route)
    need = (0, 20) if node == "write" else (0, 21)
    if v and v < need:
        return False, "--no-sandbox for %s needs delegate %d.%d (installed %d.%d): it runs sandboxed" % (
            node, need[0], need[1], v[0], v[1])
    return True, ""


def author_flag(route):
    """delegate renamed --writer to --authored-by in 0.17.0."""
    v = delegate_version(route)
    return "--writer" if v and v < (0, 17) else "--authored-by"


def headless_args(route, timeout):
    """How an engine says "no Claude session behind me": delegate 0.19.0 --unattended, 0.18.x --headless (both with no
    --timeout: the engine's own node limit still kills the process, run_proc), before 0.18 --timeout and the env."""
    v = delegate_version(route)
    if v and v < (0, 18):
        return ["--timeout", str(int(timeout))]
    if v and v < (0, 19):
        return ["--headless"]
    return ["--unattended"]


def call_delegate(route, role, prompt, schema, cwd, resume, timeout, log_path, writer=None, parent="", task="",
                  title="", no_sandbox=False):
    """One AI step through `route.py run` (worker-run v1). Returns (Result, the answer object or None)."""
    with tempfile.TemporaryDirectory() as d:
        bf, sf = os.path.join(d, "brief.md"), os.path.join(d, "schema.json")
        Path(bf).write_text(prompt, encoding="utf-8")
        Path(sf).write_text(json.dumps(schema))
        cmd = [sys.executable, route, "run", role, "--brief", bf, "--cwd", cwd, "--schema", sf,
               *headless_args(route, timeout), "--parent", parent, "--task", task, "--title", title[:120]]
        if resume:
            cmd += ["--resume", resume]
        if writer:
            cmd += [author_flag(route), writer]
        if no_sandbox:
            cmd.append("--no-sandbox")
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

LOGGED_OUT = re.compile(r"(?i)failed to authenticate|oauth session expired|not logged in|please run .*login|"
                        r"invalid api key|authentication_error")
NETWORK_DOWN = re.compile(r"(?i)ENOTFOUND|EAI_AGAIN|ECONNRESET|ECONNREFUSED|ETIMEDOUT|can't reach the api server|"
                          r"network is unreachable|could not resolve host|dns error|connection reset")


class Blocked(Exception):
    def __init__(self, why, question=""):
        super().__init__(why)
        self.why, self.question = why, question


class Engine:
    def __init__(self, bead, wt, cfg, dry_run=False, verbose=True):
        self.bead, self.wt, self.cfg, self.dry, self.verbose = bead, wt, cfg, dry_run, verbose
        self.t0 = time.time()
        self.cost = 0.0
        self.stats = {"writes": 0, "rounds": 0, "reviews": 0, "replans": 0, "nodes": 0, "tests_added": 0, "tests_removed": 0}
        self.session = tl.session_id()
        self.leftovers = []
        self.stuck_why = ""
        self.no_sandbox = bool(cfg.get("no_sandbox"))
        self.sandbox_warned = set()
        self.budget_warned = set()
        self.writer = {}  # backend -> thread/session id, so later rounds of a task resume the same writer
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

    def trace_call(self, node, role, attempt, r, j, no_sandbox=False):
        """One AI call into the run's trace: which worker session did what, and where its transcript is."""
        j = j or {}
        rec = {"node": node, "role": role, "attempt": attempt, "status": j.get("status") or r.error or "none",
               "ref": j.get("ref") or r.ref or "", "run_id": j.get("run_id") or "", "transcript": j.get("transcript") or "",
               "family": j.get("family") or "", "lane": j.get("lane") or "", "model": j.get("model") or "",
               "effort": j.get("effort") or "", "secs": round(r.secs or 0), "cost": r.cost or 0.0, "t": time.time(),
               "no_sandbox": no_sandbox}
        self.sessions.append(rec)
        self.log("session", "%s: %s %s" % (node, rec["family"] or "?", rec["ref"] or "(no session)"), **rec)

    def write_trace(self, outcome, why, sha):
        """One line per engine run in traces.jsonl, never pruned: bead, repo, branch, every session, the outcome."""
        rec = {"v": 1, "run": self.log_path.stem, "bead": self.bead,
               "repo": self.git("remote", "get-url", "origin") or str(self.wt), "worktree": str(self.wt),
               "branch": self.git("symbolic-ref", "--short", "-q", "HEAD"), "coordinator_session": self.session,
               "started": self.t0, "ended": time.time(), "outcome": outcome, "why": (why or "")[:500], "sha": sha or "",
               "cost": self.cost, "stats": self.stats, "no_sandbox": self.no_sandbox, "delegate": self.route or "", "log": str(self.log_path),
               "stderr": str(self.err_path), "sessions": self.sessions}
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
        writer = writer_family if node == "review" else None
        resume = self.writer.get("delegate") if resume_key else None
        free, why = unsandboxed(self.route, node, self.no_sandbox)
        if why and why not in self.sandbox_warned:
            self.sandbox_warned.add(why)
            self.warn(why)
        self.log("node", "%s: %s" % (node, title), node=node, backend="delegate", role=role, resume=bool(resume))
        timeout = float(self.cfg["node_timeout_min"]) * 60
        waited, attempt_prompt, attempt, errs, transient = 0.0, prompt, 1, ["not run"], 0
        while attempt <= 2:
            r, j = call_delegate(self.route, role, attempt_prompt, SCHEMAS[node], self.wt, resume, timeout,
                                 self.err_path, writer, self.session, self.bead, "%s · %s: %s" % (self.bead, node, title),
                                 no_sandbox=free)
            if j is not None and j.get("v") != 1:
                raise Blocked("failed: delegate answered worker-run v%s, this engine speaks v1 (update task-loop)"
                              % j.get("v"))
            st = (j or {}).get("status")
            self.trace_call(node, role, attempt, r, j, free)
            if st in ("lane_out", "stop"):
                wait = max(60.0, min(600.0, float(j.get("retry_after") or 0) - time.time()))
                if waited + wait > float(self.cfg["lane_wait_min"]) * 60:
                    raise Blocked("paused: no lane for %s (%s)" % (node, j.get("say") or st))
                self.warn("%s waits %d min for a lane: %s" % (node, wait // 60, j.get("say") or st))
                time.sleep(wait)
                waited += wait
                continue
            said = "%s %s" % ((j or {}).get("say") or "", r.error or "")
            if LOGGED_OUT.search(said):  # retrying cannot help: the owner must log in (Setup), the bead stays open
                login = "codex login" if "codex" in said.lower() or (j or {}).get("family") == "openai" else "claude auth login"
                raise Blocked("paused: a worker CLI is logged out; run `%s` on this machine, then rerun. (%s)"
                              % (login, said.strip()[:200]))
            if NETWORK_DOWN.search(said):  # the machine lost the network (asleep, Wi-Fi): wait like for a lane
                if waited + 60 > float(self.cfg["lane_wait_min"]) * 60:
                    raise Blocked("paused: no network for %s for %s min (%s)" % (node, self.cfg["lane_wait_min"],
                                                                                 said.strip()[:200]))
                self.warn("%s: network down, retrying in 1 min: %s" % (node, said.strip()[:160]))
                time.sleep(60)
                waited += 60
                continue
            if st == "error" and transient < 2:  # delegate 0.19: a state lock held >10 s answers error; try again
                transient += 1
                self.warn("%s: delegate error, retrying in 30 s: %s" % (node, (j or {}).get("say") or r.error))
                time.sleep(30)
                continue
            if st == "agent":
                raise Blocked("failed: delegate answered `agent`; it does not see this engine as headless")
            self.cost += r.cost
            if j and j.get("git_violation"):
                self.warn("%s changed git: %s" % (node, "; ".join(j["git_violation"])))
            if resume_key and r.ref and st == "done":
                self.writer["delegate"] = resume = r.ref
            errs = validate(r.data, SCHEMAS[node]) if r.data is not None else [
                "no structured output" + (": " + r.error if r.error else "")]
            if not errs:
                break
            self.log("note", "%s output invalid (try %d): %s" % (node, attempt, "; ".join(errs[:4])))
            fix = ("Your previous answer did not match the required output schema: %s. Answer again with only the "
                   "structured result." % "; ".join(errs[:6]))
            if r.ref and st == "done":
                resume, attempt_prompt = r.ref, fix
            else:
                resume, attempt_prompt = None, prompt + "\n\n" + fix
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
        if node == "plan" and len(d["stages"]) > 4:
            self.warn("the plan has %d stages: the bead may be too big for one task" % len(d["stages"]))
        if node == "review" and any(f["severity"] == "high" for f in d["findings"]):
            self.warn("the reviewer found a high-severity problem")

    # -- script helpers
    def sh(self, cmd, timeout=3600, check=False, save=None, env=None):
        """A command: a string goes through the shell (profile commands), a list runs as is (no quoting rules)."""
        self.log("cmd", cmd if isinstance(cmd, str) else " ".join(cmd))
        # Its own process group, so a timeout stops the whole tree (dotnet build nodes, Unity) and not just the shell;
        # the worker env, so a check never inherits this launcher's Claude session.
        p = subprocess.Popen(cmd, shell=isinstance(cmd, str), cwd=self.wt, env=dict(child_env(), **(env or {})),
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
        if self.git("status", "--porcelain"):
            if self.git("symbolic-ref", "--short", "-q", "HEAD") != branch:
                raise Blocked("failed: worktree %s has uncommitted work of another branch" % self.wt)
            self.wip("left from an earlier run")
        if exists:
            self.sh(["git", "checkout", "-q", branch], check=True)
        else:
            self.sh(["git", "checkout", "-q", "-B", branch, self.cfg["base"]], check=True)
        for old in self.task_dir.iterdir():  # earlier runs' files are no facts; only the writer's evidence carries over
            if old.name != "evidence":
                shutil.rmtree(old) if old.is_dir() else old.unlink()
        self.export_brief()
        return branch

    def export_brief(self):
        """The task as workers read it: the bead's own text and the people's comments, never the engine's own records
        (plans, reviews, reflects pile up on every rerun: 40 of lifesim-vbo's 45 KB brief)."""
        text = brief_digest(tl.show(self.bead) or {"id": self.bead}, tl.comments(self.bead))
        (self.run_dir / "brief.md").write_text(text, encoding="utf-8")
        kb = len(text.encode("utf-8")) / 1024
        if kb > float(self.cfg["brief_kb"]):
            self.warn("the brief is %.0f KB (over %s KB): the bead may be too big for one task" % (kb, self.cfg["brief_kb"]))

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
            labels = bead.get("labels") or []
            if "no-sandbox" in labels or "sandbox" in labels:
                self.no_sandbox = "no-sandbox" in labels
                self.log("note", "bead label: workers run %s" % ("outside the sandbox" if self.no_sandbox else "sandboxed"))
            hb.start()
            if not self.route:
                raise Blocked("failed: the engine needs the iorlas-delegate plugin (0.14.0 or later): "
                              "claude plugin install iorlas-delegate@iorlas-marketplace")
            self.log("note", "workers: delegate %s (worker-run v1)" % self.route)
            self.reset(bead)
            plan = self.plan()
            replans = 0
            i = 0
            while i < len(plan["stages"]):
                d = self.stage(plan, i)
                if d == "replan":
                    replans += 1
                    self.stats["replans"] = replans
                    if replans > int(self.cfg["max_replans"]):
                        raise Blocked("stage %d stuck after %s rounds and %d re-plan(s): it needs the owner's hint, "
                                      "a split, or more budget. What failed: %s" % (
                                          i + 1, self.cfg["max_rounds"], replans - 1, self.stuck_why[:600]))
                    plan = self.plan(again=True)
                    i = 0
                    continue
                i += 1
            sha = self.finish(bead)
            outcome = "landed" if sha else "done"
        except Blocked as b:
            outcome = "failed" if b.why.startswith("failed:") else "blocked"
            why, question = b.why, b.question
        except Exception as e:  # the close-out must run whatever broke
            outcome, why = "failed", "failed: engine error %s: %s" % (type(e).__name__, e)
        finally:
            hb.stop()
            self.close(outcome, why, sha, question)
        return 0 if outcome in ("landed", "done") else 2

    def plan(self, again=False):
        extra = ("\n\nThe previous plan did not work; what failed is in %s. Plan again." %
                 (self.run_dir / "replan.md")) if again else ""
        data, _ = self.ai("plan", "re-plan" if again else "plan", PLAN_PROMPT.format(brief=self.run_dir / "brief.md",
                                                                                     wt=self.wt) + extra +
                          ("\n\n" + self.where("plan") if self.where("plan") else ""))
        self.plan_summary = data["summary"]
        if data["question"].strip():
            raise Blocked("owner decision needed", data["question"])
        if not data["stages"]:
            raise Blocked("failed: the plan has no stages")
        lines = ["Plan (engine): " + data["summary"]]
        lines += ["%d. %s%s [files: %s] [checks: %s]" % (n + 1, s["goal"], " (hard)" if s["hard"] else "",
                                                          ", ".join(s["files"]), "; ".join(s["checks"]))
                  for n, s in enumerate(data["stages"])]
        lines += ["Risk: %s → %s" % (r["what"], r["check"]) for r in data["risks"]]
        self.comment("\n".join(lines))
        (self.run_dir / "plan.json").write_text(json.dumps(data, indent=1))
        self.export_brief()
        return data

    def stage(self, plan, i):
        """Write → checks → review until the review is clean. A red check goes straight back to the writer (it never
        reaches the reviewer); max_check_tries red in a row, or a review that sends it back, use up a round; when the
        rounds are used up the stage asks for a re-plan. Accept is a rule: checks green and nothing blocking in the
        review (high/medium findings, unmet requirements). The writer's or the reviewer's question is the owner's."""
        st = plan["stages"][i]
        last = i == len(plan["stages"]) - 1
        name = "stage %d/%d" % (i + 1, len(plan["stages"]))
        feedback, rounds, red, n = "", 0, 0, 0
        while True:
            n += 1
            self.stats["writes"] += 1
            if n >= 2:
                self.warn("%s: write %d (round %d)" % (name, n, rounds + 1))
            w, wfam = self.ai("write", "%s write %d" % (name, n), WRITE_PROMPT.format(
                brief=self.run_dir / "brief.md", plan=self.run_dir / "plan.json", n=i + 1, goal=st["goal"],
                files=", ".join(st["files"]), checks="\n".join("- " + c for c in st["checks"]) or "- (none named)",
                feedback=feedback, evidence=self.evidence_dir, where=self.where("write"), gate=(" (`%s`)" % self.cfg["gate"]) if self.cfg["gate"] else "",
                rules=("\nRead %s first: this repo's rules for work in your sandbox (what runs there, what does not)."
                       % (Path(self.wt) / self.cfg["worker_rules"])) if self.cfg["worker_rules"] else ""),
                resume_key="writer")
            if w["question"].strip():
                raise Blocked("owner decision needed", w["question"])
            checks = self.run_checks(st, name)
            (self.run_dir / "engine-checks.json").write_text(json.dumps(checks, indent=1))
            self.stats["tests_added"], self.stats["tests_removed"] = count_tests(self.task_diff(), self.cfg["test_pattern"])
            if self.stats["tests_removed"]:
                self.warn("the task's diff removes %d tests" % self.stats["tests_removed"])
            failed = [c for c in checks if c["exit"] not in (0, None)]
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
            review, _ = self.ai("review", name, REVIEW_PROMPT.format(
                brief=self.run_dir / "brief.md", plan=self.run_dir / "plan.json", n=i + 1, goal=st["goal"],
                base=self.base_sha(), checks=compact(checks), summary=w["summary"], evidence=self.evidence_dir,
                added=self.stats["tests_added"], removed=self.stats["tests_removed"],
                scope=("the stage goal and every requirement and acceptance criterion of the task" if last else
                       "the stage goal (later stages cover the rest of the task)")) +
                ("\n" + self.where("review") if self.where("review") else ""), writer_family=wfam)
            same = self.last_flag == "same_family"
            if same:
                self.warn("%s: the review is from the writer's own model family (no other lane was free)" % name)
            if review["findings"] or review["unmet"] or same:
                self.comment("Review (engine, %s%s): " % (name, ", same family as the writer" if same else "") + "; ".join(
                    ["%s:%s [%s] %s" % (f["file"], f["line"], f["severity"], f["fix"]) for f in review["findings"]] +
                    ["unmet: " + u for u in review["unmet"]]) or "no findings")
            self.leftovers += review["leftovers"]
            if review["question"].strip():
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
        """What the step may run, by whether it is sandboxed."""
        free, _ = unsandboxed(self.route, node, self.no_sandbox)
        if node == "write":
            return ("You run outside a sandbox, on this machine: run the tests and tools you need (unit tests, the editor's "
                    "batch tests, builds) to see your change work before you say it is done." if free else
                    "Run only the quick checks (seconds, no build of the whole project, no editor) to see your change "
                    "works; anything that needs the host is run by the engine after you.")
        return ("You run outside a sandbox and may run commands to check facts (open cited links, run a linter or a "
                "test); never edit, create or delete files." if free else "")

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
        task changed a matching path; `retry` reruns a red one (known flaky). A check already run on the same tree and
        base is not run again. The gate is not here: it runs once, on the rebased tree, at land."""
        self.log("node", "checks: %s" % name)
        items = [{"id": c.get("id") or c["cmd"], "cmd": c["cmd"], "group": c.get("group") or "tests",
                  "when": c.get("when") or [], "retry": int(c.get("retry") or 0)} for c in self.cfg["checks"]]
        items += [{"id": c, "cmd": c, "group": "acceptance", "when": [], "retry": 0} for c in st["checks"]]
        items.sort(key=lambda c: GROUPS.index(c["group"]) if c["group"] in GROUPS else 1)
        cache_path = tl.config_dir() / "check-cache" / ("%s.json" % self.bead)
        try:
            cache = json.loads(cache_path.read_text())
        except (OSError, ValueError):
            cache = {}
        key = "%s %s" % (self.tree_hash(), self.git("rev-parse", self.cfg["base"]))
        logs = self.run_dir / "checks"
        logs.mkdir(exist_ok=True)
        out, red, changed = [], None, None
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
            hit = cache.get(key, {}).get(c["cmd"])
            if hit:
                res = dict(base, **hit)
                res.update(cached=True, status=hit.get("status") or ("ran" if hit["exit"] == 0 else "failed"))
            else:
                t, tries = time.time(), 0
                while True:
                    tries += 1
                    rc, tail = self.sh(c["cmd"], timeout=float(self.cfg["node_timeout_min"]) * 60,
                                       save=logs / ("%02d-%s.log" % (n, re.sub(r"[^\w.-]+", "_", c["id"])[:40])))
                    if rc == 0 or tries > c["retry"]:
                        break
                    self.warn("`%s` failed (exit %d), retrying: it is marked flaky" % (c["id"], rc))
                res = dict(base, exit=rc, status="ran" if rc == 0 else "failed", tries=tries, tail=tail[-1500:],
                           secs=round(time.time() - t))
                if rc == 0:  # only a pass is a fact about the tree; a failure can come from outside git (stale
                    cache.setdefault(key, {})[c["cmd"]] = res  # build output, a held editor, a flake) and must rerun
            out.append(res)
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
        for attempt in range(1, 6):
            self.log("node", "land (try %d)" % attempt)
            rc, tail = self.sh(["git", "fetch", "-q", "origin"])
            if rc == 0:
                rc, tail = self.sh(["git", "rebase", "-q", self.cfg["base"]])
            if rc:
                self.sh(["git", "rebase", "--abort"])
                raise Blocked("merge conflict with main; branch kept\n" + tail)
            if self.cfg["gate"]:
                rc, tail = self.sh(self.cfg["gate"])
                if rc:
                    raise Blocked("gate red on the rebased tree\n" + tail)
            rc, tail = self.sh(self.cfg["land"], env={"TASK_LOOP_GATED_TREE": self.git("rev-parse", "HEAD^{tree}")}
                               if self.cfg["gate"] else None)  # a pre-push hook may skip a gate this tree just passed
            if rc == 0:
                sha = self.git("rev-parse", "HEAD")
                tl.cmd_land(Args(id=self.bead, sha=sha, worktree=self.wt))
                return sha
            if not re.search(r"rejected|non-fast-forward|fetch first|stale info", tail):
                raise Blocked("land failed\n" + tail)
            self.warn("push rejected (main moved), try %d of 5" % attempt)
        raise Blocked("land rejected 5 times: main moves too fast")

    def wip(self, why):
        self.sh(["git", "add", "-A"])
        rc, _ = self.sh(["git", "commit", "-q", "-m", "wip (%s): %s" % (self.bead, why)])
        return rc == 0

    def close(self, outcome, why, sha, question):
        if hasattr(signal, "SIGTERM") and threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGTERM, signal.SIG_IGN)  # a second stop must not break the close-out
        why = why or ("stopped before a reason was recorded" if outcome == "failed" else "")
        mins = (time.time() - self.t0) / 60
        if outcome not in ("landed", "done") and self.git("status", "--porcelain") and \
                self.git("symbolic-ref", "--short", "-q", "HEAD").startswith("task/"):
            self.wip(outcome)  # the next run continues this branch
        stats = "cost=$%.2f; minutes=%d; %s" % (self.cost, mins, "; ".join("%s=%s" % kv for kv in self.stats.items()))
        self.log("node", "close: %s" % outcome, outcome=outcome, why=why)
        self.write_trace(outcome, why, sha)
        self.detail([stats] + ([why[:400]] if why else []) + (["question: " + question[:400]] if question else []))
        if outcome == "failed":
            self.warn("task failed: %s" % why.splitlines()[0][:200])
        if self.dry:
            self.log("note", "dry run: bead left as it was. %s" % stats)
            return
        for lo in self.leftovers:
            tl.bd("create", lo["title"], "--type", "task", "--description", lo["why"],
                  "--deps", "discovered-from:" + self.bead)
        self.comment("Reflect (engine): outcome=%s; filed=%d; %s%s; trace=%s (tl trace %s)" % (
            outcome, len(self.leftovers), stats, ("; why=" + why) if why else "", self.log_path.stem, self.bead))
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


ENGINE_NOTES = ("Plan (engine)", "Review (engine", "Reflect (engine)", "Blocked:")


def brief_digest(bead, comments):
    """Markdown brief: title, the bead's text fields whole, related beads by title, people's comments whole, and one
    line on how the last engine run ended."""
    out = ["# %s: %s" % (bead.get("id", ""), bead.get("title", ""))]
    meta = [bead.get("issue_type"), "P%s" % bead["priority"] if bead.get("priority") is not None else "",
            ", ".join(bead.get("labels") or [])]
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
    if last:
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
            ["question: " + d["question"]] if d["question"].strip() else [])
    if node == "review":
        return (["%s %s:%s %s" % (f["severity"], f["file"], f["line"], f["fix"]) for f in d["findings"]] +
                ["unmet: " + u for u in d["unmet"]] + ["leftover: " + lo["title"] for lo in d["leftovers"]] +
                (["question: " + d["question"]] if d["question"].strip() else []))
    return []


def summarize(node, d):
    if node == "plan":
        return "%d stages, %d risks: %s" % (len(d["stages"]), len(d["risks"]), d["summary"][:200])
    if node == "write":
        return d["summary"][:300]
    if node == "review":
        return "%d findings, %d unmet" % (len(d["findings"]), len(d["unmet"]))
    return ""


# ---- prompts (one copy each; the per-node instructions of the design) -----------------------------------------------

COMMON = ("You are one step of an unattended task engine. Nobody is watching; do not ask for confirmation. "
          "Work only in {wt}. Never commit, push, branch, or change git state. Never add suppressions or weaken, skip "
          "or delete tests. Answer with the structured result only.")

PLAN_PROMPT = COMMON + """

Read the task: {brief} (the bead, with its acceptance criteria and comments: earlier plans, review findings,
the owner's answers). Read the code it names. Then plan.

- Split the work into stages, each one coherent piece that its checks can judge (often one stage is enough).
- For each stage: goal, the files it changes, the exact commands that prove it (tests, linters), and hard=true only
  when it is risky or subtle. Every check is a shell command that exits 0 when it proves the goal and non-zero when it
  does not: the engine reads only the exit code. "Expect empty" is `test -z "$(...)"` or `! grep ...`, never a bare
  grep; a count is `test "$(... | wc -l)" -eq 25`, never a comment saying what to expect.
- The engine sets every time limit and runs checks one at a time; never write timeouts, "run alone" or similar notes
  into a check.
- Name the risks ahead of time: what could break something users or other code rely on (a saved format, a public
  member, shared files), each with the check that proves it safe. None is fine.
- question: empty, unless the task cannot be done without a decision only the owner can make (product direction,
  scope, a hard-to-reverse architecture choice). Decide technical choices yourself. If you ask, write the question
  so it can be answered from a phone: what you found, the decision, 2-3 options with costs, your recommendation."""

WRITE_PROMPT = """You are the writer for one stage of a task, in an unattended engine. Nobody is watching.

Task: {brief}. Plan: {plan}. Your stage: {n}: {goal}{rules}
Files: {files}
The stage's checks (the engine runs all of them after you, outside your sandbox):
{checks}
{where}
Never run the gate{gate} or the issue tracker (bd): the engine runs the gate, and its run is the one that counts.
Repo instructions that say a change is done only when the full gate passes are for people working by hand; here the
engine does that part.
{feedback}
Checks your sandbox cannot run (network, local ports, paths outside this folder) are run by the engine after you,
outside the sandbox; say so in the summary and move on, never ask about permissions.
A check that times out or fails only in your sandbox is not yours to retry; note it once and move on.
Proof the engine cannot rerun (a test seen failing after a planted fault, then passing once restored; a manual
measurement): save the exact commands and their output as files in {evidence}/ and name those files in the summary.
Only that proof goes there, never your own runs of the checks.
Rules: no commits, no pushing, no branches; no suppressions; do not weaken, skip or delete tests; stay inside the
stage. question: empty unless only the owner can decide something about the task itself (then explain it for a
phone); never a question about tools, sandbox or permissions."""

REVIEW_PROMPT = """You review one stage of a task, from another model family than the writer. Do not edit files.
Task: {brief}. Plan: {plan}. Stage {n}: {goal}
The work: `git diff {base}` and new files (the task's work since main, committed or not).
The engine ran the checks outside any sandbox, and they all pass; these results are facts:
{checks}
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
- leftovers: real follow-up work you noticed outside this task, else empty."""


# ---- entry ----------------------------------------------------------------------------------------------------------

def load_cfg(repo):
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        user = json.loads((Path(repo) / ".task-loop.json").read_text(encoding="utf-8")).get("engine") or {}
    except (OSError, ValueError):
        user = {}
    cfg.update(user)
    return cfg


def main(a):
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
    if not a.dry_run and tl.cmd_claim(Args(id=a.id, worktree=wt, slot=a.slot)) != 0:
        return 1  # bd lets this session re-claim its own bead (a reopened one); another session's claim stops here
    eng = Engine(a.id, wt, cfg, dry_run=a.dry_run, verbose=not getattr(a, "quiet", False))
    say("engine log: %s" % eng.log_path)
    return eng.run()
