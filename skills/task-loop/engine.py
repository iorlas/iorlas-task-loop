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
import shutil
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
    "workers": {"plan": "claude:opus", "write": "codex", "verify": "claude:sonnet", "review": "other",
                "judge": "claude:haiku"},
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


_claude_ok = []


def claude_available():
    if not _claude_ok:
        ok = False
        exe = shutil.which("claude")
        if exe:
            try:
                r = subprocess.run([exe, "auth", "status"], capture_output=True, text=True, timeout=20,
                                   env=child_env(), stdin=subprocess.DEVNULL)
                ok = '"loggedIn": true' in r.stdout
            except (OSError, subprocess.SubprocessError):
                pass
        _claude_ok.append(ok)
    return _claude_ok[0]


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


def call_codex(model, prompt, schema, cwd, write, resume, timeout, log_path, on_ref=None):
    with tempfile.TemporaryDirectory() as d:
        sf, of = os.path.join(d, "schema.json"), os.path.join(d, "out.json")
        Path(sf).write_text(json.dumps(schema))
        sandbox = "workspace-write" if write else "read-only"
        base = ["codex", "exec"] + (["resume", resume] if resume else [])
        cmd = base + ["--skip-git-repo-check", "--json", "--output-schema", sf, "-o", of,
                      "-c", "sandbox_mode=\"%s\"" % sandbox, "-c", "approval_policy=\"never\""]
        if model:
            cmd += ["-m", model]
        cmd.append(prompt)

        def on_line(ln):
            if on_ref and '"thread.started"' in ln:
                on_ref(json.loads(ln).get("thread_id"))
        res, secs = run_proc(cmd, cwd, timeout, log_path, on_line)
        if res is None:
            return Result(secs=secs, error="timeout", backend="codex", ref=resume or "")
        code, out = res
        thread = resume or ""
        for ln in out.splitlines():
            if '"thread.started"' in ln:
                try:
                    thread = json.loads(ln).get("thread_id") or thread
                except ValueError:
                    pass
                break
        text = Path(of).read_text(encoding="utf-8") if os.path.exists(of) else ""
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        err = "" if code == 0 else "codex exit %d" % code
        return Result(data, text, thread, 0.0, secs, err, "codex")


def call_claude(model, prompt, schema, cwd, write, resume, timeout, log_path, on_ref=None):
    sid = resume or str(uuid.uuid4())
    if on_ref:
        on_ref(sid)
    tools = ["Read", "Glob", "Grep", "Bash"] + (["Edit", "Write"] if write else [])
    cmd = ["claude", "-p", "--output-format", "json", "--json-schema", json.dumps(schema), "--model", model,
           "--permission-mode", "acceptEdits" if write else "default", "--allowedTools"] + tools
    cmd += (["--resume", sid] if resume else ["--session-id", sid]) + ["--", prompt]
    res, secs = run_proc(cmd, cwd, timeout, log_path)
    if res is None:
        return Result(secs=secs, error="timeout", backend="claude", ref=sid)
    code, out = res
    try:
        j = json.loads(out)
    except ValueError:
        return Result(text=out[-2000:], ref=sid, secs=secs, error="claude exit %d, no json" % code, backend="claude")
    data = j.get("structured_output")
    if data is None:
        try:
            data = json.loads(j.get("result") or "")
        except ValueError:
            data = None
    err = j.get("result") if j.get("is_error") else ""
    return Result(data, j.get("result") or "", sid, float(j.get("total_cost_usd") or 0), secs, err or "", "claude")


# ---- the engine -----------------------------------------------------------------------------------------------------

class Blocked(Exception):
    def __init__(self, why, question=""):
        super().__init__(why)
        self.why, self.question = why, question


