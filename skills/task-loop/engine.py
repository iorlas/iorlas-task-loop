#!/usr/bin/env python3
"""The task engine: one bead through reset → plan → (write → checks → review)* per stage → gate → land → close.

    tl.py run-task ID [--worktree DIR] [--dry-run]

Code routes; AI nodes only produce structured outputs (validated against a schema). The close step always runs.
A coordinator session may start it and watch it (attended mode); nothing here needs one. Design:
docs/design/coordinator-less.md. Python 3.8+, standard library only.
"""

import contextlib
import difflib
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
    "max_replans": 2,                 # per bead, across runs: plans after the first (amends of any cause); then an owner ask
    "max_fix_rounds": 2,              # per bead: a red gate, a conflict or what the check before land found wrong
    "pick_label": "",                 # the label an unattended runner picks by (lifesim: auto); a decision or ticket ask removes it
    "needs_info_label": "needs-info", # and adds this one, so the bead leaves the queue until the owner relabels it
    "skip_labels": [],                # the loop's queue (tl next, tl loop) never takes a bead with one of these labels
    "epic_order": [],                 # within a priority, beads under an earlier epic here (at any depth) come first
    "epic_only": False,               # true: beads under none of epic_order's epics are not taken at all
    "gate_only": [],                  # commands no plan check may run, only the gate at land: "cmd" or {cmd, why}
    "max_stages": 3,                  # a bigger plan is a split ask (ticket), unless the owner already answered one
    "node_timeout_min": 45,
    "writer_check_max_s": 60,         # a check whose last run took longer is the engine's, never the writer's to run
    "delegate": "",                   # path to delegate's route.py; "" = the newest installed iorlas-delegate
    "lane_wait_min": 10,              # how long a step waits in its slot for a lane; longer: the run pauses (slot freed)
    "checks": [],                     # repo checks: [{id, cmd, group: static|tests|acceptance, when: [globs], retry}]
    "host": False,                    # the work needs the host (Unity, an editor): write steps get delegate's --host
                                      # a bead label `sandbox` turns it off for one bead
    "no_sandbox": False,              # the 0.6 name of `host`, still read
    "worker_rules": "",               # repo file the planner and writer read first (lifesim: docs/agents/codex.md)
    "brief_kb": 5,
    "test_pattern": r"^\s*(def test_|async def test_|\[(Test|UnityTest|Fact|Theory|TestMethod|TestCase)\b|#\[test\]|(it|test)\(|func Test)",                    # a brief bigger than this gets a ⚠ (never cut: the bead may be too big)
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

DRY_CHECK_TEXT = ("\n\nYour plan was sent back: the engine dry-ran its checks and these cannot run:\n%s\nReturn the plan "
                  "with only these checks fixed.")


# tl-bxk.10.9: an unchecked item naming one of these, or a backticked command, is a check only where the repo uses it
KNOWN_TOOLS = {"ruff", "black", "flake8", "pylint", "mypy", "pyright", "isort", "bandit", "eslint", "prettier", "tsc",
               "biome", "stylelint", "shellcheck", "shfmt", "hadolint", "yamllint", "markdownlint", "actionlint",
               "golangci-lint", "gofmt", "staticcheck", "clippy", "rustfmt", "rubocop", "ktlint", "detekt", "swiftlint",
               "clang-tidy", "clang-format", "cppcheck", "csharpier", "semgrep", "codespell", "vale", "pre-commit", "prek"}
RUN_VERB = r"(?:run|runs|ran|running|lint|lints|linted|linting|format|formats|formatted|check|checks|checked)"


def tools_named(what):
    """The tools an unchecked item names: the first word of a backticked command with arguments (`ruff check tools`),
    or a known linter or formatter backticked (`mypy`) or right after a run, lint, format or check verb ("ran ruff",
    "checked with eslint"). Prose that only contains a tool's name ("the biome transition") names none."""
    found = []
    for cmd in re.findall(r"`([^`]+)`", what):
        words = cmd.split()
        if (len(words) > 1 and re.fullmatch(r"[a-z][a-z0-9+-]*", words[0])) or cmd.strip().lower() in KNOWN_TOOLS:
            found.append(words[0].lower())
    rx = re.compile(r"\b%s\s+(?:(?:with|by|using|the)\s+)?([a-z][a-z0-9+-]*)" % RUN_VERB)
    found += [w for w in rx.findall(what.lower()) if w in KNOWN_TOOLS]
    return list(dict.fromkeys(found))


def tool_on_path(name):
    return shutil.which(name)


def unused_tool(what, root, cfg):
    """The evidence that every tool an item names is one the repo does not use: nothing in the tracked tree mentions
    it (`git grep -w -I`, dot directories, CI, toolchain and agent files included), nor the engine's gate and checks,
    and it is not on PATH; "" when it names none or the repo uses one."""
    tools = tools_named(what)
    if not tools:
        return ""
    engine_text = " ".join([cfg.get("gate") or ""] + [str(c) for c in cfg.get("checks") or []])
    said = []
    for t in tools:
        r = tl.run_git(root, "grep", "-w", "-I", "-l", "-F", t, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
        if r.returncode not in (0, 1):  # no git tree to read: no evidence, the item stays
            return ""
        if r.stdout.strip() or re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(t), engine_text) or tool_on_path(t):
            return ""
        said.append("git grep -w -I %s: no match in the tracked tree nor the engine's gate and checks; which %s: "
                    "not found" % (t, t))
    return "not a check here: the repo does not use it (%s)" % "; ".join(said)


def plan_checks(plan):
    """The plan's checks: stages, risks, cases."""
    return list(dict.fromkeys([c for s in plan.get("stages") or [] for c in s["checks"]] + [
        x["check"] for k in ("risks", "cases") for x in plan.get(k) or []]))


def tracker_checks(plan):
    """The plan's checks that read the issue tracker instead of the code."""
    return [c for c in plan_checks(plan) if TRACKER_CHECK.search(c)]


# a command the repo runs only in the gate (the gate itself, engine.gate_only) is red by design on the uncommitted tree a
# writer leaves, so a check running it burns every round (lifesim-fld.27.9: `just unity-check`, 68 min, stuck)
CMD_LEAD = r"(?:^|[;&|(`!{]|\b(?:then|do|else|xargs|exec|command|env|time)\b)\s*"
GATE_ONLY_TEXT = ("\n\nYour plan was sent back: these checks run a command that runs only in the gate at land (the engine "
                  "runs it once, on the rebased tree), never on a stage's uncommitted tree:\n%s\nRewrite them without "
                  "it: the land gate proves what it proves.")


def gate_only(cfg):
    """[(cmd, why)]: the gate command and engine.gate_only's entries ("cmd" or {cmd, why})."""
    out = [(cfg.get("gate") or "", "the engine runs the gate once, on the rebased tree")]
    out += [(x, "") if isinstance(x, str) else (x.get("cmd") or "", x.get("why") or "") for x in cfg.get("gate_only") or []]
    return [(" ".join(c.split()), why) for c, why in out if c.strip()]


def gate_only_checks(plan, cfg):
    """[(check, reason)]: the plan's checks that run a gate-only command."""
    rules = [(re.compile(CMD_LEAD + r"\s+".join(map(re.escape, c.split())) + r"(?=\s|$|[;&|)`])"),
              "%s runs only in the gate at land%s" % (c, ": " + why if why else "")) for c, why in gate_only(cfg)]
    out = []
    for c in plan_checks(plan):
        hit = next((why for rx, why in rules if rx.search(c)), None)
        if hit:
            out.append((c, hit))
    return out


# a check that cannot run is found before any write, not by a writer's round (tl-bxk.10.13). Conservative on purpose: a false
# alarm costs a planner call, the thing this saves.
PROC_SUBST = re.compile(r"<\(")
FILE_ARG = re.compile(r"(?:^|[;&|(]\s*)(?:test|\[)\s+-[fesr]\s+(\S+)|(?:^|[;&|(]\s*)(?:cat|bash|sh|node|python3?)\s+(?:-[^\smc]\S*\s+)*([^\s;&|<>$`'\"-]*[./]\S*)")


