#!/usr/bin/env python3
"""The task engine: one bead through reset → plan → (write → verify → [review] → judge)* → gate → land → close.

    tl.py run-task ID [--worktree DIR] [--dry-run]

Code routes; AI nodes only produce structured outputs (validated against a schema). The close step always runs.
A coordinator session may start it and watch it (attended mode); nothing here needs one. Design:
docs/design/coordinator-less.md. Python 3.8+, standard library only.
"""

import json
import os
import re
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
    "max_rounds": 3,                  # write rounds per stage before the task is blocked
    "max_replans": 1,
    "node_timeout_min": 45,
    "delegate": "",                   # path to delegate's route.py; "" = the newest installed iorlas-delegate
    "lane_wait_min": 60,              # how long a step waits for a lane that is out before the task is blocked
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
    "verify": {"type": "object", "additionalProperties": False,
               "required": ["verdict", "checks", "gaps", "risk_flags", "outside_touches", "tests_added",
                            "tests_removed"],
               "properties": {"verdict": {"type": "string", "enum": ["accept", "gaps"]},
                              "checks": {"type": "array", "items": {
                                  "type": "object", "additionalProperties": False, "required": ["cmd", "exit", "tail"],
                                  "properties": {"cmd": S_STR, "exit": {"type": "integer"}, "tail": S_STR}}},
                              "gaps": S_STRS, "risk_flags": S_STRS, "outside_touches": S_STRS,
                              "tests_added": {"type": "integer"}, "tests_removed": {"type": "integer"}}},
    "review": {"type": "object", "additionalProperties": False, "required": ["findings"],
               "properties": {"findings": {"type": "array", "items": {
                   "type": "object", "additionalProperties": False, "required": ["file", "line", "severity", "fix"],
                   "properties": {"file": S_STR, "line": {"type": "integer"},
                                  "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                                  "fix": S_STR}}}}},
    "judge": {"type": "object", "additionalProperties": False, "required": ["decision", "why", "question", "leftovers"],
              "properties": {"decision": {"type": "string", "enum": ["accept", "rework", "replan", "block"]},
                             "why": S_STR, "question": S_STR, "leftovers": LEFTOVERS}},
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


ROLES = {"plan": "planner", "write": "worker", "verify": "light", "review": "reviewer", "judge": "light"}


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


def call_delegate(route, role, prompt, schema, cwd, resume, timeout, log_path, writer=None, parent="", task="",
                  title=""):
    """One AI step through `route.py run` (worker-run v1). Returns (Result, the answer object or None)."""
    with tempfile.TemporaryDirectory() as d:
        bf, sf = os.path.join(d, "brief.md"), os.path.join(d, "schema.json")
        Path(bf).write_text(prompt, encoding="utf-8")
        Path(sf).write_text(json.dumps(schema))
        cmd = [sys.executable, route, "run", role, "--brief", bf, "--cwd", cwd, "--schema", sf,
               "--timeout", str(int(timeout)), "--parent", parent, "--task", task, "--title", title[:120]]
        if resume:
            cmd += ["--resume", resume]
        if writer:
            cmd += ["--writer", writer]
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
        self.stats = {"rounds": 0, "reviews": 0, "replans": 0, "nodes": 0, "tests_added": 0, "tests_removed": 0}
        self.session = tl.session_id()
        self.leftovers = []
        self.budget_warned = set()
        self.writer = {}  # backend -> thread/session id, so later rounds of a task resume the same writer
        d = tl.config_dir() / "engine"
        d.mkdir(exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.log_path = d / ("%s-%s.jsonl" % (bead, stamp))
        self.err_path = d / ("%s-%s.stderr" % (bead, stamp))
        self.task_dir = Path(wt) / ".task" / bead
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
        self.log("node", "%s: %s" % (node, title), node=node, backend="delegate", role=role, resume=bool(resume))
        timeout = float(self.cfg["node_timeout_min"]) * 60
        waited, attempt_prompt, attempt, errs = 0.0, prompt, 1, ["not run"]
        while attempt <= 2:
            r, j = call_delegate(self.route, role, attempt_prompt, SCHEMAS[node], self.wt, resume, timeout,
                                 self.err_path, writer, self.session, self.bead, "%s · %s: %s" % (self.bead, node, title))
            if j is not None and j.get("v") != 1:
                raise Blocked("failed: delegate answered worker-run v%s, this engine speaks v1 (update task-loop)"
                              % j.get("v"))
            st = (j or {}).get("status")
            if st in ("lane_out", "stop"):
                wait = max(60.0, min(600.0, float(j.get("retry_after") or 0) - time.time()))
                if waited + wait > float(self.cfg["lane_wait_min"]) * 60:
                    raise Blocked("paused: no lane for %s (%s)" % (node, j.get("say") or st))
                self.warn("%s waits %d min for a lane: %s" % (node, wait // 60, j.get("say") or st))
                time.sleep(wait)
                waited += wait
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
        fam = r.backend  # openai | claude: the family that wrote, for the reviewer
        model = "%s %s on %s" % ((j or {}).get("model"), (j or {}).get("effort"), (j or {}).get("lane"))
        (self.task_dir / ("%s-%d.json" % (node, self.stats["nodes"]))).write_text(json.dumps(r.data, indent=1))
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
        if node == "verify":
            if d["tests_removed"]:
                self.warn("the diff removes %d tests" % d["tests_removed"])
            if d["outside_touches"]:
                self.warn("files outside the task: %s" % ", ".join(d["outside_touches"]))
        if node == "review" and any(f["severity"] == "high" for f in d["findings"]):
            self.warn("the reviewer found a high-severity problem")
        if node == "judge" and d["decision"] in ("replan", "block"):
            self.warn("judge says %s: %s" % (d["decision"], d["why"][:200]))

    # -- script helpers
    def sh(self, cmd, timeout=3600, check=False):
        """A command: a string goes through the shell (profile commands), a list runs as is (no quoting rules)."""
        self.log("cmd", cmd if isinstance(cmd, str) else " ".join(cmd))
        r = subprocess.run(cmd, shell=isinstance(cmd, str), cwd=self.wt, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                           stdin=subprocess.DEVNULL)
        tail = "\n".join((r.stdout + r.stderr).strip().splitlines()[-15:])
        self.log("note", "exit %d%s" % (r.returncode, (": " + tail[-600:]) if r.returncode else ""), exit=r.returncode)
        if check and r.returncode:
            raise Blocked("failed: `%s` exit %d\n%s" % (cmd, r.returncode, tail))
        return r.returncode, tail

    def git(self, *a):
        return tl.git(*a, cwd=self.wt)

    # -- nodes
    def reset(self, bead):
        self.log("node", "reset")
        branch = (bead.get("metadata") or {}).get("branch") or "task/" + self.bead
        self.sh(["git", "fetch", "-q", "origin"], check=True)
        exists = bool(self.git("rev-parse", "--verify", "-q", "refs/heads/" + branch))
        if self.git("status", "--porcelain"):
            if self.git("symbolic-ref", "--short", "-q", "HEAD") != branch:
                raise Blocked("failed: worktree %s has uncommitted work of another branch" % self.wt)
            self.wip("left from an earlier run")
        if exists:
            self.sh(["git", "checkout", "-q", branch], check=True)
        else:
            self.sh(["git", "checkout", "-q", "-B", branch, self.cfg["base"]], check=True)
        exclude = Path(self.git("rev-parse", "--path-format=absolute", "--git-common-dir")) / "info" / "exclude"
        if ".task/" not in (exclude.read_text() if exclude.exists() else ""):
            with open(exclude, "a") as f:
                f.write("\n.task/\n")
        self.export_brief()
        return branch

    def export_brief(self):
        r = tl.bd("show", self.bead)
        (self.task_dir / "brief.md").write_text(r.stdout, encoding="utf-8")

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
                        raise Blocked("judge asked to re-plan more than %s times" % self.cfg["max_replans"])
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
        extra = ("\n\nThe previous plan did not work; the judge's findings are in %s. Plan again." %
                 (self.task_dir / "replan.md")) if again else ""
        data, _ = self.ai("plan", "re-plan" if again else "plan", PLAN_PROMPT.format(brief=self.task_dir / "brief.md",
                                                                                     wt=self.wt) + extra)
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
        (self.task_dir / "plan.json").write_text(json.dumps(data, indent=1))
        self.export_brief()
        return data

    def stage(self, plan, i):
        st = plan["stages"][i]
        name = "stage %d/%d" % (i + 1, len(plan["stages"]))
        feedback = ""
        for rnd in range(1, int(self.cfg["max_rounds"]) + 1):
            self.stats["rounds"] += 1
            if rnd >= 2:
                self.warn("%s: write round %d" % (name, rnd))
            w, wfam = self.ai("write", "%s round %d" % (name, rnd), WRITE_PROMPT.format(
                brief=self.task_dir / "brief.md", plan=self.task_dir / "plan.json", n=i + 1, goal=st["goal"],
                files=", ".join(st["files"]), checks="\n".join("- " + c for c in st["checks"]) or "- (none named)",
                feedback=feedback, evidence=self.evidence_dir), resume_key="writer")
            checks = self.run_checks(st, name)
            (self.task_dir / "engine-checks.json").write_text(json.dumps(checks, indent=1))
            diff_before = self.git("diff", "HEAD")
            v, _ = self.ai("verify", name, VERIFY_PROMPT.format(goal=st["goal"], checks=compact(checks),
                                                               evidence=self.evidence_dir, summary=w["summary"],
                                                               brief=self.task_dir / "brief.md"))
            v["checks"] = [dict(c, tail=c["tail"][-600:]) for c in checks]  # the facts are the engine's runs, never a copy
            if self.git("diff", "HEAD") != diff_before:
                v["risk_flags"].append("the verifier changed files")
                self.warn("the verifier changed files")
            self.stats["tests_added"] += v["tests_added"]
            self.stats["tests_removed"] += v["tests_removed"]
            risky = bool(v["risk_flags"] or v["outside_touches"] or st["hard"] or rnd >= 3 or
                         any(r for r in plan["risks"]))
            review = {"findings": []}
            if risky and v["verdict"] == "accept":
                self.stats["reviews"] += 1
                review, _ = self.ai("review", name, REVIEW_PROMPT.format(brief=self.task_dir / "brief.md",
                                                                        plan=self.task_dir / "plan.json",
                                                                        flags="; ".join(v["risk_flags"] +
                                                                                       v["outside_touches"]) or "none"),
                                    writer_family=wfam)
                if review["findings"]:
                    self.comment("Review (engine, %s): " % name + "; ".join(
                        "%s:%s [%s] %s" % (f["file"], f["line"], f["severity"], f["fix"]) for f in review["findings"]))
            failed = [c for c in checks if c["exit"] != 0]
            facts = {"stage": st, "round": rnd, "writer": w, "checks_run_by_engine": checks, "verify": v,
                     "review": review}
            (self.task_dir / "judge-input.json").write_text(json.dumps(facts, indent=1))
            j, _ = self.ai("judge", name, JUDGE_PROMPT.format(facts=json.dumps(dict(facts, checks_run_by_engine=[
                dict(c, tail=c["tail"][-600:]) for c in checks]), indent=1)))
            self.leftovers += j["leftovers"]
            if j["decision"] == "accept" and failed:
                self.warn("judge accepted with %d failed checks: rework instead" % len(failed))
                j = dict(j, decision="rework", why="These checks fail: " + "; ".join(
                    "`%s` exit %d: %s" % (c["cmd"], c["exit"], c["tail"][-300:]) for c in failed))
            if j["decision"] == "accept":
                return "accept"
            if j["decision"] == "block":
                if not j["question"].strip():  # a block is for the owner; one without a question is the engine's problem
                    raise Blocked("failed: judge blocked without an owner question: " + j["why"])
                raise Blocked(j["why"], j["question"])
            if j["decision"] == "replan":
                (self.task_dir / "replan.md").write_text(j["why"] + "\n\n" + json.dumps(facts, indent=1))
                return "replan"
            feedback = ("\nThe previous round was not accepted. Fix exactly this:\n%s\nGaps: %s\nFindings: %s\n"
                        "Check results (run by the engine, outside your sandbox): %s\n" % (
                            j["why"], "; ".join(v["gaps"]), "; ".join(f["fix"] for f in review["findings"]),
                            compact(checks)))
        raise Blocked("stage %d not accepted after %s rounds" % (i + 1, self.cfg["max_rounds"]))

    def run_checks(self, st, name):
        """The stage's checks and the gate, run by the engine outside any sandbox: the results are facts."""
        cmds = list(st["checks"])
        if self.cfg["gate"] and self.cfg["gate"] not in cmds:
            cmds.append(self.cfg["gate"])
        self.log("node", "checks: %s" % name)
        out = []
        for c in cmds:
            t = time.time()
            rc, tail = self.sh(c, timeout=float(self.cfg["node_timeout_min"]) * 60)
            out.append({"cmd": c, "exit": rc, "tail": tail[-1500:]})
            self.detail(["%s `%s` exit %d (%ds)" % ("✓" if rc == 0 else "✗", c, rc, time.time() - t)] +
                        (tail.splitlines()[-3:] if rc else []))
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
            rc, tail = self.sh(self.cfg["land"])
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
        mins = (time.time() - self.t0) / 60
        if outcome not in ("landed", "done") and self.git("status", "--porcelain") and \
                self.git("symbolic-ref", "--short", "-q", "HEAD").startswith("task/"):
            self.wip(outcome)  # the next run continues this branch
        stats = "cost=$%.2f; minutes=%d; %s" % (self.cost, mins, "; ".join("%s=%s" % kv for kv in self.stats.items()))
        self.log("node", "close: %s" % outcome, outcome=outcome, why=why)
        self.detail([stats] + ([why[:400]] if why else []) + (["question: " + question[:400]] if question else []))
        if outcome == "failed":
            self.warn("task failed: %s" % why.splitlines()[0][:200])
        if self.dry:
            self.log("note", "dry run: bead left as it was. %s" % stats)
            return
        for lo in self.leftovers:
            tl.bd("create", lo["title"], "--type", "task", "--description", lo["why"],
                  "--deps", "discovered-from:" + self.bead)
        self.comment("Reflect (engine): outcome=%s; filed=%d; %s%s" % (outcome, len(self.leftovers), stats,
                                                                     ("; why=" + why) if why else ""))
        if outcome == "landed":
            tl.cmd_close(Args(id=self.bead, reason="merged %s" % sha[:12]))
        elif outcome == "done":
            tl.cmd_close(Args(id=self.bead, reason="done, nothing to land"))
        else:
            text = why + (("\n\nQuestion: " + question) if question else "")
            tl.cmd_block(Args(id=self.bead, why=text))


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


def compact(checks):
    """Check results for a prompt: command, exit code and the last lines of output."""
    return "\n".join("- `%s` exit %d%s" % (c["cmd"], c["exit"], (": " + c["tail"][-400:].replace("\n", " | "))
                                          if c["exit"] else "") for c in checks) or "- (no checks)"


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
    if node == "verify":
        return (["gap: " + g for g in d["gaps"]] + ["flag: " + f for f in d["risk_flags"]] +
                ["tests +%d -%d" % (d["tests_added"], d["tests_removed"])])
    if node == "review":
        return ["%s %s:%s %s" % (f["severity"], f["file"], f["line"], f["fix"]) for f in d["findings"]]
    if node == "judge":
        return ["leftover: " + lo["title"] for lo in d["leftovers"]] + (
            ["question: " + d["question"]] if d["question"].strip() else [])
    return []


def summarize(node, d):
    if node == "plan":
        return "%d stages, %d risks: %s" % (len(d["stages"]), len(d["risks"]), d["summary"][:200])
    if node == "write":
        return d["summary"][:300]
    if node == "verify":
        return "%s; checks %s; gaps %d; flags %s" % (d["verdict"], ", ".join(str(c["exit"]) for c in d["checks"]),
                                                     len(d["gaps"]), "; ".join(d["risk_flags"]) or "none")
    if node == "review":
        return "%d findings" % len(d["findings"])
    if node == "judge":
        return "%s: %s" % (d["decision"], d["why"][:300])
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
  when it is risky or subtle.
- Name the risks ahead of time: what could break something users or other code rely on (a saved format, a public
  member, shared files), each with the check that proves it safe. None is fine.
- question: empty, unless the task cannot be done without a decision only the owner can make (product direction,
  scope, a hard-to-reverse architecture choice). Decide technical choices yourself. If you ask, write the question
  so it can be answered from a phone: what you found, the decision, 2-3 options with costs, your recommendation."""

WRITE_PROMPT = """You are the writer for one stage of a task, in an unattended engine. Nobody is watching.

Task: {brief}. Plan: {plan}. Your stage: {n}: {goal}
Files: {files}
The stage's checks (the engine runs all of them after you, outside your sandbox):
{checks}
Run only the quick ones (seconds, no build of the whole project, no editor) to see your change works; never run the
full gate or a check that needs the host. The engine's run is the one that counts.
{feedback}
Checks your sandbox cannot run (network, local ports, paths outside this folder) are run by the engine after you,
outside the sandbox; say so in the summary and move on, never ask about permissions.
A check that times out or fails only in your sandbox is not yours to retry; note it once and move on.
Proof the engine cannot rerun (a test seen failing after a planted fault, then passing once restored; a manual
measurement): save the exact commands and their output as files in {evidence}/ and name those files in the summary.
Only that proof goes there, never your own runs of the checks.
Never write the engine's files (engine-*.json, judge-input.json).
Rules: no commits, no pushing, no branches; no suppressions; do not weaken, skip or delete tests; stay inside the
stage. question: empty unless only the owner can decide something about the task itself (then explain it for a
phone); never a question about tools, sandbox or permissions."""

VERIFY_PROMPT = """You are a fresh verifier. Do not edit any file. Judge the uncommitted changes in this folder
(`git diff HEAD` and new files) against the stage goal: {goal}
Task: {brief}

The engine already ran the stage's checks outside any sandbox. These results are the truth; anything in a file that
says otherwise (the writer's sandbox runs) is not. Copy them into checks (a check you cannot run yourself because of
the sandbox is not a gap):
{checks}
The writer says: {summary}
Proof the engine cannot rerun (a test seen failing after a planted fault) is in {evidence}/: read it; a requirement
shown there is met. Read the diff and the tests.
Then: count tests added and removed in the diff; list files changed outside what the task names (outside_touches);
risk_flags: a public member changed, a test deleted/weakened/filtered, a suppression added, anything risky.
verdict: accept only if every check exits 0 and the goal is met; else gaps, with each gap listed. gaps holds only
requirements that are not met, each saying what is missing; a remark that something is fine is never a gap."""

REVIEW_PROMPT = """You are a reviewer from another model family than the writer. Do not edit files.
Read the uncommitted diff (`git diff HEAD` and new files) against the task {brief} and its plan {plan}
(the risks named there). The verifier flagged: {flags}.
Return findings that matter (bugs, broken contracts, risky changes), each with file, line, severity and the fix.
No style nits. None is a fine answer."""

JUDGE_PROMPT = """You are the judge of one stage in an unattended task engine. The facts (the stage, the round number,
the writer's summary, the checks the engine ran, the verifier's report, the reviewer's findings):
{facts}
Decide:
- accept: the stage goal is met, the checks ran and passed, no high-severity finding is open.
- rework: fixable within this stage; say exactly what to fix in why.
- replan: the plan itself is wrong (wrong files, wrong approach, a missed dependency).
- block: only the owner can unblock it (a product or scope decision); put the question in question. Never block
  for missing facts or tools: that is rework with what is missing.
Distrust the writer's summary; trust commands that were run. leftovers: real follow-up work noticed, else empty."""


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