class Engine:
    def __init__(self, bead, wt, cfg, dry_run=False):
        self.bead, self.wt, self.cfg, self.dry = bead, wt, cfg, dry_run
        self.t0 = time.time()
        self.cost = 0.0
        self.stats = {"rounds": 0, "reviews": 0, "replans": 0, "nodes": 0, "tests_added": 0, "tests_removed": 0}
        self.session = tl.session_id()
        self.leftovers = []
        self.writer = {}  # backend -> thread/session id, so later rounds of a task resume the same writer
        d = tl.config_dir() / "engine"
        d.mkdir(exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.log_path = d / ("%s-%s.jsonl" % (bead, stamp))
        self.err_path = d / ("%s-%s.stderr" % (bead, stamp))
        self.task_dir = Path(wt) / ".task" / bead
        self.task_dir.mkdir(parents=True, exist_ok=True)

    # -- records
    def log(self, kind, text, **kw):
        rec = {"t": time.time(), "kind": kind, "text": text}
        rec.update(kw)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if kind == "node":
            tl.event("stage", self.bead, text=text)
        print("[%s] %s" % (time.strftime("%H:%M:%S"), text), flush=True)

    def budget_check(self):
        mins = (time.time() - self.t0) / 60
        if self.cost > float(self.cfg["budget_usd"]) or mins > float(self.cfg["budget_min"]):
            raise Blocked("over budget: $%.2f of $%s, %d of %s min" % (self.cost, self.cfg["budget_usd"], mins,
                                                                        self.cfg["budget_min"]))

    # -- AI node
    def backend_for(self, node, writer_family=None):
        spec = self.cfg["workers"].get(node) or "codex"
        if spec == "other":
            spec = "claude:sonnet" if writer_family == "codex" else "codex"
        fam, _, model = spec.partition(":")
        if fam == "claude" and not claude_available():
            fam, model = "codex", ""
        return fam, model

    def ai(self, node, title, prompt, write=False, resume_key=None, writer_family=None):
        self.budget_check()
        self.stats["nodes"] += 1
        fam, model = self.backend_for(node, writer_family)
        schema = SCHEMAS[node]
        resume = self.writer.get(fam) if resume_key else None
        self.log("node", "%s: %s" % (node, title), node=node, backend=fam, model=model, resume=bool(resume))
        run_id = str(uuid.uuid4())
        rec = {"kind": "codex" if fam == "codex" else "claude-p", "parent_session": self.session, "cwd": self.wt,
               "title": "%s · %s: %s" % (self.bead, node, title), "model": model or fam, "lane": node,
               "started": time.time(), "status": "running"}
        tl_agent_run(run_id, rec)
        fn = call_codex if fam == "codex" else call_claude
        timeout = float(self.cfg["node_timeout_min"]) * 60
        attempt_prompt = prompt
        for attempt in (1, 2):
            ref_key = "thread" if fam == "codex" else "session"
            r = fn(model, attempt_prompt, schema, self.wt, write, resume, timeout, self.err_path,
                   on_ref=lambda ref, k=ref_key: tl_agent_run(run_id, {k: ref}))
            self.cost += r.cost
            ref = {"thread": r.ref} if fam == "codex" else {"session": r.ref}
            tl_agent_run(run_id, dict(ref))
            if resume_key and r.ref:
                self.writer[fam] = r.ref
                resume = r.ref
            errs = validate(r.data, schema) if r.data is not None else ["no structured output" +
                                                                         (": " + r.error if r.error else "")]
            if not errs:
                break
            self.log("note", "%s output invalid (try %d): %s" % (node, attempt, "; ".join(errs[:4])))
            fix = ("Your previous answer did not match the required output schema: %s. Answer again with only the "
                   "structured result." % "; ".join(errs[:6]))
            if r.ref and r.error != "timeout":  # retry inside the same thread: it keeps its context
                resume, attempt_prompt = r.ref, fix
            else:
                resume, attempt_prompt = None, prompt + "\n\n" + fix
        ok = not errs
        tl_agent_run(run_id, {"ended": time.time(), "status": "completed" if ok else "failed",
                              "exit": 0 if ok else 1})
        if not ok:
            raise Blocked("failed: %s node produced no valid output (%s)" % (node, "; ".join(errs[:3])))
        (self.task_dir / ("%s-%d.json" % (node, self.stats["nodes"]))).write_text(json.dumps(r.data, indent=1))
        self.log("msg", "%s → %s" % (node, summarize(node, r.data)), node=node, data=r.data, cost=r.cost,
                 secs=round(r.secs), backend=fam)
        return r.data, fam

    # -- script helpers
    def sh(self, cmd, timeout=3600, check=False):
        self.log("cmd", cmd)
        r = subprocess.run(cmd, shell=True, cwd=self.wt, capture_output=True, text=True, timeout=timeout,
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
        self.sh("git fetch -q origin", check=True)
        exists = bool(self.git("rev-parse", "--verify", "-q", "refs/heads/" + branch))
        if self.git("status", "--porcelain"):
            if self.git("symbolic-ref", "--short", "-q", "HEAD") != branch:
                raise Blocked("failed: worktree %s has uncommitted work of another branch" % self.wt)
            self.wip("left from an earlier run")
        if exists:
            self.sh("git checkout -q %s" % branch, check=True)
        else:
            self.sh("git checkout -q -B %s %s" % (branch, self.cfg["base"]), check=True)
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
            w, wfam = self.ai("write", "%s round %d" % (name, rnd), WRITE_PROMPT.format(
                brief=self.task_dir / "brief.md", plan=self.task_dir / "plan.json", n=i + 1, goal=st["goal"],
                files=", ".join(st["files"]), checks="\n".join("- " + c for c in st["checks"]) or "- (none named)",
                feedback=feedback), write=True, resume_key="writer")
            checks = self.run_checks(st, name)
            (self.task_dir / "checks.json").write_text(json.dumps(checks, indent=1))
            diff_before = self.git("diff", "HEAD")
            v, _ = self.ai("verify", name, VERIFY_PROMPT.format(goal=st["goal"], checks=self.task_dir / "checks.json",
                                                               brief=self.task_dir / "brief.md"), write=True)
            if self.git("diff", "HEAD") != diff_before:
                v["risk_flags"].append("the verifier changed files")
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
            j, _ = self.ai("judge", name, JUDGE_PROMPT.format(facts=self.task_dir / "judge-input.json"))
            self.leftovers += j["leftovers"]
            if j["decision"] == "accept" and failed:
                self.log("note", "judge accepted with %d failed checks: rework instead" % len(failed))
                j = dict(j, decision="rework", why="These checks fail: " + "; ".join(
                    "`%s` exit %d: %s" % (c["cmd"], c["exit"], c["tail"][-300:]) for c in failed))
            if j["decision"] == "accept":
                return "accept"
            if j["decision"] == "block":
                raise Blocked(j["why"], j["question"])
            if j["decision"] == "replan":
                (self.task_dir / "replan.md").write_text(j["why"] + "\n\n" + json.dumps(facts, indent=1))
                return "replan"
            feedback = ("\nThe previous round was not accepted. Fix exactly this:\n%s\nGaps: %s\nFindings: %s\n"
                        "Check results (run by the engine, outside your sandbox): %s\n" % (
                            j["why"], "; ".join(v["gaps"]), "; ".join(f["fix"] for f in review["findings"]),
                            self.task_dir / "checks.json"))
        raise Blocked("stage %d not accepted after %s rounds" % (i + 1, self.cfg["max_rounds"]))

    def run_checks(self, st, name):
        """The stage's checks and the gate, run by the engine outside any sandbox: the results are facts."""
        cmds = list(st["checks"])
        if self.cfg["gate"] and self.cfg["gate"] not in cmds:
            cmds.append(self.cfg["gate"])
        self.log("node", "checks: %s" % name)
        out = []
        for c in cmds:
            rc, tail = self.sh(c, timeout=float(self.cfg["node_timeout_min"]) * 60)
            out.append({"cmd": c, "exit": rc, "tail": tail[-1500:]})
        return out

    def finish(self, bead):
        if not self.git("status", "--porcelain"):
            if self.git("rev-list", "--count", "%s..HEAD" % self.cfg["base"]) in ("", "0"):
                self.log("note", "nothing changed")
                return ""
        else:
            self.sh("git add -A", check=True)
            msg = "%s (%s)" % (bead.get("title", self.bead)[:72], self.bead)
            rc, tail = self.sh("git commit -q -m %s" % sh_quote(msg))
            if rc:
                raise Blocked("failed: commit refused (hooks)\n" + tail)
        if self.dry:
            self.log("note", "dry run: not landing")
            return ""
        for attempt in range(1, 6):
            self.log("node", "land (try %d)" % attempt)
            rc, tail = self.sh("git fetch -q origin && git rebase -q %s" % self.cfg["base"])
            if rc:
                self.sh("git rebase --abort")
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
        raise Blocked("land rejected 5 times: main moves too fast")

    def wip(self, why):
        self.sh("git add -A")
        rc, _ = self.sh("git commit -q -m %s" % sh_quote("wip (%s): %s" % (self.bead, why)))
        return rc == 0

    def close(self, outcome, why, sha, question):
        mins = (time.time() - self.t0) / 60
        if outcome not in ("landed", "done") and self.git("status", "--porcelain") and \
                self.git("symbolic-ref", "--short", "-q", "HEAD").startswith("task/"):
            self.wip(outcome)  # the next run continues this branch
        stats = "cost=$%.2f; minutes=%d; %s" % (self.cost, mins, "; ".join("%s=%s" % kv for kv in self.stats.items()))
        self.log("node", "close: %s" % outcome, outcome=outcome, why=why)
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


def tl_agent_run(run_id, fields):
    """This engine is a worker launcher: it publishes agent-runs v1 records like any other (docs/contracts)."""
    root = (Path(os.environ["APPDATA"]) if os.name == "nt" else
            Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")) / "agent-runs" / "runs"
    root.mkdir(parents=True, exist_ok=True)
    f = root / (run_id + ".json")
    try:
        rec = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rec = {"v": 1, "producer": "tl-engine", "id": run_id}
    rec.update(fields)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec), encoding="utf-8")
    os.replace(tmp, f)


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


class Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def sh_quote(s):
    return "'" + s.replace("'", "'\"'\"'") + "'"


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
Before reporting, run these checks and make them pass:
{checks}
{feedback}
Checks your sandbox cannot run (network, local ports, paths outside this folder) are run by the engine after you,
outside the sandbox; say so in the summary and move on, never ask about permissions.
Rules: no commits, no pushing, no branches; no suppressions; do not weaken, skip or delete tests; stay inside the
stage. question: empty unless only the owner can decide something about the task itself (then explain it for a
phone); never a question about tools, sandbox or permissions."""

VERIFY_PROMPT = """You are a fresh verifier. Do not edit any file. Judge the uncommitted changes in this folder
(`git diff HEAD` and new files) against the stage goal: {goal}
Task: {brief}

The engine already ran the stage's checks outside any sandbox; their exit codes and output are in {checks}: copy them
into checks (a check you cannot run yourself because of the sandbox is not a gap). Read the diff and the tests.
Then: count tests added and removed in the diff; list files changed outside what the task names (outside_touches);
risk_flags: a public member changed, a test deleted/weakened/filtered, a suppression added, anything risky.
verdict: accept only if every check exits 0 and the goal is met; else gaps, with each gap listed."""

REVIEW_PROMPT = """You are a reviewer from another model family than the writer. Do not edit files.
Read the uncommitted diff (`git diff HEAD` and new files) against the task {brief} and its plan {plan}
(the risks named there). The verifier flagged: {flags}.
Return findings that matter (bugs, broken contracts, risky changes), each with file, line, severity and the fix.
No style nits. None is a fine answer."""

JUDGE_PROMPT = """You are the judge of one stage in an unattended task engine. Read the facts: {facts}
(the stage, the round number, the writer's summary, the verifier's report, the reviewer's findings).
Decide:
- accept: the stage goal is met, the checks ran and passed, no high-severity finding is open.
- rework: fixable within this stage; say exactly what to fix in why.
- replan: the plan itself is wrong (wrong files, wrong approach, a missed dependency).
- block: only the owner can unblock it (a product or scope decision); put the question in question.
Distrust the writer's summary; trust commands that were run. leftovers: real follow-up work noticed, else empty."""


# ---- entry ----------------------------------------------------------------------------------------------------------

def load_cfg(repo):
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        user = json.loads((Path(repo) / ".task-loop.json").read_text(encoding="utf-8")).get("engine") or {}
    except (OSError, ValueError):
        user = {}
    workers = dict(cfg["workers"], **(user.get("workers") or {}))
    cfg.update(user)
    cfg["workers"] = workers
    return cfg


def main(a):
    if not os.environ.get("TASK_LOOP_SESSION") and not tl.session_id():
        os.environ["TASK_LOOP_SESSION"] = "engine-" + uuid.uuid4().hex[:12]
    repo = tl.repo_root()
    cfg = load_cfg(repo)
    wt = a.worktree
    if not wt:
        r = subprocess.run([sys.executable, str(Path(__file__).with_name("tl.py")), "worktree", "start"],
                           capture_output=True, text=True)
        wt = r.stdout.strip().splitlines()[-1] if r.returncode == 0 and r.stdout.strip() else ""
        if not wt:
            sys.exit("tl: no worktree: " + r.stderr)
    wt = str(Path(wt).resolve())
    if not a.dry_run:
        mine = (tl.show(a.id).get("assignee") or "") == tl.actor()
        if not mine and tl.cmd_claim(Args(id=a.id, worktree=wt, slot=a.slot)) != 0:
            return 1
    eng = Engine(a.id, wt, cfg, dry_run=a.dry_run)
    print("engine log: %s" % eng.log_path, flush=True)
    return eng.run()