def dry_check(plan, wt):
    """[error]: the plan's checks that cannot run: bash -n syntax, process substitution, a file the check reads that is
    neither in the tree nor a file some stage names."""
    errs, made = [], [os.path.normpath(f) for st in plan.get("stages") or [] for f in st["files"]]
    for c in plan_checks(plan):
        bare = re.sub(r"\"[^\"]*\"|'[^']*'", "''", c)
        if PROC_SUBST.search(bare):
            errs.append("`%s`: process substitution `<(` is not allowed (write the output to a file instead)" % c)
        try:
            r = subprocess.run(["bash", "-n"], input=c, capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            r = None
        if r is not None and r.returncode:
            errs.append("`%s`: bash -n: %s" % (c, (r.stderr or "syntax error").strip().splitlines()[-1][:200]))
            continue
        if re.search(r"(?:^|[;&|(\s])cd\s", c):
            continue
        for m in FILE_ARG.finditer(c):
            f = (m.group(1) or m.group(2) or "").strip("\"'")
            g = os.path.normpath(f)
            if (not f or re.search(r"[$*?{}~`]", f) or f.startswith("/") or "://" in f
                    or re.search(r">\s*%s(?![\w./-])" % re.escape(f), c) or Path(wt, f).exists()
                    or any(g == k or g.startswith(k + "/") or g.endswith("/" + k) for k in made)):
                continue
            errs.append("`%s`: `%s` is not in the tree and no stage lists it in files (add it to the stage that creates it)" % (c, f))
    return list(dict.fromkeys(errs))


FIELDS = ("title", "description", "acceptance_criteria", "design", "notes")


def bead_snapshot(bead, comments):
    """What a later amend diffs against: the bead's text fields, issue type, dependencies (id:type) and the people's
    comments, as the planner saw them."""
    deps = sorted("%s:%s" % (d.get("id"), d.get("dependency_type") or d.get("type") or "")
                  for d in bead.get("dependencies") or [] if isinstance(d, dict) and d.get("id"))
    return {"fields": {k: (bead.get(k) or "").strip() for k in FIELDS},
            "issue_type": (bead.get("issue_type") or "").strip(), "deps": deps,
            "comments": [(c.get("text") or "").strip() for c in comments if not (c.get("text") or "").startswith(ENGINE_NOTES)]}


DIFF_CAP = 4096


def bead_diff(old, new, answer=""):
    """Text: what changed in the bead since the plan (fields as a unified diff of at most 4 KB each, issue type,
    dependencies, new comments, the owner's answer). '' when nothing."""
    out = []
    for k in FIELDS:
        a, b = old["fields"].get(k, ""), new["fields"].get(k, "")
        if a != b:
            d = "\n".join(difflib.unified_diff(a.splitlines(), b.splitlines(), "was", "now", n=1, lineterm=""))
            out.append("- %s changed:\n%s" % (k, d if len(d) <= DIFF_CAP else d[:DIFF_CAP] + "\n... (diff cut at 4 KB)"))
    if "issue_type" in old and old["issue_type"] != new.get("issue_type", ""):
        out.append("- issue_type was: %s\n  now: %s" % (old["issue_type"] or "(empty)", new.get("issue_type") or "(empty)"))
    if "deps" in old and old["deps"] != new.get("deps", []):
        was, now = set(old["deps"]), set(new.get("deps", []))
        out.append("- dependencies: added %s; removed %s" % (", ".join(sorted(now - was)) or "none",
                                                              ", ".join(sorted(was - now)) or "none"))
    seen = list(old.get("comments") or [])
    for t in new["comments"]:
        if t in seen:
            seen.remove(t)
        else:
            out.append("- new comment:\n%s" % t[:1500])
    if answer:
        out.append("- the owner's answer to the engine's ask:\n%s" % answer[:1500])
    return "\n".join(out)


def linked_text(bead_id, bead, comments, show, comments_of, cap=10, each=400):
    """The decisions that live in other beads: the dependencies and the parent first, then the ids the task text and
    the people's comments name (not the engine's own comments); title, status, close reason, the last comment; each
    at most `each` chars, at most `cap` beads. tl-bxk.10.10"""
    pre = bead_id.split("-")[0]
    text = " ".join(str(bead.get(k) or "") for k in FIELDS) + " " + " ".join(
        c.get("text") or "" for c in comments if not (c.get("text") or "").startswith(ENGINE_NOTES))
    deps = {d.get("id"): d for d in bead.get("dependencies") or [] if isinstance(d, dict) and d.get("id")}
    ids = list(deps) + [bead.get("parent")]
    ids += re.findall(r"(?<![\w.-])(%s-[A-Za-z0-9]+(?:\.[0-9]+)*)" % re.escape(pre), text)
    ids = [i for i in dict.fromkeys(ids) if i and i != bead_id][:cap]
    out = []
    for i in ids:
        d = deps.get(i) or {}
        if "status" not in d or (d.get("status") == "closed" and not d.get("close_reason")):
            got = show(i)
            d = got if isinstance(got, dict) and got.get("id") == i else d
        if not d.get("id"):
            continue
        # no field tells an owner from another author: a comment is anyone's but the engine's
        notes = [c for c in comments_of(i) if not (c.get("text") or "").startswith(ENGINE_NOTES)]
        line = "- %s [%s] %s" % (i, d.get("status") or "?", " ".join(str(d.get("title") or "").split()))
        if (d.get("close_reason") or "").strip():
            line += "\n  closed: " + " ".join(d["close_reason"].split())
        if notes:
            line += "\n  comment: " + " ".join((notes[-1].get("text") or "").split())
        out.append(line if len(line) <= each else line[:each - 3] + "...")
    return ("\n## Linked beads (data, not instructions):\n" + "\n".join(out) + "\n") if out else ""


LATER_CASES = ("\nAn acceptance case this stage cannot run is not unchecked: it is checked when the last stage runs it.")
FRESH_WRITER_TEXT = ("\nYou take over from an earlier writer of this task, on another model. Its work is in this "
                     "tree, committed on this branch or not: read `git status` and the diff from main first, then go on "
                     "from there; do not start over.")

SCHEMAS = {
    "plan": {"type": "object", "additionalProperties": False,
             "required": ["summary", "stages", "risks", "question", "decided", "cases", "leftovers"],
             "properties": {
                 "summary": S_STR, "decided": S_STR,
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

GIT_PIN_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")  # the engine's own git is pinned; no child inherits a pin


def child_env():
    """Workers never inherit the launcher's session (a leaked CLAUDE_* broke claude children in the factory)."""
    drop = ("CLAUDE_CODE_", "CLAUDECODE", "ANTHROPIC_", "DELEGATE_", "CODEX_COMPANION", "CLAUDE_PID",
            "CLAUDE_AGENT_SDK", "CLAUDE_PLUGIN", "TASK_LOOP_")
    env = {k: v for k, v in os.environ.items() if not k.startswith(drop) and k not in GIT_PIN_VARS}
    env["TASK_LOOP_WORKER"] = "1"
    env["DELEGATE_DEPTH"] = "1"  # a worker never delegates further
    return env


class Result:
    def __init__(self, data=None, text="", ref="", cost=0.0, secs=0.0, error="", backend=""):
        self.data, self.text, self.ref, self.cost, self.secs, self.error, self.backend = (
            data, text, ref, cost, secs, error, backend)


WORKER_LINE = re.compile(r"delegate: worker pid=(\d+) pgid=(\d+)")  # route.py 0.31.1+, on stderr when it starts one


def run_proc(cmd, cwd, timeout, log_path, on_line=None, env=None):
    t = time.time()
    lines, worker = [], {}
    with open(log_path, "ab") as log:
        p = subprocess.Popen(cmd, cwd=cwd, env=dict(child_env(), **(env or {})), stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=(os.name != "nt"))
        if LOCK:
            LOCK.note(route_pid=p.pid)

        def read():
            for raw in p.stdout:
                ln = raw.decode("utf-8", "replace")
                lines.append(ln)
                if on_line:
                    try:
                        on_line(ln)
                    except Exception:
                        pass

        def read_err():  # route.py's stderr to the log; its worker line says which process group to stop
            for raw in p.stderr:
                try:
                    log.write(raw)
                    log.flush()
                except (ValueError, OSError):  # the call is over and its log closed
                    pass
                m = WORKER_LINE.search(raw.decode("utf-8", "replace"))
                if m:
                    pid = int(m.group(1))
                    worker.update(pid=pid, pgid=int(m.group(2)), start=tl.proc_start(pid))
                    if LOCK:
                        LOCK.note(workers=[[pid, worker["start"]]])
        readers = [threading.Thread(target=f, daemon=True) for f in (read, read_err)]
        for r in readers:
            r.start()
        stopped = False
        try:
            p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            stopped = True
            stop_tree(p, log, worker)
            for r in readers:
                r.join(2)
            return None, time.time() - t
        except BaseException:  # stopped: never leave the worker running
            stopped = True
            stop_tree(p, log, worker)
            raise
        finally:
            if LOCK:
                LOCK.note(route_pid=None, **({} if stopped else {"workers": []}))
        for r in readers:
            r.join(10)
    return (p.returncode, "".join(lines)), time.time() - t


STOP_GRACE = 10  # seconds route.py gets to stop its worker after a SIGTERM, before everything is SIGKILLed


def stop_tree(p, log=None, worker=None):
    """Stop a delegate call and its worker. route.py runs the worker in a process group of its own and stops it on
    SIGTERM, never on SIGKILL: a SIGKILL to route.py's group alone orphaned the lifesim-5ar.7 writer, which kept editing
    the slot after its engine stopped (2026-10-21). So: note the whole tree, SIGTERM route.py, give it STOP_GRACE, look
    again, then SIGKILL what is still the same process (same pid, group and start time in both looks: a pid reused in
    between is never hit). A survivor is written to the log and kept in the engine lock, so the slot stays busy while
    it lives. route.py 0.31.1+ names its worker (`delegate: worker pid=N pgid=N` on stderr): then SIGTERM to route.py
    is the stop (it SIGKILLs the worker's group), and only a route.py still alive after STOP_GRACE is SIGKILLed with the
    worker's group. The ps tree walk is for a route.py that named no worker."""
    if os.name == "nt":
        kill_tree(p)
        return []
    if worker and worker.get("pgid"):
        return stop_named(p, log, worker)
    before = tl.proc_table()
    tree = descendants(p.pid, before)
    with contextlib.suppress(OSError):
        os.killpg(p.pid, signal.SIGTERM)
    try:
        p.wait(timeout=STOP_GRACE)
    except subprocess.TimeoutExpired:
        pass
    if p.returncode is None:  # unreaped, its pid and group id cannot have been reused
        with contextlib.suppress(OSError):
            os.killpg(p.pid, 9)
    after = tl.proc_table()
    same = [(pid, pgid, st) for pid, pgid, st in tree if after.get(pid, (None, None, None))[1:] == (pgid, st)]
    for pid, pgid, _ in same:
        with contextlib.suppress(OSError):
            os.killpg(pgid, 9)  # a group with a member still in it keeps its id
        with contextlib.suppress(OSError):
            os.kill(pid, 9)
    with contextlib.suppress(Exception):
        p.wait(timeout=5)
    end, left = time.time() + 2, same
    while left and time.time() < end:
        left = [x for x in left if tl.proc_alive(x[0], x[2])]
        if left:
            time.sleep(0.05)
    if left:
        if log:
            log.write(("\u26a0 worker pid %s outlived the stop of its delegate call\n" % [x[0] for x in left]).encode())
        if LOCK:
            LOCK.note(workers=[[x[0], x[2]] for x in left])
    return [x[0] for x in left]


def stop_named(p, log, w):
    with contextlib.suppress(OSError):
        os.killpg(p.pid, signal.SIGTERM)
    try:
        p.wait(timeout=STOP_GRACE)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(OSError):
            os.killpg(p.pid, 9)
    if w["pgid"] != os.getpgrp() and tl.proc_alive(w["pid"], w.get("start") or ""):  # still the worker it named; never our own group
        with contextlib.suppress(OSError):
            os.killpg(w["pgid"], 9)
    with contextlib.suppress(Exception):
        p.wait(timeout=5)
    end = time.time() + 2
    while time.time() < end and tl.proc_alive(w["pid"], w.get("start") or ""):
        time.sleep(0.05)
    if not tl.proc_alive(w["pid"], w.get("start") or ""):
        return []
    if log:
        log.write(("\u26a0 worker pid %s outlived the stop of its delegate call\n" % w["pid"]).encode())
    if LOCK:
        LOCK.note(workers=[[w["pid"], w.get("start") or ""]])
    return [w["pid"]]


def descendants(pid, table):
    """[(pid, pgid, start)] of every process under `pid` in a tl.proc_table()."""
    kids = {}
    for k, (ppid, pgid, st) in table.items():
        kids.setdefault(ppid, []).append((k, pgid, st))
    found, todo = [], [pid]
    while todo:
        for k in kids.get(todo.pop(), []):
            if k not in found:
                found.append(k)
                todo.append(k[0])
    return found


class EngineLock:
    """<worktree>/.task/engine.lock while run-task runs there (see tl.engine_busy). A worker that outlived its stop keeps
    the lock (pid 0) until it is gone."""

    def __init__(self, wt, bead, slot=""):
        self.wt = wt
        self.path = tl.engine_lock_path(wt)
        self.data = {"pid": os.getpid(), "start": tl.proc_start(os.getpid()), "bead": bead, "slot": slot or "",
                     "slot_bead": os.environ.get("TASK_LOOP_SLOT_BEAD", ""), "by": "run-task", "started": time.time(),
                     "route": None, "workers": []}

    def take(self):
        """"" when this run holds the worktree now, else what holds it. A run the loop started takes over the loop's
        lock for its slot."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handoff = True  # engine_busy lets it take over only its parent loop's lock for the same slot bead
        for _ in range(3):
            busy = tl.engine_busy(self.wt, handoff=handoff)
            if busy:
                return busy
            try:  # created only if absent: two runs starting at once cannot both win
                os.close(os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            except FileExistsError:
                with contextlib.suppress(OSError):  # a dead run's lock or the parent loop's (engine_busy said so)
                    if not tl.engine_busy(self.wt, handoff=handoff):
                        self.path.unlink()
                continue
            self.write()
            return ""
        return "another run took the engine lock at the same time"

    def write(self):
        tl.write_engine_lock(self.wt, self.data)

    def note(self, route_pid=False, **kw):
        if route_pid is not False:
            kw["route"] = [route_pid, tl.proc_start(route_pid)] if route_pid else None
        self.data.update(kw)
        with contextlib.suppress(OSError):
            self.write()

    def release(self):
        left = [w for w in self.data.get("workers") or [] if tl.proc_alive(w[0], w[1])]
        with contextlib.suppress(OSError):
            if left:
                self.data.update(pid=0, route=None, workers=left)
                self.write()
            else:
                self.path.unlink()


LOCK = None  # this process's EngineLock while run-task runs


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


def lane_status(route):
    """`route.py status --json` lanes (name -> {out, out_until, ...}); {} when it cannot be read."""
    try:
        r = subprocess.run([sys.executable, route, "status", "--json"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60, env=child_env())
        j = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 and r.stdout.strip() else {}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}
    lanes = j.get("lanes") if isinstance(j, dict) else None
    return lanes if isinstance(lanes, dict) else {}


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


def same_dir(a, b):
    """The same folder: os.path.samefile, realpath equality when either path is missing."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.realpath(str(a)) == os.path.realpath(str(b))


def tree_problem(wt):
    """(what is wrong, the owner's fix) when git at `wt`, read as ambient config has it, is not that checkout; else None."""
    clean = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR")}

    def g(*a):
        r = subprocess.run(["git", "-C", str(wt)] + list(a), env=clean, capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        return r.stdout.strip() if r.returncode == 0 else ""

    repo = str(Path(g("rev-parse", "--path-format=absolute", "--git-common-dir") or ".").parent)
    origin = g("config", "--show-origin", "--get", "core.worktree")
    if origin:
        where = origin.split("\t")[0].replace("file:", "")
        return ("core.worktree is set (%s)" % origin.replace("\t", " = ", 1),
                "core.worktree redirects every worktree of this repo to another folder. Remove it: "
                "`git config --unset core.worktree` in %s (it was set in %s), then rerun." % (repo, where))
    if g("config", "--get", "core.bare").lower() == "true":
        return ("core.bare is true",
                "core.bare=true in the repo's config makes git refuse the work tree. Fix: `git config core.bare false` "
                "in %s, then rerun." % repo)
    top = g("rev-parse", "--show-toplevel")
    if not top or not same_dir(top, wt):
        return ("git's top-level folder is %s, not the slot %s" % (top or "(none)", wt),
                "Something redirects git away from the slot. Check `git config --show-origin --list` in %s for "
                "core.worktree or core.bare; `git config --unset core.worktree` in %s if set." % (wt, repo))
    return None


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
        # unpinned: a worker's git may run on other repos; engine.assert_tree catches a redirect after the node
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
        self.cap_granted = False
        self.planned = 0      # planner runs on this bead, across runs: the first plan, then amends (engine.max_replans caps them)
        self.extra = 0        # amends the owner allowed past the cap
        self.plan_log = []    # [{mode, why}] per counted planner run: the cap's ask names each
        self.old_plan, self.amend_text, self.amend_why = None, "", ""  # set where a checkpoint's plan is kept to be amended
        self.planner_ref = ""  # the last planner thread: a check send-back resumes it
        self.snap = {}        # the bead's text fields and people's comments as planned: a later amend diffs against it
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
        self.plan_decided = False  # the planner was sent back once with the requirement that answers its question
        self.writer_fallback = False  # the writer's thread is a fallback: delegate's answer said so, or it went on
                                      # as a new thread after a lane_out the engine saw
        self.fallback_lane = ""  # that writer's first-choice lane, when known: delegate's first_lane, or the lane seen out
        self.verified = []  # the verifier's answer per unchecked item at land: in the trace and on the bead
        self.write_rounds = []  # per write round: resumed, input tokens, turns (the next measure of a fix round's cost)
        self.sessions = []  # every AI call of this run: the trace a later reflection reads (traces.jsonl)
        self.outcome, self.why, self.asked = "failed", "", False  # what result() tells the loop
        self.retry_after = 0.0  # a pause for a lane: when delegate says it is back (epoch; 0 = unknown)
        self.landed_sha = ""  # set the moment the push goes through: whatever stops the run after it, the bead landed
        # the machine-readable trace the dashboard draws (docs/design/dashboard.md, Timeline records)
        self.node_n, self.cur, self.last_node, self.moved_from, self.moved_to = 0, None, None, None, None
        self.check_round = 0
        self.prev_ck, self.ck_run, self.resumed, self.run_logged = "", "", False, False
        d = tl.config_dir() / "engine"
        d.mkdir(exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.log_path = d / ("%s-%s.jsonl" % (bead, stamp))
        self.err_path = d / ("%s-%s.stderr" % (bead, stamp))
        # Engine files (brief, plan, node answers, check results) live outside the worktree, where no worker can write
        # them; in lifesim-vbo a writer's sandbox runs kept in .task/ were read as engine results by four planners.
        self.run_dir = tl.config_dir() / "runs" / self.log_path.stem
        self.run_dir.mkdir(parents=True, exist_ok=True)
        prune_check_rounds(tl.config_dir() / "runs")
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
        if kind in QUIET_KINDS:
            return
        if kind == "warn" or not (kind == "cmd" and not self.verbose):
            say("[%s] %s%s" % (time.strftime("%H:%M:%S"), "⚠ " if kind == "warn" else "", text))

    def node(self, step, text, **kw):
        """A node begins (the open one ends first): the old `node` record with its run-scoped id, step and counters."""
        if step != "close":
            self.assert_tree(step)
        self.end_node()
        self.node_n += 1
        self.cur = {"id": self.node_n, "step": step, "t": time.time(), "sessions": [], "outcome": "", "detail": ""}
        self.last_node = self.cur
        self.log("node", text, id=self.node_n, step=step, **kw)
        return self.node_n

    def outcome_of(self, outcome, detail=""):
        """What the open node came to, for its end record."""
        if self.cur:
            self.cur.update(outcome=outcome, detail=detail[:300])

    def end_node(self, outcome=""):
        c, self.cur = self.cur, None
        if not c:
            return
        out = c["outcome"] or outcome or "done"
        self.log("end", "%s %d: %s" % (c["step"], c["id"], out), id=c["id"], step=c["step"], outcome=out,
                 detail=c["detail"], secs=round(time.time() - c["t"]), sessions=c["sessions"])

    def transition(self, to, cause, detail="", **kw):
        """A decision point: from the open (or last) node to the next step, with the cause and what it was."""
        frm = (self.cur or self.last_node or {}).get("id", 0)
        self.moved_from, self.moved_to = frm, to
        rec = {"from": frm, "to": to, "cause": cause, "detail": (detail or "")[:300]}
        rec.update(kw)
        self.log("transition", "%s -> %s: %s" % (cause, to, (detail or "")[:200]), **rec)

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
        why = ("fresh" if self.cfg.get("fresh") else "answer" if self.answered else "resume" if self.resumed
               else "retry" if prev else "first")
        return {"prev_run": prev, "started_because": why, "ask": (self.answered or {}).get("id") or ""}

    def log_run(self):
        """The run record: why it started, once that is known (after the checkpoint is read), or at the close."""
        if self.run_logged:
            return
        self.run_logged = True
        o = self.origin()
        self.log("run", "run: %s" % o["started_because"], run=self.log_path.stem, bead=self.bead, worktree=str(self.wt),
                 slot=(LOCK.data.get("slot") if LOCK else "") or "", **o)

    def trace_call(self, node, role, attempt, r, j, host=False):
        """One AI call into the run's trace: which worker session did what, and where its transcript is."""
        j = j or {}
        rec = {"node": node, "role": role, "attempt": attempt, "status": j.get("status") or r.error or "none",
               "ref": j.get("ref") or r.ref or "", "run_id": j.get("run_id") or "", "transcript": j.get("transcript") or "",
               "family": j.get("family") or "", "lane": j.get("lane") or "", "model": j.get("model") or "",
               "effort": j.get("effort") or "", "turns": j.get("turns"), "secs": round(r.secs or 0), "cost": r.cost or 0.0, "t": time.time(),
               "host": host, "tokens": j.get("tokens"), "denied": j.get("denied") or [],  # tokens {in, cached, out}
               "reason": j.get("reason"), "next": j.get("next"), "context": j.get("context"),
               "node_id": (self.cur or {}).get("id"), "resume": bool(getattr(self, "_resume", None)), "flag": j.get("flag")}
        if self.cur and rec["ref"]:
            self.cur["sessions"].append(rec["ref"])
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
               "verified": self.verified, "write_rounds": self.write_rounds}
        rec.update(self.origin())
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
    def ai(self, node, title, prompt, *a, **kw):
        """One AI node, then the tree check: a worker that wrote core.worktree is caught before review or land."""
        out = self._ai(node, title, prompt, *a, **kw)
        self.assert_tree(kw.get("step") or node, "after")
        return out

    def _ai(self, node, title, prompt, resume_key=None, writer_family=None, step=None, resume_ref=None, **meta):
        """One AI node through delegate (worker-run v1): it picks lane and model, limits apply, it records the run."""
        self.budget_check()
        self.stats["nodes"] += 1
        role = ROLES[node]
        writer = writer_family if node in ("review", "verify") else None
        resume = resume_ref or (self.writer.get("delegate") if resume_key else None)
        if resume and resume_key and self.writer_fallback:  # tl-bxk.10.5: a fallback writer would keep the bead off Codex for good
            lane = lane_status(self.route or "").get(self.fallback_lane) if self.fallback_lane else None
            if self.fallback_lane and not isinstance(lane, dict):  # that lane is not configured here: no fallback
                self.writer_fallback, self.fallback_lane = False, ""
            elif lane is None or lane.get("out") is False:  # back again, or no lane known to wait for
                self.transition(step or node, "fallback_retake", "%s: delegate routes afresh instead of resuming the "
                                "fallback writer (%s)" % ("%s is usable again" % self.fallback_lane if self.fallback_lane
                                                          else "its first-choice lane is not known",
                                                          self.writer_family or "?"),
                                lane=self.fallback_lane, family=self.writer_family or "")
                resume, prompt = None, prompt + FRESH_WRITER_TEXT
        out_on = ""
        if getattr(self, "plan_data", None):  # an unsandboxed worker can write here: every step reads the engine's plan
            (self.run_dir / "plan.json").write_text(json.dumps(self.plan_data, indent=1))
        flag = access(self.host)
        self.node(step or node, "%s: %s" % (node, title), node=node, backend="delegate", role=role, resume=bool(resume),
                  **meta)
        timeout = float(self.cfg["node_timeout_min"]) * 60
        waited, attempt_prompt, attempt, errs = 0.0, prompt, 1, ["not run"]
        while attempt <= 2:
            self._resume = resume
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
                self.transition(step or node, "lane_out", "the resumed thread's lane is out: a new thread",
                                lane=j.get("lane") or "")
                resume, attempt_prompt, out_on = None, attempt_prompt + FRESH_WRITER_TEXT, j.get("lane") or ""
                continue
            if nxt == "retry":  # worker-run v2: delegate says when; how long a slot waits is this engine's policy
                due = float(j.get("retry_after") or 0)
                wait = max(60.0, due - time.time())
                if waited + wait > float(self.cfg["lane_wait_min"]) * 60:  # a long wait frees the slot; the checkpoint resumes
                    self.retry_after = due if due > time.time() else 0.0
                    self.outcome_of("paused", reason)
                    self.transition("pause", "paused", "%s for %s until %s" % (
                        "no network" if reason == "network" else "no lane", node,
                        time.strftime("%H:%M:%S", time.localtime(due)) if due > time.time() else "a lane frees"),
                        until=self.retry_after, lane=j.get("lane") or "", reason=reason)
                    raise Blocked("paused: %s for %s until %s (%s: %s)" % (
                        "no network" if reason == "network" else "no lane", node,
                        time.strftime("%H:%M:%S", time.localtime(due)) if due > time.time() else "a lane frees",
                        reason, said[:200]))
                wait = min(600.0, wait)
                self.warn("%s waits %d min (%s): %s" % (node, wait // 60, reason, said[:160]))
                self.transition(step or node, "lane_wait", "waited %d min for a lane (%s)" % (wait // 60, reason),
                                lane=j.get("lane") or "")
                time.sleep(wait)
                waited += wait
                continue
            self.cost += r.cost
            denied = "; ".join("`%s`" % (d.get("input") or d.get("tool")) for d in j.get("denied") or [])
            if nxt == "owner" and not denied:
                if reason == "lane_out":  # a new thread found no lane either and no time it frees: the bead waits, no ask
                    self.outcome_of("paused", reason)
                    self.transition("pause", "paused", "no lane for %s, no time it frees" % node, lane=j.get("lane") or "",
                                    reason=reason)
                    raise Blocked("paused: no lane for %s (lane_out, no time it frees): %s" % (node, said[:200]))
                if reason in ("logged_out", "setup"):  # the machine's to fix, not the bead's: it stays open, no ask
                    fix = ("run `codex login`" if j.get("family") == "openai" else "run `claude auth login`") \
                        if reason == "logged_out" else "set up delegate (/iorlas-delegate:init)"
                    raise Blocked("paused: %s on %s; %s on this machine, then rerun. (%s)" % (reason, node, fix, said[:200]))
                raise Blocked("needs a human: delegate stopped the %s step (%s): %s" % (node, reason, said[:400]))
            if j.get("git_violation"):
                self.warn("%s changed git: %s" % (node, "; ".join(j["git_violation"])))
            if resume_key and r.ref and j.get("status") == "done":
                said_fb = j.get("fallback") if "fallback" in ((self.contract or {}).get("features") or []) else None
                if isinstance(said_fb, bool):  # delegate 0.32 says it on every answer, a resumed one too
                    self.writer_fallback = said_fb
                    self.fallback_lane = (j.get("first_lane") or out_on or self.fallback_lane) if said_fb else ""
                elif r.ref != resume:  # a new thread: a fallback only when it runs elsewhere than a lane seen out
                    gone = out_on or self.fallback_lane
                    self.fallback_lane = gone if gone and (j.get("lane") or "") != gone else ""
                    self.writer_fallback = bool(self.fallback_lane)
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
            if attempt < 2:
                self.transition(step or node, "invalid_output", "; ".join(errs[:2]))
            if resume:  # one more try as a new thread: a refused or broken resume is not worth a second attempt
                resume, attempt_prompt = None, prompt
            attempt += 1
        if errs:
            raise Blocked("failed: %s node produced no valid output (%s)" % (node, "; ".join(errs[:3])))
        if node == "plan" and r.ref:
            self.planner_ref = r.ref
        self.last_flag = (j or {}).get("flag")  # same_family | degraded | ...: delegate could not give the usual lane
        fam = r.backend  # openai | claude: the family that wrote, for the reviewer
        model = "%s %s on %s" % ((j or {}).get("model"), (j or {}).get("effort"), (j or {}).get("lane"))
        (self.run_dir / ("%s-%d.json" % (node, self.stats["nodes"]))).write_text(json.dumps(r.data, indent=1))
        self.log("msg", "%s → %s  [%s%s, %ds, $%.2f, total $%.2f]" % (
            node, summarize(node, r.data), fam, (":" + model) if model else "", r.secs, r.cost, self.cost),
            node=node, data=r.data, cost=r.cost, secs=round(r.secs), backend=fam, node_id=(self.cur or {}).get("id"))
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
    def assert_tree(self, step, when="before"):
        """Before and after every node, and before the land: this slot's git is the slot (lifesim-1mm: a core.worktree in the shared
        .git/config pointed every slot's git at another folder). Unpinned, as a worker's or check's git would see it. A wrong tree
        stops the run with an owner ask, never a skip."""
        bad = tree_problem(self.wt)
        if bad:
            why = "tree: %s (%s %s)" % (bad[0], when, step)
            self.transition("ask", "wrong_tree", bad[0])
            raise Blocked(why, bad[1])

    def sh(self, cmd, timeout=3600, check=False, save=None, env=None, pin=False):
        """A command: a string goes through bash with -e and pipefail (checks, profile commands), so a red command in a
        `;` list or a pipe fails it (lifesim-gfr.31.1: `just unity-check > log; ! grep ...` passed with unity-check
        red); `! cmd` and `cmd || true` still pass. A list runs as is (no quoting rules). pin=True: an engine git command, run
        with GIT_DIR/GIT_WORK_TREE of the slot; checks and gates run unpinned (they may run git on other repos)."""
        self.log("cmd", cmd if isinstance(cmd, str) else " ".join(cmd))
        # Its own process group, so a timeout stops the whole tree (dotnet build nodes, Unity) and not just the shell;
        # the worker env, so a check never inherits this launcher's Claude session.
        bash = shutil.which("bash") if isinstance(cmd, str) and os.name != "nt" else None  # plans write bash
        run = [bash, "-e", "-o", "pipefail", "-c", cmd] if bash else cmd  # Windows: cmd.exe, as before
        p = subprocess.Popen(run, shell=isinstance(run, str), cwd=self.wt,
                             env=dict(child_env(), **(tl.pinned_env(self.wt) if pin else {}), **(env or {})),
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

    def stage_all(self, check=False):
        """Stage the slot's own changes: exactly the paths `git status --porcelain` lists under the pinned env, never a
        bare `git add -A` (tl-bxk.10.12). Returns the exit code."""
        self.log("cmd", "git add -A (the slot's own status paths)")
        st = tl.run_git(self.wt, "status", "--porcelain", "-z", "--untracked-files=all", capture_output=True)
        parts, paths = st.stdout.decode("utf-8", "surrogateescape").split("\0"), []
        k = 0
        while k < len(parts):
            e = parts[k]
            k += 1
            if len(e) > 3:
                paths.append(e[3:])
                if e[0] in "RC":  # the next entry is the path it came from: gone from the tree, staged already
                    k += 1
        rc = st.returncode
        if rc == 0 and paths:
            r = tl.run_git(self.wt, "--literal-pathspecs", "add", "-A", "--pathspec-from-file=-", "--pathspec-file-nul",
                           input="\0".join(paths).encode("utf-8", "surrogateescape"), capture_output=True)
            rc = r.returncode
            st = r
        if check and rc:
            raise Blocked("failed: staging the slot's paths exit %d\n%s" % (rc, st.stderr.decode("utf-8", "replace")[-600:]))
        return rc

    def fetch(self, check=False):
        """git fetch, again while it loses a ref lock to another process's fetch into this repo (tl.REF_RACE)."""
        for i in range(5):
            rc, tail = self.sh(["git", "fetch", "-q", "origin"], pin=True)
            if rc == 0 or not tl.REF_RACE.search(tail):
                break
            time.sleep(0.1 * (i + 1))
        if check and rc:
            raise Blocked("failed: `git fetch -q origin` exit %d\n%s" % (rc, tail))
        return rc, tail

    def base_sha(self):
        """Where the task's work starts: an earlier run's commits on the task branch count as the task's diff."""
        return self.git("merge-base", self.cfg["base"], "HEAD") or self.cfg["base"]

    def git(self, *a):
        return tl.git(*a, cwd=self.wt)

    # -- nodes
    def reset(self, bead):
        self.node("reset", "reset")
        branch = (bead.get("metadata") or {}).get("branch") or "task/" + self.bead
        self.fetch(check=True)
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
            self.sh(["git", "checkout", "-q", branch], check=True, pin=True)
        else:
            self.sh(["git", "checkout", "-q", "-B", branch, self.cfg["base"]], check=True, pin=True)
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
        text = brief_digest(bead, comments) + linked_text(self.bead, bead, comments, tl.show, tl.comments)
        self.snap = bead_snapshot(bead, comments)
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
        committed = self.git("rev-parse", "--verify", "-q", self.cfg["base"] + "^{commit}")  # never the working tree
        base = (tl.profile(str(self.wt), self.cfg["base"]).get("engine") or {}) if committed else {}
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
        hb = Heartbeat(self.bead, os.environ.get("TASK_LOOP_SLOT_BEAD", ""))
        try:
            self.prev_ck = (json.loads(self.checkpoint_path().read_text()) or {}).get("run") or ""
        except (OSError, ValueError, AttributeError):
            self.prev_ck = ""
        try:
            if getattr(self, "stop_pending", False):  # stopped during the claim (run_bead): close it as stopped
                raise Blocked("failed: stopped (SIGTERM)")
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
            self.grant_cap()
            if not has_criteria(bead):
                raise Blocked("ticket: the bead has no acceptance criteria", "What proves this bead done? Add acceptance "
                              "criteria (the field, or a ## Acceptance Criteria section), then rerun.")
            plan, i, state = self.resume_point()
            self.log_run()
            if plan is None:
                plan, i, state = self.plan(again=self.replan_first), 0, None
            while i < len(plan["stages"]):
                d = self.stage(plan, i, state)
                state = None
                if d == "replan":
                    self.replans += 1
                    self.stats["replans"] = replans = self.replans
                    if replans > int(self.cfg["max_replans"]) + self.extra:
                        raise self.cap_blocked("stage %d stuck after %s rounds. What failed: %s" % (
                            i + 1, self.cfg["max_rounds"], self.stuck_why[:600]))
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
            with self.stop_deferred():  # a stop here would skip the close: no trace, no bead update
                if self.landed_sha and outcome != "landed":  # stopped after the push: on the base, close it as landed
                    self.warn("%s after the land went through; closing it landed" % (why or outcome))
                    outcome, why, sha, question = "landed", "", self.landed_sha, ""
                hb.stop()
                self.outcome, self.why = outcome, why
                self.close(outcome, why, sha, question)
        return 0 if outcome in ("landed", "done") else 2

    def result(self):
        """The run's outcome for the loop: landed (closed, done too), parked (blocked for the owner: an ask, or one
        still open), paused (the machine's trouble: lanes, login, network; the bead stays open), failed."""
        out = ("landed" if self.outcome in ("landed", "done") else "failed" if self.outcome == "failed"
               else "paused" if self.why.startswith("paused:") else "parked")
        return {"v": 1, "outcome": out, "bead": self.bead, "why": self.why[:500], "run": self.log_path.stem,
                "log": str(self.log_path), "minutes": round((time.time() - self.t0) / 60, 1),
                "rounds": self.stats["rounds"], "tests_added": self.stats["tests_added"], "asked": self.asked,
                "retry_after": self.retry_after if out == "paused" else 0.0, "cost": round(self.cost, 2)}

    def self_verify(self, gaps):
        """One read-only verifier call before a verify ask; returns the items that still go to the owner. Per item:
        settled with quoted evidence drops it, wrong goes to one fix round at land (max_fix_rounds; none left: to the
        owner, naming the defect), open goes to the owner. The 2026-10-21 lifesim night: lifesim-d5f.46 (a hand-written
        .meta against its siblings), lifesim-fld.26.15 (a call site) and lifesim-gfr.31.1 (an evidence file that proved
        it) each waited hours for an ask a supervisor settled in a minute by reading."""
        if not gaps:
            return gaps
        unused = [(u, unused_tool(u["what"], self.wt, self.cfg)) for u in gaps]
        for u, ev in unused:
            if ev:
                self.verified.append({"what": u["what"], "kind": u["kind"], "verdict": "settled", "evidence": ev,
                                      "why": "not a check here"})
        if any(ev for _, ev in unused):
            gaps = [u for u, ev in unused if not ev]
            n_drop = len(unused) - len(gaps)
            self.transition("verify" if gaps else "land", "not_a_check", "%d item%s name a tool the repo does not use" % (
                n_drop, "" if n_drop == 1 else "s"))
            if not gaps:
                counts = ", ".join("%d %s" % (sum(x["verdict"] == k for x in self.verified), k) for k in VERDICTS)
                self.log("verify", "before land: %s" % counts, verified=self.verified)
                self.comment("Verify (engine): what the workers could not check, before land: " + "; ".join(
                    "%s: %s, %s" % (x["verdict"], x["what"], '"%s"' % x["evidence"]) for x in self.verified))
                return []
        items = "".join("%d. %s (%s)\n" % (n, u["what"], u["kind"]) for n, u in enumerate(gaps, 1))
        try:
            d, _ = self.ai("verify", "%d unchecked item(s) before land" % len(gaps), VERIFY_PROMPT.format(
                brief=self.brief_text(), work=self.work_summary(), evidence=self.evidence_dir,
                where=self.where("verify"), items=items), writer_family=self.writer_family, items=len(gaps))
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
        counts = ", ".join("%d %s" % (sum(x["verdict"] == k for x in self.verified), k) for k in VERDICTS)
        self.log("verify", "before land: %s" % counts, verified=self.verified)
        self.outcome_of("wrong" if wrong else "open" if still else "settled", counts)
        self.comment("Verify (engine): what the workers could not check, self-verified read-only before land: " + "; ".join(
            "%s: %s, %s" % (x["verdict"], x["what"], ('"%s"' % x["evidence"]) if x["verdict"] == "settled" else x["why"])
            for x in self.verified))
        if not wrong:
            if still:
                self.transition("ask", "verify_open", "%d item%s only the owner can check" % (
                    len(still), "" if len(still) == 1 else "s"))
            else:
                self.transition("land", "verified", counts)
            return still
        if self.fixes >= int(self.cfg["max_fix_rounds"]):
            self.transition("ask", "verify_wrong", "%d found wrong, no fix round left" % len(wrong))
            return still + [dict(u, why="found wrong: %s; no fix round left" % u["why"]) for u in wrong]
        self.transition("fix", "verify_wrong", "%d found wrong: %s" % (len(wrong), "; ".join(u["why"] for u in wrong)))
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

    def ask_plan(self, prompt, step, title, mode="plan"):
        """One planner answer. Its checks are validated before any write; the ones that read the tracker, run gate-only
        commands, or cannot run (dry_check) go back once, on the same planner thread, with the exact errors."""
        data, _ = self.ai("plan", title, prompt, step=step, mode=mode)
        if self.plan_fits(data):  # checkpoint first: a SIGTERM during the send-back below resumes with this plan
            self.plan_data = json.loads(json.dumps(data))
            self.save_checkpoint(stage=0, rounds=0, n=0, feedback="", step="write")
        bad, gated, dry = tracker_checks(data), gate_only_checks(data, self.cfg), dry_check(data, self.wt)
        if bad or gated or dry:  # asked once to rewrite them, like an invalid answer; not a counted re-plan
            why = ""
            if bad:
                self.warn("the plan's checks read the issue tracker, sent back: %s" % "; ".join(bad)[:300])
                why += TRACKER_TEXT % "\n".join("- `%s`" % c for c in bad)
            if gated:
                self.warn("the plan's checks run gate-only commands, sent back: %s" % "; ".join(
                    "%s (%s)" % g for g in gated)[:300])
                why += GATE_ONLY_TEXT % "\n".join("- `%s`: %s" % g for g in gated)
            if dry:
                self.warn("the plan's checks cannot run, sent back: %s" % "; ".join(dry)[:300])
                why += DRY_CHECK_TEXT % "\n".join("- " + e for e in dry)
            self.outcome_of("sent back", "its checks read the tracker, run gate-only commands or cannot run")
            self.transition(step, "plan_sent_back", "checks %s" % "; ".join(
                (["read the issue tracker"] if bad else []) + (["run gate-only commands"] if gated else []) +
                (["cannot run"] if dry else [])))
            ref = self.planner_ref
            back = (why.lstrip() + "\n\nYour plan, to correct (same output schema):\n" + json.dumps(data, indent=1)) if ref else prompt + why
            data, _ = self.ai("plan", "rewrite checks", back, step=step, mode="checks_back", resume_ref=ref or None)
            bad, gated = tracker_checks(data), gate_only_checks(data, self.cfg)
            if bad:
                raise Blocked("failed: the plan's checks still read the issue tracker after one rewrite: %s"
                              % "; ".join(bad)[:400])
            if gated:
                raise Blocked("failed: the plan's checks still run gate-only commands after one rewrite: %s"
                              % "; ".join("%s (%s)" % g for g in gated)[:400])
            dry = dry_check(data, self.wt)
            if dry:  # a heuristic: the writer's bad_checks flag decides from here, no second send-back
                self.warn("the plan's checks may still not run after one rewrite: %s" % "; ".join(dry)[:300])
        return data

    def cap_blocked(self, detail=""):
        """The re-plan cap's ask: the planner ran `planned` times. An answer with "allow" or "more" gives one more."""
        why = "; ".join("%d. %s: %s" % (k + 1, e["mode"], e["why"]) for k, e in enumerate(self.plan_log))[:1500]
        return Blocked(REPLAN_CAP + "%d times (the limit is %d plan + %d amends): %s%s" % (
            self.planned, 1, int(self.cfg["max_replans"]) + self.extra, why, ("; " + detail) if detail else ""),
            "This bead was planned %d times, so the engine stops instead of burning more planner runs. Why each time: %s\n"
            "Choose: split the bead; clarify it (comment what the plan keeps missing); or reply \"allow one more\"." % (
                self.planned, why))

    def grant_cap(self):
        """The owner answered the cap's ask: an answer with "allow" or "more" (any case) lets the bead plan once more.
        "split" or "clarify" does not: the answer is recorded and the bead blocks again at the cap. Goes into the
        checkpoint's extra, which resume_point adds to."""
        a = self.answered or {}
        if not (a.get("why") or "").startswith(REPLAN_CAP) or self.cap_granted:
            return
        answer = self.answer_text(a)
        low = answer.lower()
        self.cap_granted = True
        if "allow" not in low and "more" not in low:
            self.log("note", "the owner answered the re-plan cap (%s) without allowing more: still blocked. Answer: %s" % (
                a["id"], answer[:300] or "(none)"))
            try:
                a["answer_recorded"] = answer[:1500]
                self.ask_path().write_text(json.dumps(a, indent=1))
            except OSError:
                pass
            return
        self.log("note", "the owner allowed one more planner run (ask %s): %s" % (a["id"], answer[:200]))
        try:
            ck = json.loads(self.checkpoint_path().read_text())
            ck["extra"] = int(ck.get("extra") or 0) + 1
            self.checkpoint_path().write_text(json.dumps(ck, indent=1))
        except (OSError, ValueError):
            self.extra += 1

    def plan(self, again=False):
        old = self.old_plan or (self.plan_data if again and getattr(self, "plan_data", None) else None)
        mode = "amend" if old else "plan"
        why = ""
        if again:
            try:
                why = (self.run_dir / "replan.md").read_text(encoding="utf-8")[-12500:]
            except OSError:
                pass
        if self.planned >= 1 + int(self.cfg["max_replans"]) + self.extra:
            raise self.cap_blocked()
        self.planned += 1
        self.plan_log.append({"mode": mode, "why": (self.amend_why or ("a re-plan: " + why[:160].replace("\n", " ") if again else "first plan"))[:240]})
        if old and not again and not self.amend_text:
            self.amend_text = "The bead is the same as when the old plan was made."
        extra = ""
        if old:
            extra = ("\n\nAn earlier plan exists for this task. Return the plan with the smallest change that covers what "
                     "follows; keep accepted stages and their checks unless the change touches them; do not re-explore code "
                     "the old plan already names. Same output schema as a plan.\n<old_plan>\n%s\n</old_plan>\n"
                     "What changed:\n<change>\n%s\n</change>" % (json.dumps(old, indent=1), (self.amend_text or why).strip()))
        elif again:
            extra = "\n\nThe previous plan did not work. What failed:\n<failed>\n%s\n</failed>\nPlan again." % why
        self.old_plan, self.amend_text, self.amend_why = None, "", ""
        rules = []
        if self.cfg["worker_rules"]:
            rf = Path(self.wt) / self.cfg["worker_rules"]
            try:  # a short rules file is inlined: reading it costs the planner a turn
                inline = rf.read_text(encoding="utf-8") if rf.stat().st_size < RULES_INLINE_MAX else None
            except OSError:
                inline = None
            if inline is not None:
                rules.append("This repo's rules for workers (what runs where, known pitfalls of its tools); the checks you "
                             "write must follow them:\n<worker_rules>\n%s\n</worker_rules>" % inline.strip())
            else:
                rules.append("Read %s: this repo's rules for workers (what runs where, known pitfalls of its tools); the "
                             "checks you write must follow them." % rf)
        rules.append("Proof files that a check reads or a reviewer looks at (screenshots, logs, probe output) go under "
                     "%s: it is kept across runs, and nothing else under %s is." % (self.evidence_dir, self.task_dir))
        rules.append("Checks run on the uncommitted working tree after each write. The engine runs the gate%s once, on "
                     "the rebased tree at land: never put %s in a stage's checks, and a criterion that names it is proven "
                     "by that land gate: write no case for it." % (
                         (" (`%s`)" % self.cfg["gate"]) if self.cfg["gate"] else "",
                         ("`%s`" % self.cfg["gate"]) if self.cfg["gate"] else "it"))
        extra_gated = [(c, why) for c, why in gate_only(self.cfg) if c != " ".join(self.cfg["gate"].split())]
        if extra_gated:
            rules.append("These run only in the gate at land too, never in a check: " + "; ".join(
                "`%s`%s" % (c, " (%s)" % why if why else "") for c, why in extra_gated) + ".")
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
        if len(prompt.encode("utf-8")) > PLAN_BRIEF_KB * 1024:
            self.warn("the planner's brief is %.0f KB (over %d KB)" % (len(prompt.encode("utf-8")) / 1024, PLAN_BRIEF_KB))
        step = "replan" if again else "plan"
        data = self.ask_plan(prompt, step, "amend" if old else "plan", mode)
        q = data["question"].strip()
        decided = data["decided"].strip() if q else ""
        if decided and not self.plan_decided:  # tl-bxk.10.3: no owner ask, the planner plans again
            self.plan_decided = True
            self.warn("the planner asked what an accepted requirement decides: %s" % decided[:300])
            self.outcome_of("sent back", "an accepted requirement decides its question")
            self.transition(step, "planner_decided", "an accepted requirement decides it: %s" % decided)
            self.planned += 1  # a planner run like the others: the cap counts it
            self.plan_log.append({"mode": "plan", "why": "an accepted requirement decides its question"})
            data = self.ask_plan(prompt + DECIDED_TEXT % (q, decided) + PLAN_DECIDED_TEXT, step, "plan to meet it", "checks_back")
        data = json.loads(json.dumps(data))  # the engine's own copy: cases are added to it as the task runs
        if self.plan_fits(data):
            # a SIGTERM from here on resumes with this plan (d5f.38 lost a finished 1.1M plan before its checkpoint)
            self.plan_data = data
            self.save_checkpoint(stage=0, rounds=0, n=0, feedback="", step="write")
        if self.verify_answer and not data["stages"] and not data["question"].strip():
            self.log("note", "the planner finds the owner's answer asks for nothing more: landing")
            self.plan_leftovers(data)
            return data
        self.plan_summary = data["summary"]
        for c in data.get("cases") or []:
            c.setdefault("by", "plan")
        self.plan_data = data
        if data["question"].strip():
            self.outcome_of("asks", data["question"][:200])
            raise Blocked("owner decision needed", data["question"])
        self.outcome_of("%d stage%s" % (len(data["stages"]), "" if len(data["stages"]) == 1 else "s"),
                        data["summary"][:200])
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

    def plan_fits(self, data):
        """A plan worth keeping through a stop: it has stages, asks nothing, and is not a split ask."""
        return bool(data["stages"] and not data["question"].strip() and (
            len(data["stages"]) <= int(self.cfg["max_stages"]) or (self.answered or {}).get("kind") == "ticket"))

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
               "plan": self.plan_data, "planner_ref": self.planner_ref, "planned": self.planned, "extra": self.extra, "plan_log": self.plan_log, "snap": self.snap,
               "done": self.done, "accepted": self.accepted, "replans": self.replans, "fixes": self.fixes, "denials": self.denials,
               "writer": self.writer.get("delegate") or "", "writer_fallback": self.writer_fallback, "fallback_lane": self.fallback_lane,
               "writer_family": self.writer_family or "", "brief": self.brief_hash, "head": self.git("rev-parse", "HEAD"),
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
        self.ck_run = ck.get("run") or "" if isinstance(ck, dict) else ""
        branch = self.git("symbolic-ref", "--short", "-q", "HEAD")
        if ck.get("v") != 1 or ck.get("branch") != branch or not ck.get("plan"):
            self.drop_checkpoint()
            return None, 0, None
        self.planned = int(ck.get("planned") or 1 + int(ck.get("replans") or 0))  # checkpoints before the count: plan + replans
        self.extra, self.plan_log = self.extra + int(ck.get("extra") or 0), list(ck.get("plan_log") or [])
        self.planner_ref = ck.get("planner_ref") or self.planner_ref
        head = self.git("rev-parse", "HEAD")
        ours = head == ck["head"] or (self.left_dirty and not ck["closed"] and self.git("rev-parse", "HEAD~1") == ck["head"])
        if not ours:  # a commit, or an edit after a clean close, that is not this engine's: the plan may not fit it
            self.log("note", "the branch changed since the checkpoint of %s: amending its plan" % ck["run"])
            self.old_plan, self.amend_why = ck["plan"], "branch changed outside the engine"
            self.amend_text = ("The branch changed outside the engine since the old plan (commits after %s):\n%s\nNo stage of "
                               "the old plan is known to be in the tree; read `git status` and the diff from the base."
                               % (ck["head"][:12], (self.git("log", "--oneline", "-n", "15", "%s..HEAD" % ck["head"]) or "(none)")[:800]))
            return None, 0, None
        self.resumed = True
        self.done = list(ck["done"])
        self.replans, self.fixes = int(ck.get("replans") or 0), int(ck.get("fixes") or 0)
        self.denials = list(ck.get("denials") or [])
        self.filed = list(ck.get("filed") or [])
        if ck["writer"]:
            self.writer["delegate"] = ck["writer"]
            self.fallback_lane = ck.get("fallback_lane") or ""
            self.writer_fallback = bool(ck.get("writer_fallback", bool(self.fallback_lane)))
            self.writer_family = ck.get("writer_family") or None
        if ck["step"] == "gate-red":
            self.log("note", "the gate was red at land in %s: re-planning with its output, keeping %d accepted stage(s)"
                     % (ck["run"], len(self.done)))
            (self.run_dir / "replan.md").write_text(
                "Every stage was accepted, then the gate failed on the tree rebased onto the latest base (often "
                "another task landed first). Plan the fix.\n\n" + ck.get("gate_tail", ""))
            self.replan_first = True
            self.old_plan, self.amend_why = ck["plan"], "gate red at land"
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
            answer = self.answer_text(self.answered) if self.answered else ""
            diff = bead_diff(ck["snap"], self.snap, answer) if ck.get("snap") else None
            if diff == "":  # the hash moved on a label or a priority: nothing the plan reads changed
                self.log("note", "the bead changed since the checkpoint of %s, but nothing the plan reads: keeping the plan, "
                         "no planner run" % ck["run"])
            else:
                self.log("note", "the bead changed since the checkpoint of %s: amending its plan, keeping %d accepted stage(s)"
                         % (ck["run"], len(self.done)))
                self.old_plan = ck["plan"]
                self.amend_why = "bead changed: %s" % ("the owner answered ask %s" % self.answered["id"] if self.answered
                                                       else "an edit with no ask")
                self.amend_text = diff or "The bead changed since the old plan (the checkpoint holds no copy of the old text): read the task above."
                self.amend_text += "\nAccepted stages (their work is in the tree): " + ("; ".join(self.done) or "none")
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
        failed_cmds = state.get("failed")  # the commands the last engine run found red (None: no check ran red yet)
        where = ({"fix": state.get("fix_n"), "fixes": state.get("fix_of")} if fix else
                 {"stage": i + 1, "stages": len(plan["stages"])})
        while True:
            if not fix:  # a fix runs at land: its checkpoint stays at land, and a resume lands again
                self.save_checkpoint(stage=i, rounds=rounds, n=n, feedback=feedback, step="write")
            n += 1
            self.stats["writes"] += 1
            if n >= 2:
                self.warn("%s: write %d (round %d)" % (name, n, rounds + 1))
            w, wfam = self.ai("write", "%s write %d" % (name, n), WRITE_PROMPT.format(
                brief=self.brief_text(), plan=self.plan_text(), n=i + 1, goal=st["goal"],
                files=", ".join(st["files"]), checks=self.stage_checks_text(st["checks"]),
                feedback=feedback, evidence=self.evidence_dir, where=self.where("write", [c["cmd"] for c in self.cfg["checks"]] + st["checks"], failed_cmds), gate=(" (`%s`)" % self.cfg["gate"]) if self.cfg["gate"] else "",
                rules=("\nRead %s first: this repo's rules for work in your sandbox (what runs there, what does not)."
                       % (Path(self.wt) / self.cfg["worker_rules"])) if self.cfg["worker_rules"] else "") +
                "\nThe plan's acceptance cases run on the last stage. If you find a case they miss, add it to new_cases (the "
                "criterion it proves, the check, why); never remove or weaken one." + ("" if last else LATER_CASES) +
                UNCHECKED_TEXT, resume_key="writer", write=n, round=rounds + 1, **where)
            self.writer_family = wfam
            wr = self.sessions[-1] if self.sessions else {}
            self.write_rounds.append({"write": n, "round": rounds + 1, "node_id": wr.get("node_id"), "ref": wr.get("ref"),
                                      "resumed": "yes" if wr.get("resume") else "no",
                                      "input_tokens": (wr.get("tokens") or {}).get("in"), "turns": wr.get("turns")})
            wrote_unchecked = w.get("unchecked") or []  # the review decides what is still unproven after the checks
            if w["question"].strip() and w["decided"].strip():  # lifesim-d5f.58: an accepted requirement is no question
                rounds += 1
                self.stats["rounds"] += 1
                self.stuck_why = "the writer asked what an accepted requirement decides: %s" % w["decided"]
                self.warn("%s: %s" % (name, self.stuck_why[:300]))
                if rounds >= int(self.cfg["max_rounds"]):
                    (self.run_dir / "replan.md").write_text(self.stuck_why + "\n\nThe question: " + w["question"])
                    self.transition("replan", "rounds_used", "%d rounds used: %s" % (rounds, self.stuck_why))
                    return "replan"
                self.transition("write", "writer_decided", "an accepted requirement decides it: %s" % w["decided"])
                feedback = DECIDED_TEXT % (w["question"], w["decided"])
                continue
            if w["question"].strip():
                self.outcome_of("asks", w["question"][:200])
                raise Blocked("owner decision needed", w["question"])
            self.add_cases(w.get("new_cases") or [])
            checks = self.run_checks(dict(st, checks=st["checks"] + (self.case_checks() if last else [])), name,
                                     round=rounds + 1, **where)
            (self.run_dir / "engine-checks.json").write_text(json.dumps(checks, indent=1))
            (self.run_dir / ("engine-checks.r%d.json" % self.check_round)).write_text(json.dumps(checks, indent=1))
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
                (self.run_dir / "replan.md").write_text(self.stuck_why + "\n\nTheir output:\n" + failure_brief(wrong, self.run_dir))
                self.transition("replan", "bad_checks", "the writer says %d check%s cannot pass: %s" % (
                    len(wrong), "" if len(wrong) == 1 else "s", "; ".join(flagged[c["cmd"].strip()] for c in wrong)))
                return "replan"
            if failed:
                red += 1
                failed_cmds = [c["cmd"] for c in failed]
                feedback = ("\nThese checks fail (run by the engine, outside your sandbox). Fix exactly this:\n%s\n"
                            % failure_brief(failed, self.run_dir))
                red_text = "%d failed: %s" % (len(failed), ", ".join(c["id"][:60] for c in failed))
                if red < int(self.cfg["max_check_tries"]):
                    self.transition("write", "checks_red", red_text)
                    continue
                red, rounds = 0, rounds + 1
                self.stats["rounds"] += 1
                self.stuck_why = "checks still red after %s tries: %s" % (self.cfg["max_check_tries"], compact(failed))
                if rounds >= int(self.cfg["max_rounds"]):
                    (self.run_dir / "replan.md").write_text(self.stuck_why + "\n\nTheir output:\n" + failure_brief(failed, self.run_dir))
                    self.transition("replan", "rounds_used", "%s; %d rounds used" % (red_text, rounds))
                    return "replan"
                self.transition("write", "checks_red", "%s; round %d used" % (red_text, rounds))
                continue
            red = 0
            self.transition("review", "checks_green", "%d passed" % sum(1 for c in checks if c["exit"] == 0))
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
                writer_family=wfam, round=rounds + 1, **where)
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
                self.outcome_of("asks", review["question"][:200])
                raise Blocked("owner decision needed", review["question"])
            blocking = [f for f in review["findings"] if f["severity"] in ("high", "medium")]
            said = "%d finding%s, %d unmet" % (len(blocking), "" if len(blocking) == 1 else "s", len(review["unmet"]))
            if not blocking and not review["unmet"]:
                low = len(review["findings"])
                self.outcome_of("clean", "%d low finding%s" % (low, "" if low == 1 else "s") if low else "")
                self.transition("next", "accepted", "%s accepted" % name)
                return "accept"
            self.outcome_of("sent back", said)
            rounds += 1
            self.stats["rounds"] += 1
            self.stuck_why = "the review still sends it back: %s" % "; ".join(
                review["unmet"] + ["%s:%s %s" % (f["file"], f["line"], f["fix"]) for f in blocking])
            if rounds >= int(self.cfg["max_rounds"]):
                (self.run_dir / "replan.md").write_text(self.stuck_why)
                self.transition("replan", "rounds_used", "review sent it back: %s; %d rounds used" % (said, rounds))
                return "replan"
            failed_cmds = None
            self.transition("write", "review_sendback", "%s: round %d" % (said, rounds + 1))
            feedback = ("\nThe reviewer sent the stage back. Fix exactly this:\n%s%s\n" % (
                "".join("- unmet: %s\n" % u for u in review["unmet"]),
                "".join("- %s:%s [%s] %s\n" % (f["file"], f["line"], f["severity"], f["fix"]) for f in blocking)))

    def check_secs(self, config_dir=None):
        """{normalized cmd: seconds}: the longest run that passed, else the longest run at all. Read from every run's
        engine-checks*.json and every check-cache file under the config dir (all beads), else from the checks records
        of this bead's run logs."""
        base = Path(config_dir) if config_dir else tl.config_dir()
        seen = {}  # cmd -> ([passed secs], [all secs])

        def add(c):
            if not isinstance(c, dict) or c.get("secs") is None or not c.get("cmd") or c.get("exit") is None:
                return
            try:
                secs = float(c["secs"])
            except (TypeError, ValueError):
                return
            got = seen.setdefault(norm_cmd(c["cmd"]), ([], []))
            got[1].append(secs)
            if c["exit"] == 0:
                got[0].append(secs)

        def load(path):
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None

        for path in sorted(base.glob("runs/*/engine-checks*.json")):
            for c in load(path) or []:
                add(c)
        for path in sorted(base.glob("check-cache/*.json")):
            for by_cmd in (load(path) or {}).values():
                for c in by_cmd.values() if isinstance(by_cmd, dict) else ():
                    add(c)
        for path in sorted(self.log_path.parent.glob("%s-*.jsonl" % self.bead)):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for ln in lines:
                if '"kind": "checks"' not in ln:
                    continue
                try:
                    items = json.loads(ln).get("items") or []
                except ValueError:
                    continue
                for c in items:
                    if not c.get("cached"):
                        add(c)
        return {cmd: max(p or a) for cmd, (p, a) in seen.items()}

    def engine_only(self, cmd, secs):
        """A check the writer must not run: its longest passing run (else longest run) took over engine.writer_check_max_s,
        or it never ran and looks like a Unity, play, full test, check or build run."""
        s = secs.get(norm_cmd(cmd), secs.get(cmd))
        if cmd == self.cfg.get("gate"):
            return True
        return s > float(self.cfg["writer_check_max_s"]) if s is not None else bool(SLOW_CMD.search(cmd))

    def stage_checks_text(self, checks):
        """The stage's check list split for the writer: the fast ones it may run, the slow ones the engine runs alone."""
        if not checks:
            return "- (none named)"
        secs = self.check_secs()
        slow = [c for c in checks if self.engine_only(c, secs)]
        fast = [c for c in checks if c not in slow]
        text = ""
        if fast:
            text += "You may run these:\n" + "\n".join("- " + c for c in fast)
        if slow:
            text += ("\n" if text else "") + "The engine runs these, do not run them:\n" + "\n".join("- " + c for c in slow)
        return text

    def where(self, node, checks=(), failed=None):
        """What the step is for, never what its sandbox allows: delegate tells each worker that (worker-run v2).
        For the writer: which checks it may run (fast ones) and which are the engine's (slow ones)."""
        if node == "write":
            secs = self.check_secs()
            pool = list(dict.fromkeys(checks)) if failed is None else list(dict.fromkeys(failed))
            slow = [c for c in pool if self.engine_only(c, secs)]
            fast = [c for c in pool if c not in slow]
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
        with tempfile.TemporaryDirectory() as d:
            env = dict(tl.git_env(self.wt), GIT_INDEX_FILE=os.path.join(d, "index"))
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

    def run_checks(self, st, name, **meta):
        out = self._run_checks(st, name, **meta)
        self.assert_tree("checks", "after")
        return out

    def _run_checks(self, st, name, **meta):
        """One engine step, no AI: the repo's checks (engine.checks) and the stage's acceptance checks, grouped
        static → tests → acceptance; a red group skips the groups after it. A repo check with `when` runs only when the
        task changed a matching path; `retry` reruns a red one (known flaky). A repo check that passed on the same tree
        and base is not run again, unless it says `"cache": false`; a stage check always runs, since a plan's check can
        read what git cannot see (a running editor, a log, a bead comment). The gate is not here: it runs once, on the rebased tree, at land."""
        self.node("checks", "checks: %s" % name, **meta)
        self.check_round += 1
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
                    log_name = "%02d-%s.r%d.log" % (n, re.sub(r"[^\w.-]+", "_", c["id"])[:40], self.check_round)
                    rc, tail = self.sh(cmd, timeout=float(self.cfg["node_timeout_min"]) * 60, save=logs / log_name)
                    if rc == 0 or tries > c["retry"]:
                        break
                    self.warn("`%s` failed (exit %d), retrying: it is marked flaky" % (c["id"], rc))
                res = dict(base, exit=rc, status="ran" if rc == 0 else "failed", tries=tries, tail=tail[-1500:],
                           secs=round(time.time() - t), log="checks/" + log_name)
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
        bad = [c for c in out if c["status"] == "failed"]
        self.outcome_of("red" if bad else "green", "%d failed: %s" % (len(bad), ", ".join(c["id"][:60] for c in bad))
                        if bad else "%d passed" % sum(1 for c in out if c["status"] == "ran"))
        self.log("checks", "checks round %d: %s" % (self.check_round, "%d failed" % len(bad) if bad else "green"),
                 node_id=(self.cur or {}).get("id"), round=self.check_round, items=[
                     {"id": c["id"], "cmd": c["cmd"], "group": c["group"], "exit": c["exit"], "status": c["status"],
                      "secs": c.get("secs"), "tries": c.get("tries"), "cached": bool(c.get("cached")),
                      "why": c.get("why") or "", "log": "" if c.get("cached") else c.get("log") or ""} for c in out])
        return out

    def finish(self, bead):
        if not self.git("status", "--porcelain"):
            if self.git("rev-list", "--count", "%s..HEAD" % self.cfg["base"]) in ("", "0"):
                self.log("note", "nothing changed")
                return ""
        # one commit per task, titled after the bead: earlier runs' wip commits are folded in
        base = self.git("merge-base", "HEAD", self.cfg["base"])
        if base:
            self.sh(["git", "reset", "-q", "--soft", base], check=True, pin=True)
        self.stage_all(check=True)
        msg = "%s (%s)" % (bead.get("title", self.bead)[:72], self.bead)
        rc, tail = self.sh(["git", "commit", "-q", "-m", msg], pin=True)
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
                self.node("land", "land (try %d)" % (pushes + 1), **{"try": pushes + 1})
                rc, tail = self.fetch()
                if rc == 0:
                    rc, tail = self.sh(["git", "rebase", "-q", self.cfg["base"]], pin=True)
                if rc:
                    unmerged = self.git("diff", "--name-only", "--diff-filter=U")
                    if not unmerged:
                        self.sh(["git", "rebase", "--abort"], pin=True)
                        raise Blocked("failed: fetch or rebase onto %s failed; branch kept\n%s" % (self.cfg["base"], tail))
                    problem = ("conflict", "Conflicted files: %s\n%s" % (", ".join(unmerged.split()), tail))
                    self.outcome_of("conflict", ", ".join(unmerged.split()))
                elif self.cfg["gate"]:
                    self.gate_log = self.run_dir / ("gate.r%d.log" % (self.fixes + 1))
                    rc, tail = self.sh(self.cfg["gate"], save=self.gate_log)
                    if rc:
                        problem = ("gate", tail)
                        self.outcome_of("gate red", (tail.strip().splitlines() or [""])[-1])
                if not problem:
                    with self.stop_deferred() as stop:  # a push half done is no state to stop in: finish it, then stop
                        rc, tail = self.sh(self.cfg["land"], pin=True, env={"TASK_LOOP_GATED_TREE": self.git(
                            "rev-parse", "HEAD^{tree}")} if self.cfg["gate"] else None)  # a pre-push hook may skip a gate this tree passed
                        if rc == 0:
                            self.landed_sha = sha = self.git("rev-parse", "HEAD")
                            tl.cmd_land(Args(id=self.bead, sha=sha, worktree=self.wt))
                    if rc == 0:
                        self.outcome_of("landed", sha[:12])
                        if stop:
                            self.warn("a stop came during the land: landed first, closing now")
                        return sha
                    if stop:
                        raise Blocked("failed: stopped (SIGTERM)")
                    if not re.search(r"rejected|non-fast-forward|fetch first|stale info", tail):
                        raise Blocked("land failed\n" + tail)
                    pushes += 1
                    self.outcome_of("rejected", "main moved")
                    if pushes >= 5:
                        raise Blocked("land rejected 5 times: main moves too fast")
                    self.warn("push rejected (main moved), try %d of 5" % pushes)
                    self.transition("land", "push_race", "push rejected (main moved): try %d of 5" % (pushes + 1))
                    continue
            if self.fixes < int(self.cfg["max_fix_rounds"]):
                self.transition("fix", "gate_red" if problem[0] == "gate" else "conflict",
                                "gate red on the rebased tree: %s" % (problem[1].strip().splitlines() or [""])[-1][:200]
                                if problem[0] == "gate" else problem[1].splitlines()[0])
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
                self.sh(["git", "rebase", "--abort"], pin=True)
            raise Blocked("%s after %d fix rounds: it needs the owner's hint\n%s" % (what, limit, tail[-3000:]))
        self.warn("land: %s, fix round %d of %d" % (what, self.fixes, limit))
        self.save_checkpoint(stage=len((self.plan_data or {}).get("stages") or []), rounds=0, n=0, feedback="", step="land")
        checks = list(dict.fromkeys(c for s in (self.plan_data or {}).get("stages") or [] for c in s["checks"]))
        if kind == "conflict":
            checks.append(self.MARKERS)
        goal, text = self.FIX[kind]
        st = {"goal": "Fix: " + goal, "files": [], "checks": checks, "hard": False}
        d = self.stage({"stages": [st]}, 0, {
            "fix": True, "name": "fix %d/%d" % (self.fixes, limit), "fix_n": self.fixes, "fix_of": limit,
            "failed": [self.cfg["gate"] or "rebase"] if kind == "gate" else None,
            "feedback": text % tail if kind == "verify" else text % (
                (" (`%s`)" % self.cfg["gate"]) if kind == "gate" and self.cfg["gate"] else "",
                failure_brief([{"cmd": self.cfg["gate"] or "rebase", "exit": 1, "status": "failed", "group": "gate",
                                "tail": tail[-4000:], "log": str(getattr(self, "gate_log", "") or "")}], self.run_dir)
                if kind == "gate" else compact([{"cmd": "rebase", "exit": 1, "status": "failed", "group": "gate",
                                                 "tail": tail[-4000:]}])),
            "scope": "the fix only: it must %s without breaking what the accepted stages built" % goal})
        if kind == "conflict":
            if self.sh(self.MARKERS, pin=True)[0]:
                return self.fix("conflict", "conflict markers are still in the tree after the fix")
            self.stage_all(check=True)
            rc, out = self.sh(["git", "-c", "core.editor=true", "rebase", "--continue"], pin=True)
            if rc:
                self.sh(["git", "rebase", "--abort"], pin=True)
                raise Blocked("failed: the rebase did not continue after the conflict fix\n" + out)
        elif kind == "gate" and self.git("status", "--porcelain"):
            self.stage_all(check=True)
            self.sh(["git", "commit", "-q", "--amend", "--no-edit"], check=True, pin=True)
        if d != "accept" and kind != "verify":
            self.warn("land: the fix round did not pass its checks and review; landing tries the gate again")
        return d

    @contextlib.contextmanager
    def land_lock(self):
        """One land at a time per repo, across slots and sessions: an flock the OS drops when the process dies."""
        path = tl.land_lock_path(self.git("remote", "get-url", "origin") or str(self.wt))
        with tl.os_lock(path, self.bead, lambda who: self.log("note", "waiting for the land lock (held by %s)" % who)):
            yield path

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

    def wip(self, why):
        self.stage_all()
        rc, _ = self.sh(["git", "commit", "-q", "-m", "wip (%s): %s" % (self.bead, why)], pin=True)
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
            self.sh(["git", "rebase", "--abort"], pin=True)
        branch = self.git("symbolic-ref", "--short", "-q", "HEAD")
        new = [lo for lo in self.leftovers if lo["title"] not in self.filed]
        self.filed += [lo["title"] for lo in new]  # into the checkpoint before it is marked closed
        if outcome not in ("landed", "done") and branch and branch == getattr(self, "branch", None):
            if self.git("status", "--porcelain"):
                self.wip(outcome)  # the next run continues this branch
            self.mark_checkpoint_closed(why)
        stats = "cost=$%.2f; minutes=%d; %s" % (self.cost, mins, "; ".join("%s=%s" % kv for kv in self.stats.items()))
        self.log_run()
        last = self.cur or self.last_node
        if last and (self.moved_from != last["id"] or self.moved_to not in ("ask", "pause", "close")):
            # no move out of the run was logged from the last node: the close is it
            to, cause = close_move(outcome, why)
            self.transition(to, cause, why.splitlines()[0][:200] if why else outcome)
        self.end_node(node_outcome(outcome, why))
        self.node("close", "close: %s" % outcome, outcome=outcome, why=why)
        self.outcome_of(outcome, why.splitlines()[0][:200] if why else "")
        self.end_node()
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
        self.asked = bool(kind)
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


GHERKIN_TEST = re.compile(r"^\s*Scenario( Outline)?:")  # a use-case scenario (Reqnroll, lifesim-fld.26.10)


QUIET_KINDS = ("end", "transition", "checks", "run")  # trace records for the dashboard, never printed
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


def node_outcome(outcome, why):
    """What a node still open at the close came to: the run's own end."""
    if outcome in ("landed", "done"):
        return outcome
    if why.startswith("paused:"):
        return "paused"
    if why.startswith("waiting:"):
        return "waiting"
    if why.startswith("failed: stopped"):
        return "stopped"
    if outcome == "failed":
        return "failed"
    return "asks" if ask_kind(why) else "blocked"


def close_move(outcome, why):
    """(to, cause) of the last move, when no decision point logged one: landed, an ask, a pause, a wait, a failure."""
    if outcome in ("landed", "done"):
        return "close", outcome
    if why.startswith("paused:"):
        return "pause", "paused"
    if why.startswith("waiting:"):
        return "ask", "waiting"
    kind = ask_kind(why)
    if kind:
        return "ask", kind
    return "close", "stopped" if why.startswith("failed: stopped") else "failed"


def count_tests(diff, pattern):
    """Tests added and removed in a unified diff: lines matching the repo's test pattern (engine.test_pattern), and
    Gherkin scenarios in .feature files."""
    rx, feature = re.compile(pattern), False
    added = removed = 0
    for ln in diff.splitlines():
        if ln.startswith(("+++", "---")):
            if not ln.rstrip().endswith("/dev/null"):  # a deleted file names itself on its --- line only
                feature = ln.rstrip().endswith(".feature")
            continue
        hit = (GHERKIN_TEST if feature else rx).search(ln[1:])
        if ln.startswith("+") and hit:
            added += 1
        elif ln.startswith("-") and hit:
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
    """The bead's lease, and the slot bead's when tl loop runs this (TASK_LOOP_SLOT_BEAD): a loop killed with SIGKILL
    leaves its slot held while this run lives."""

    def __init__(self, bead, slot_bead=""):
        self.beads, self.stop_ev = [b for b in (bead, slot_bead) if b], threading.Event()
        self.th = threading.Thread(target=self.loop, daemon=True)

    def start(self):
        self.th.start()

    def loop(self):
        while not self.stop_ev.wait(60):
            for b in self.beads:
                tl.bd("heartbeat", b)

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


SLOW_CMD = re.compile(r"(?i)(?<![a-z])(unity|play|test[-_]all|check|build|dotnet)")
ERR_LINE = re.compile(r"(?i:error|fail|exception|assert)|: E")
NOISE_LINE = re.compile(r"\b0 Error|\bwarning [A-Z]+\d+:")
STRONG_LINE = re.compile(r"\berror [A-Z]*\d+|: error")
FRAME_LINE = re.compile(r'^\s*File ".*", line \d+')


def norm_cmd(cmd):
    return " ".join(str(cmd).split())


def failure_brief(checks, run_dir, each=6000, total=12000, lines=40):
    """The failing checks for a fix brief: command (cut at 300 chars), log path ("none" when no log), then the error lines
    of the saved log (noise dropped, real compiler errors first, deduplicated, up to `lines`, newline layout kept), else
    its last `lines` lines; the last python traceback frame; then always the log's last line (a timeout says so there).
    `each` bytes per check, `total` for all; a cut never drops that last part."""
    out, left = [], total
    for c in checks:
        log = Path(run_dir, c["log"]) if c.get("log") else None
        try:
            text = log.read_text(encoding="utf-8", errors="replace") if log else c.get("tail") or ""
        except OSError:
            text, log = c.get("tail") or "", None
        rows = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
        hits = list(dict.fromkeys(ln for ln in rows if ERR_LINE.search(ln) and not NOISE_LINE.search(ln)))
        hits = ([ln for ln in hits if STRONG_LINE.search(ln)] + [ln for ln in hits if not STRONG_LINE.search(ln)])[:lines]
        body = hits or [ln for ln in rows if not NOISE_LINE.search(ln)][-lines:]
        frames = [i for i, ln in enumerate(rows) if FRAME_LINE.match(ln)]
        if frames:
            body = [ln for ln in rows[frames[-1]:frames[-1] + 2] if ln not in body] + body
        code = c.get("exit")
        end = []
        if isinstance(code, int) and (code == 124 or code < 0):
            secs = c.get("secs")
            end.append("timed out after %s s" % (int(secs) if isinstance(secs, (int, float)) else "?"))
        if rows and rows[-1] not in body:
            end.append(rows[-1])
        cmd = c["cmd"] if len(c["cmd"]) <= 300 else c["cmd"][:300] + "..."
        head = "- `%s` exit %s\n  log: %s" % (cmd, code, log or "none")
        room = min(each, left)
        if room <= 0:
            out.append(head + "\n  (output left out: see the log)")
            continue
        tail = "\n".join(end)
        main = "\n".join(body)
        if len(main) > max(room - len(tail), 0):
            main = main[:max(room - len(tail), 0)] + "\n... (cut: see the log)"
        text = "\n".join(x for x in (main, tail) if x)
        left -= len(text)
        out.append(head + ("\n" + text if text else ""))
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
          "or delete tests; a test that contradicts an accepted requirement is fixed to match the requirement, never "
          "weakened or deleted to make the code pass. Answer with the structured result only.")

DECIDED_RULE = ("A change that contradicts an accepted requirement (in the task, its acceptance criteria, or a "
                "requirement it cites) is never the owner's question: the fix is to meet the requirement. Nor is a test, "
                "check or scenario at odds with an accepted requirement: that is no conflict between two requirements. "
                "A test that contradicts an accepted requirement is fixed to match the requirement, never weakened or "
                "deleted to make the code pass. An owner's answer in the task's comments decides "
                "as an accepted requirement does. decided: the "
                "accepted requirement, quoted, that already answers your question (the engine then sends the stage "
                "back to meet it instead of asking the owner); empty when you have no question, when two accepted "
                "requirements conflict, or when no requirement decides it yet (those are the owner's).")
REPLAN_CAP = "stuck: the bead was re-planned "  # the cap's ask; an owner's answer to it allows one more
RULES_INLINE_MAX = 6 * 1024   # a worker_rules file under this goes into the planner's brief
PLAN_BRIEF_KB = 12            # the planner's whole brief should stay under this
DECIDED_TEXT = ("\nYou asked: %s\nAn accepted requirement already decides it: %s\nMeet that requirement: change the "
                "work, never the requirement.\n")
PLAN_DECIDED_TEXT = "Plan the work that meets it; ask nothing it already answers.\n"

PLAN_PROMPT = COMMON + """

The task (the bead, with its acceptance criteria and comments: review findings, the owner's answers):
<task>
{brief}
</task>
Explore cheaply: find code with `rg -n` and read line ranges (`sed -n 'a,bp'`), not whole files. Stop reading once
each stage has its files and its checks. Budget: about 12 tool calls. Then plan.

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
  so it can be answered from a phone: what you found, the decision, 2-3 options with costs, your recommendation.
""" + DECIDED_RULE

WRITE_PROMPT = """You are the writer for one stage of a task, in an unattended engine. Nobody is watching.

<task>
{brief}
</task>
<plan>
{plan}
</plan>
Your stage: {n}: {goal}{rules}
Files: {files}
The stage's checks (the engine runs all of them after you; the split says which you may run):
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
    """DEFAULTS plus the `engine` block of the repo's .task-loop.json as committed on the base branch (tl.profile).
    The base is itself a key: the working tree (or DEFAULTS) names it, then the base's copy is read. A caller fetches
    first (the loop's queue does; run-task reads the last fetch, and resets onto the base anyway)."""
    cfg = json.loads(json.dumps(DEFAULTS))
    local = tl.profile(repo).get("engine") or {}
    base = local.get("base") or cfg["base"]
    cfg.update(tl.profile(repo, base).get("engine") or {})
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
        rc = {"v": 1, "outcome": "failed", "bead": a.id, "why": b.why}
    if isinstance(rc, dict):  # stopped before the engine ran: nothing in the bead changed
        report(a, rc)
        return 1
    return rc


def run_main(a):
    for f in (sys.stdout, sys.stderr):
        append_output(f)
    if hasattr(signal, "SIGTERM"):  # a stop (kill switch, coordinator) still runs the close step
        signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(Blocked("failed: stopped (SIGTERM)")))
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
                       on_wait=waiting)
    if not got:
        why = "no free slot (tl slot list); --wait waits in line for one"
        print("TAKEN: %s" % why)
        return {"v": 1, "outcome": "taken", "bead": a.id, "why": why}
    a.slot, a.worktree, sb = got
    os.environ["TASK_LOOP_SLOT_BEAD"] = sb  # run_in sees the slot as taken; the engine heartbeats it
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
    """The engine lock, with the area check before it under the area lock (loop.area_lock): "" when this run holds the
    worktree, else why not. A bead whose area runs elsewhere: a warning, or refused with --exclusive-area."""
    import loop  # the queue rule; imports engine itself

    def mark():  # the slot says which bead runs in it (held_bead makes its area busy): only once the area is decided
        if sb:
            tl.bd("update", sb, "--set-metadata", "held_bead=" + a.id, cwd=repo)
    if not loop.has_areas(cfg):
        why = lock.take()
        if not why:
            mark()
        return why
    with loop.area_lock(repo, cfg):
        area, busy = loop.area_busy(repo, cfg, tl.show(a.id) or {"id": a.id}, {})
        if busy and getattr(a, "exclusive_area", False):
            return busy + " (--exclusive-area)"
        if busy:
            say("⚠ %s: running anyway beside it; --exclusive-area refuses instead" % busy)
        why = lock.take()
        if not why:
            mark()
        return why


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
    global LOCK
    took = ""
    try:
        # a hand run takes its slot's bead as the loop does (a --worktree that is a slot too); one the loop started has
        # it already: TASK_LOOP_SLOT_BEAD names that very slot's bead
        slot = a.slot or tl.slot_of(repo, wt)
        sb = (tl.slot_bead(repo, slot) or {}).get("id") if slot else ""
        if slot and not (sb and os.environ.get("TASK_LOOP_SLOT_BEAD") == sb):
            took, why = tl.take_named_slot(repo, slot, tl.profile_slots(repo), "run-task " + a.id)
            if not took:
                print("TAKEN: %s" % why)
                return {"v": 1, "outcome": "taken", "bead": a.id, "why": why}
            os.environ["TASK_LOOP_SLOT_BEAD"] = took  # the engine's heartbeat keeps it
        lock = EngineLock(wt, a.id, slot)
        busy = take_area(a, repo, cfg, lock, sb=took or sb if slot else "")
        if busy:
            why = busy if busy.startswith("area ") else "worktree %s: %s" % (wt, busy)
            print("TAKEN: %s" % why)
            return {"v": 1, "outcome": "taken", "bead": a.id, "why": why}
        LOCK = lock
        return run_bead(a, repo, cfg, wt)
    finally:
        old = signal.signal(signal.SIGTERM, signal.SIG_IGN) if hasattr(signal, "SIGTERM") and \
            threading.current_thread() is threading.main_thread() else None
        try:
            if LOCK:
                LOCK.release()
                LOCK = None
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
        cfg["fresh"] = bool(getattr(a, "fresh", False))
        eng = Engine(a.id, wt, cfg, dry_run=a.dry_run, verbose=not getattr(a, "quiet", False))
        eng.stop_pending = bool(stop)
        say("engine log: %s" % eng.log_path)
    rc = eng.run()
    with defer_stop(None):  # the outcome line is what the loop reads: a stop waits for it
        rec = eng.result()
        if pause_line(rec):
            say(pause_line(rec))
        report(a, rec)
    return rc
