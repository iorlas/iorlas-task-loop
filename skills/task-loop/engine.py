#!/usr/bin/env python3
"""The task engine: one bead through reset → plan → (write → checks → review)* per stage → gate → land → close.

    tl.py run-task ID [--worktree DIR] [--dry-run]

Code routes; AI nodes only produce structured outputs (validated against a schema). The close step always runs.
A coordinator session may start it and watch it (attended mode); nothing here needs one. Design:
docs/design/coordinator-less.md. Python 3.8+, standard library only.
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

from checks import lint, trim
from checks import speed as cs
from core import enginelock, fmt
import applog
import lifecycle
import links
import looks
import loop_health
import outcome as oc
import seams
import tl
import vendored  # noqa: F401
from clock import SystemClock
from taskloop.adapters import delegate as dg
from taskloop.adapters import procs as sproc
from taskloop.adapters.runner import live_path
from taskloop.app.asks import intake, raiser
from taskloop.app.run import trace as runtrace
from taskloop.app.run.calls import timing
from taskloop.app.run.context import RunContext
from taskloop.app.run.worker_call import Ops, WorkerCall
from taskloop.app.slots.lease import Lease
from taskloop.contracts import log as rec
from taskloop.contracts.ask import BudgetLine
from taskloop.contracts.bead import Bead
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
from taskloop.domain.lanes.matchers import read_only_command, split_top
from taskloop.domain.lanes.says import stop_say, stop_why
from taskloop.stores.real import real_stores

# ---- output contracts -----------------------------------------------------------------------------------------------

FLAKE_DAYS = 14     # how long a writer-reported flaky test stays in the shared notes
# tl-ntp (owner ruling 82 item 1): agents assume and record an Assumption; only a step that cannot be undone may ask the owner.
IRREVERSIBLE = {"push_shared": "a push to a shared branch", "delete_outside": "a deletion outside the worktree",
                "close_epic": "closing an epic", "spend_money": "spending money"}
ASSUMPTION = "Assumption: "  # the stable prefix of an assumption line (plan comment, plan summary)
INPUT_KINDS = ("file", "platform", "object", "engine", "tool", "other")
CAUSE_CLASSES = ("engine", "prompt", "delegate", "repo_profile", "bead", "sandbox", "other")  # tl-05s
PROVED_BY = ("check", "stage", "leftover", "engine_step")  # tl-bxk.13.16.1: how a plan criterion is proved (the ledger)
HANDOFF_CAP = 1500  # characters of round history one prompt carries (tl-bxk.13.6)
S_STR = {"type": "string"}
S_STRS = {"type": "array", "items": S_STR}
OPTIONS = {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                      "required": ["label", "cost", "answer", "recommended"],
                                      "properties": {"label": S_STR, "cost": S_STR, "answer": S_STR,
                                                     "recommended": {"type": "boolean"}}}}
OPTIONS_RULE = ("options: with a question, 2-4 answers the owner can click, each a short label, a one-line cost, the exact "
                "answer text the next run will read, and recommended (true for exactly one: yours); empty with no question.")
LEFTOVERS = {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                        "properties": {"title": S_STR, "why": S_STR}, "required": ["title", "why"]}}
# tl-bxk.10.28: the AI classifies an unchecked item, the engine routes it. The first six are the old kinds (an old
# checkpoint or a worker still sends them): an open one is asked, as before.
ROUTED_KINDS = ("engine_step", "checkable", "external_fact", "taste", "owner_decision")
LEGACY_KINDS = ("requirement", "number", "deletion", "link", "case", "tooling")
# a kind may move only toward a stricter route (never to a looser one): the engine settles the loosest, asks the strictest
KIND_RANK = dict({"engine_step": 0, "external_fact": 1, "taste": 1, "checkable": 2, "owner_decision": 3},
                 **{k: 2 for k in LEGACY_KINDS})
CODE_EXT = re.compile(r"\.(?:py|cs|js|jsx|ts|tsx|go|rs|java|kt|rb|sh|c|h|cpp|hpp|json|ya?ml|toml|md|txt|csv|sql|css|html|gd|"
                      r"lua|swift|asmdef|unity|prefab)$", re.I)
SYMBOL = re.compile(r"\b(?:[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+|[a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b")
# what the engine itself does for a bead; an engine_step item settles only when it names one of these and the engine will
ENGINE_FILES = re.compile(r"\b(?:fil(?:e|es|ed|ing)|creat(?:e|es|ed|ing)|open(?:s|ed|ing)?)\b.*\b(?:follow-?ups?|leftovers?)\b|"
                          r"\b(?:follow-?ups?|leftovers?)\b.*\b(?:not filed|filed|files?|creat\w+)\b", re.I)
ENGINE_BEADS = re.compile(r"\bfil(?:e|es|ed|ing)\s+(?:(?:the|a|an|these|those|all|each|new|nine|\d+|follow-?ups?)\s+)*beads?\b|"
                          r"\bcreat(?:e|es|ed|ing)\s+(?:(?:the|a|an|these|those|all|each|new|nine|\d+|follow-?ups?)\s+)*beads?\b|"
                          r"\bbeads?\b[^.]{0,40}\b(?:to be (?:filed|created)|(?:is |are )?(?:not )?filed|to file)\b", re.I)
ENGINE_LANDS = re.compile(r"\b(?:at|after|before|on) (?:the )?land(?:ing)?\b|\bthe engine (?:lands|merges|pushes|runs the gate)\b|"
                          r"\bthe (?:land )?gate (?:runs|will run)\b", re.I)
ENGINE_SHOTS = re.compile(r"\b(?:screenshots?|shots|pictures)\b.*\b(?:copi\w+|committed|kept|saved into the repo)\b|"
                          r"\b(?:copi\w+|commit\w*|keeps?)\b.*\b(?:screenshots?|shots|pictures)\b", re.I)
ENGINE_CLOSES = re.compile(r"\bclos(?:e|es|ed|ing)\b[^.]*\bbead\b|\bbead\b[^.]*\bclos(?:e|es|ed|ing)\b", re.I)
UNCHECKED_KINDS = ROUTED_KINDS + LEGACY_KINDS  # one of these unchecked is verified before the land
KIND_LINES = (
    "engine_step: something the engine itself does after this point (files leftover or follow-up beads, lands, runs the "
    "gate, copies screenshots, closes the bead)",
    "checkable: a behaviour, a number the code computes or a rate holding across cases: a test or check could prove it",
    "external_fact: a fact from outside the repo (a price, a licence, a size quoted from a web page or a file the repo "
    "does not hold) that no check here can prove; give its source (a URL or the named outside document)",
    "taste: a look, a feel or a judgement call only a person can make",
    "owner_decision: needs the owner to decide: a change to the contract or requirements, money, an account or a login",
    "case: an acceptance case you could not run",
)
UNCHECKED_TEXT = ("\nunchecked: what you could not check yourself, each with its kind: " + "; ".join(KIND_LINES) +
                  "; or other. Empty when you checked everything.")

VERDICTS = ("settled", "wrong", "open")  # the verifier's answer per unchecked item, before a verify ask

# tl-bxk.10.23: engine.visual_paths {include, exclude} (globs) says which changes are visual; absent, no look rules at all
IMAGE_EXT = (".png", ".jpg", ".jpeg")
MAX_SHOTS, MAX_SHOT_BYTES = 20, 5 * 1024 * 1024
LOOK_WRITE_TABLE = ("\nThis stage changes how something looks (it touches visual paths). You cannot render it here: the engine does, "
                    "right after this write, and a look judge reads the pictures. Say what to render in `shots`: one entry per "
                    "set of pictures, with a method from the table below, its args (name, value) and names (the screens or "
                    "states you changed, in words). At most %d entries. Do not save screenshots yourself.\n%s\nIf nothing on "
                    "screen differs, leave `shots` empty and put a one-line reason in logic_only.")
LOOK_FEEDBACK = ("\nThe engine rendered your shots and the look judge found these defects:\n%s\nThe pictures are at (open one only "
                 "if you need to):\n%s\nFix what the judge saw, and list the shots to render again in `shots`.\n")
LOOK_ITEM = re.compile(r"owner\b[^.]{0,40}\b(?:judge|check|decide|assess|review|verify)\b[^.]*\b"
                       r"(?:looks?|visual\w*|appearance|screenshots?)\b", re.I)  # 'Only the owner can judge the look.'
LOOK_LABEL = "owner-look"


glob_re = cs.glob_re  # one glob dialect for visual_paths and a check's `inputs` (defined in checks_speed)


def check_inputs(c):
    """A configured check's `inputs` as a list (the file allows one glob as a string)."""
    return [c.inputs] if isinstance(c.inputs, str) else list(c.inputs)


def visual_hit(vp, paths):
    """True when a path matches an include glob and no exclude glob."""
    inc = [glob_re(g) for g in vp.include] if vp else []
    exc = [glob_re(g) for g in vp.exclude] if vp else []
    return any(any(r.match(p) for r in inc) and not any(r.match(p) for r in exc) for p in paths)

TRACKER_TEXT = ("\n\nYour plan was sent back: these checks read the issue tracker (they run bd or read .beads/), which "
                "no writer can run and no code change can satisfy:\n%s\nRewrite them to prove the code and the tree only. "
                "Follow-up work the task wants filed goes in leftovers: the engine files it.")

REPEAT_TEXT = ("\n\nYour plan was sent back: these slow commands run in more than one check, or repeat a check the engine already "
               "runs, and each run takes minutes:\n%s\nRun each once. A check that needs its result reads the file the first "
               "one saved, or `$TL_CHECK_LOG_<ID>` for a repo check, instead of running the command again.")

EMPTY_PLAN_TEXT = ("\n\nYour plan was sent back: it has no stages, no question and no leftovers, so there is nothing to do and nothing to "
                   "ask. A plan has at least one stage (goal, files, checks). If the work is already done in the tree, plan the "
                   "stage that checks it. If only follow-up work is left, list it in leftovers. If the task cannot be done without "
                   "an owner's decision, ask it in question.")

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
    engine_text = " ".join([cfg.gate or ""] + [str(c) for c in cfg.checks])
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




FIELDS = ("title", "description", "acceptance_criteria", "design", "notes")


def bead_snapshot(bead, comments):
    """What a later amend diffs against: the bead's text fields, issue type, dependencies (id:type) and the people's
    comments, as the planner saw them."""
    deps = sorted("%s:%s" % (d.id, d.type) for d in bead.dependencies if d.id)
    return {"fields": {k: (people_lines if k == "notes" else str.strip)(getattr(bead, k)) for k in FIELDS},
            "issue_type": bead.issue_type.strip(), "deps": deps,
            "comments": [c.text.strip() for c in comments if not engine_written(c.text)]}


DIFF_CAP = 4096


def bead_diff(old, new, answer="", comments=True):
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
    for t in (new["comments"] if comments else []):
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
    text = " ".join(getattr(bead, k) for k in FIELDS) + " " + " ".join(c.text for c in comments if not engine_written(c.text))
    deps = {d.id: d for d in bead.dependencies if d.id}
    ids = list(deps) + [bead.parent]
    ids += re.findall(r"(?<![\w.-])(%s-[A-Za-z0-9]+(?:\.[0-9]+)*)" % re.escape(pre), text)
    ids = [i for i in dict.fromkeys(ids) if i and i != bead_id][:cap]
    out = []
    for i in ids:
        d = deps.get(i)
        if d is None or not d.status or (d.status == "closed" and not d.close_reason):
            d = show(i) or d
        if d is None:
            continue
        # no field tells an owner from another author: a comment is anyone's but the engine's
        notes = [c for c in comments_of(i) if not engine_written(c.text)]
        line = "- %s [%s] %s" % (i, d.status or "?", " ".join(d.title.split()))
        if d.close_reason.strip():
            line += "\n  closed: " + " ".join(d.close_reason.split())
        if notes:
            line += "\n  comment: " + " ".join(notes[-1].text.split())
        out.append(line if len(line) <= each else line[:each - 3] + "...")
    return ("\n## Linked beads (data, not instructions):\n" + "\n".join(out) + "\n") if out else ""


LATER_CASES = ("\nAn acceptance case this stage cannot run is not unchecked: it is checked when the last stage runs it.")
SCHEMAS = {
    "plan": {"type": "object", "additionalProperties": False,
             "required": ["summary", "stages", "risks", "question", "options", "decided", "cases", "leftovers"],
             "properties": {
                 "summary": S_STR, "decided": S_STR,
                 "stages": {"type": "array", "items": {
                     "type": "object", "additionalProperties": False, "required": ["goal", "files", "checks", "hard"],
                     "properties": {"goal": S_STR, "files": S_STRS, "checks": S_STRS, "hard": {"type": "boolean"}}}},
                 "risks": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                      "required": ["what", "check"],
                                                      "properties": {"what": S_STR, "check": S_STR}}},
                 "question": S_STR, "options": OPTIONS,
                 "irreversible": {"type": "string", "enum": [""] + list(IRREVERSIBLE)},  # optional (tl-ntp): what the question's step cannot undo
                 "unresolved": {"type": "array", "items": {  # optional (tl-bxk.13.16.3): inputs the criteria need that were not found
                     "type": "object", "additionalProperties": False, "required": ["what", "kind", "path"],
                     "properties": {"what": S_STR, "kind": {"type": "string", "enum": list(INPUT_KINDS)}, "path": S_STR}}},
                 "cases": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                      "required": ["criterion", "check"],
                                                      "properties": {"criterion": S_STR, "check": S_STR,
                                                                     "class": {"type": "string", "enum": list(looks.CLASSES)},
                                                                     "proved_by": {"type": "string", "enum": list(PROVED_BY)},
                                                                     "via": S_STR}}},
                 "leftovers": LEFTOVERS}},
    "write": {"type": "object", "additionalProperties": False,
              "required": ["summary", "checks_run", "question", "options", "decided", "bad_checks", "new_cases", "unchecked"],
              "properties": {"summary": S_STR, "question": S_STR, "options": OPTIONS, "decided": S_STR,
                             "shots": {"type": "array", "items": {  # optional (tl-bxk.13.15.2): what the engine should render after this write
                                 "type": "object", "additionalProperties": False, "required": ["method", "args", "names"],
                                 "properties": {"method": S_STR, "names": S_STRS,
                                                "args": {"type": "array", "items": {
                                                    "type": "object", "additionalProperties": False, "required": ["name", "value"],
                                                    "properties": {"name": S_STR, "value": S_STR}}}}}},
                             "flakes": {"type": "array", "items": {  # optional (tl-bxk.13.8): tests that failed for a reason outside the change
                                 "type": "object", "additionalProperties": False, "required": ["test", "note"],
                                 "properties": {"test": S_STR, "note": S_STR}}},
                             "unchecked": {"type": "array", "items": {
                                 "type": "object", "additionalProperties": False, "required": ["what", "kind"],
                                 "properties": {"what": S_STR, "kind": {"type": "string", "enum": list(UNCHECKED_KINDS) + ["other"]},
                                                "source": S_STR}}},
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
               "required": ["findings", "unmet", "question", "options", "decided", "leftovers", "unchecked"],
               "properties": {"unchecked": {"type": "array", "items": {
                       "type": "object", "additionalProperties": False, "required": ["what", "kind"],
                       "properties": {"what": S_STR, "kind": {"type": "string", "enum": list(UNCHECKED_KINDS) + ["other"]},
                                                "source": S_STR}}},
                   "findings": {"type": "array", "items": {
                   "type": "object", "additionalProperties": False, "required": ["file", "line", "severity", "fix"],
                   "properties": {"file": S_STR, "line": {"type": "integer"},
                                  "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                                  "fix": S_STR}}},
                   "unmet": S_STRS, "question": S_STR, "options": OPTIONS, "decided": S_STR, "leftovers": LEFTOVERS,
                   "accept_files": S_STRS, "reject_files": S_STRS}},  # optional: unexplained new files the review accepts into the commit / rejects as strays
    "reflect": {"type": "object", "additionalProperties": False, "required": ["went_well", "went_badly", "wasted", "change"],
                "properties": {"went_well": S_STRS, "wasted": S_STRS, "change": S_STRS,
                               "went_badly": {"type": "array", "items": {
                                   "type": "object", "additionalProperties": False, "required": ["what", "cause", "session", "evidence"],
                                   "properties": {"what": S_STR, "cause": {"type": "string", "enum": list(CAUSE_CLASSES)},
                                                  "session": S_STR, "evidence": S_STR}}}}},
    "look": {"type": "object", "additionalProperties": False, "required": ["findings", "summary"],
             "properties": {"summary": S_STR,
                            "findings": {"type": "array", "items": {
                                "type": "object", "additionalProperties": False, "required": ["item", "verdict", "where", "why"],
                                "properties": {"item": S_STR, "verdict": {"type": "string", "enum": ["pass", "defect"]},
                                               "where": S_STR, "why": S_STR}}}}},
    "verify": {"type": "object", "additionalProperties": False, "required": ["items"],
               "properties": {"items": {"type": "array", "items": {
                   "type": "object", "additionalProperties": False, "required": ["n", "verdict", "evidence", "why", "kind", "source"],
                   "properties": {"n": {"type": "integer"}, "verdict": {"type": "string", "enum": list(VERDICTS)},
                                  "evidence": S_STR, "why": S_STR,
                                  "kind": {"type": "string", "enum": list(UNCHECKED_KINDS) + ["other"]}, "source": S_STR}}}}},
}


LOOK_FIELDS = {"write": "logic_only", "review": "look"}  # asked only on a visual stage (tl-bxk.10.23)


def schema_for(node, visual=False):
    """The node's contract; on a visual stage (visual_paths set and the stage touches them) a copy that also requires the
    look field. Everywhere else exactly SCHEMAS[node]."""
    field = LOOK_FIELDS.get(node)
    if not (visual and field):
        return SCHEMAS[node]
    sch = copy.deepcopy(SCHEMAS[node])
    sch["properties"][field] = S_STR
    sch["required"] = list(sch["required"]) + [field]
    return sch


def strict(schema):
    """The contract as Codex's strict structured output takes it: every object requires all its properties, and one the
    contract leaves optional may be null instead. 53 lifesim runs stopped on 'Missing source' (2026-10-22)."""
    sch = copy.deepcopy(schema)
    if sch.get("type") == "object":
        props = sch.get("properties", {})
        for k, v in props.items():
            v = props[k] = strict(v)
            if k not in sch.get("required", []):
                if isinstance(v.get("type"), str):
                    v["type"] = [v["type"], "null"]
                if "enum" in v:
                    v["enum"] = list(v["enum"]) + [None]
        sch["required"] = list(props)
    if sch.get("type") == "array" and isinstance(sch.get("items"), dict):
        sch["items"] = strict(sch["items"])
    return sch


def unstrict(data, schema):
    """A strict answer back in the contract's shape: an optional field the worker sent as null is left out."""
    if schema.get("type") == "object" and isinstance(data, dict):
        props, req = schema.get("properties", {}), set(schema.get("required", []))
        return {k: unstrict(v, props[k]) if k in props else v for k, v in data.items()
                if not (v is None and k in props and k not in req)}
    if schema.get("type") == "array" and isinstance(data, list):
        return [unstrict(v, schema.get("items") or {}) for v in data]
    return data


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
    import loop  # imports engine itself
    return loop.vet_newer()


class Exec(BaseException):
    """Raised after a test's injected exec function returns (the real exec never does): unwinds run() without its close."""


def exec_in_place(argv):
    applog.close_all()
    os.execv(sys.executable, argv)


PUSH_UP_FAILS = 3  # network errors on the push while the probe says the network is up: the fault is not the network's to cure (a proxy, DNS)
# tl-bxk.13.16.4: a push that died of the network (lifesim-l4ow: curl 56 broken pipe, after a 17 min hook) is retried with a rest
TRANSIENT_PUSH = re.compile(r"curl \d+|Broken pipe|Connection (?:reset|timed out|refused)|Could not resolve host|early EOF|RPC failed|"
                            r"remote end hung up|SSL_ERROR|TLS|Operation timed out|Network is unreachable|"
                            r"Temporary failure in name resolution|error: 5\d\d|HTTP/\d(?:\.\d)? 5\d\d", re.I)
# tl-fsj: a configured check that fails because the tree lacks what the base's config names is the engine's, never a writer's amend
STALE_TREE = re.compile(r"does not contain recipe|This checkout has no |no recipe (?:named|called)|Justfile does not contain", re.I)


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


class Engine:
    def __init__(self, bead, wt, cfg, dry_run=False, verbose=True, store=None, route=seams.DelegateRoute(), clock=None, git=None,
                 stores=None, fresh=False):
        self.bead, self.wt, self.cfg, self.dry, self.verbose, self.store, self.router, self.repo = bead, wt, cfg, dry_run, verbose, store or tl.bd_store(), route, git
        self.stats = {"writes": 0, "rounds": 0, "reviews": 0, "replans": 0, "nodes": 0, "tests_added": 0, "tests_removed": 0,
                      "tokens_in": 0, "tokens_cached": 0, "tokens_out": 0}
        self.session, self.fresh = tl.session_id(), fresh
        self.leftovers = []
        self.look_notes, self.look_paths, self.bead_parent = [], [], ""  # tl-bxk.10.23
        self.look_filed = False
        self.look_unjudged, self.look_retried, self.shots_skipped = {}, set(), set()  # unjudged: item -> why
        self.unverified = []  # tl-bxk.10.28: items that land for the owner
        self.link_ok, self.link_bad, self.link_fn, self.link_tries = set(), {}, None, {}  # tl-bxk.7: links opened from this host (link_fn: a test's check)
        self.filed = []       # leftover titles filed by an earlier run on this checkpoint: a replan naming one again is no new bead
        self.stage_tree = ""  # the tree the current stage started from ("" = the task's base): the review's diff runs from here
        self.writer_said = "" # the writer's answers so far: a new file they name is meant (tl-bxk.10.24)
        self.accepted_new = []  # untracked files a review accepted into the commit
        self.amended = False  # a plan was amended or replanned: its first stage does not start at the task's base
        self.strays = []  # unaccepted untracked files moved to evidence/strays before the land gate (tl-bxk.10.24)
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
        self.pending_land_validation = ""  # a rejected push's failed checks still need an accepted fix
        self.denials = []     # commands refused to this bead's writers, across lanes and runs
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
        self.writer = {}  # backend -> thread/session id, so later rounds of a task resume the same writer
        self.writer_family = None  # the family of the last write: the verifier comes from another one when it can
        self.plan_assumed = False  # tl-ntp: the planner was sent back once to plan on assumptions
        self.plan_decided = False  # the planner was sent back once with the requirement that answers its question
        self.writer_fallback = False  # the writer's thread is a fallback: delegate's answer said so, or it went on
                                      # as a new thread after a lane_out the engine saw
        self.fallback_lane = ""  # that writer's first-choice lane, when known: delegate's first_lane, or the lane seen out
        self.verified = []  # the verifier's answer per unchecked item at land: in the trace and on the bead
        self.write_rounds = []  # per write round: resumed, input tokens, turns, prompt chars, context k, why fresh (a fix round's cost)
        self.last_summary = ""  # the last write's summary: a fresh writer is told it
        self.handoff = {"rounds": [], "seen_lows": []}  # tl-bxk.13.6: what the rounds did and what a review already noted
        self.salvaged = False  # a resume conflict was fixed in place, not by starting again (tl-7y6.2.19)
        self.lane_notes = []  # steps that ran on the writer's own family, with delegate's warning (tl: same_family, never a pause)
        self.rebase_resets = 0  # times the plan count started again after a rebase (checkpointed)
        self.look_done, self.look_prev = 0, []  # render rounds this stage; the last round's defects (tl-bxk.13.15)
        self.rendered_names, self.last_reqs, self.render_stale = set(), [], False  # the engine's own pictures this run, the last request
        self.taste = []  # [{id, title}] taste items for the owner-look bead
        self.scope = ""  # the bead's acceptance text: an unchecked item outside it is a follow-up, not a gap (tl-bxk.13.5)
        self.sessions = []  # every AI call of this run: the trace a later reflection reads (traces.jsonl)
        self.outcome, self.why, self.asked = "failed", "", False  # what result() tells the loop
        self.kind, self.fp, self.storm = None, "", ""  # the run's outcome.Kind (None: the verify-gaps ask), its fingerprint, a storm banner
        self.clock, self.disp = clock or SystemClock(), None
        self.retry_after = 0.0  # a pause for a lane: when delegate says it is back (epoch; 0 = unknown)
        self.landed_sha = ""  # set the moment the push goes through: whatever stops the run after it, the bead landed
        self.check_round = 0
        self.last_checks, self.checks_tree = None, ""  # the last engine check results and the tree they ran on (tl-bxk.10.25)
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
        self.log, self.steps, self.budget, self.calls, self.checklog = (getattr(self.ctx, k) for k in ("log", "steps", "budget", "calls", "checklog"))
        self.delegate_route(quiet=True)
        if self.reexec:
            self.restore_run()
        elif pause:
            self.restore_run("pause.json")
            self.log.note("back from a network pause: run %s goes on" % stem)

    # the budget's numbers, read and set as the engine's own (waited: seconds spent waiting for a shared resource, not budget_min's)
    t0, waited, labels, cost = (property(lambda self, k=k: getattr(self.budget, k), lambda self, v, k=k: setattr(self.budget, k, v))
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
            (self.run_dir / "plan.json").write_text(json.dumps(self.plan_data, indent=1))

    def blocked_for(self, why, kind, stop=None):
        """The Blocked a worker call ends its step with: `kind` is an outcome.Kind name; `stop` the stop that decided it."""
        err = Blocked(why, kind=oc.Kind[kind])
        err.stop = stop
        return err

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
        if not self.cfg.reflect or self.dry or not self.route or getattr(self, "stop_pending", False):
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
            res = dg.call(self.resolved, req, prompt, strict(SCHEMAS["reflect"]), self.router.runner(self.err_path, None, None, self.live("reflect"))).res
            saved = {k: v for k, v in self.stats.items() if k.startswith("tokens_")}
            self.calls.end(cid, "reflect", "reviewer", 1, res)
            self.stats.update(saved)  # the run's counts are the run's, as the Reflect comment says them
            if res.data is None or res.stop is not None:
                return None
            data = unstrict(res.data, SCHEMAS["reflect"])
            if validate(data, SCHEMAS["reflect"]):
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
        return REFLECT_PROMPT % (self.bead, fmt.clip(getattr(self, "bead_title", "") or "", 120), outcome, fmt.clip(why or "(none)", 600),
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
                reflection=getattr(self, "reflection", None), lane_notes=self.lane_notes, salvaged=self.salvaged)))
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
        total = sum(int(m.group(1)) for m in SLOT_WAIT.finditer(text or ""))
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
        return out

    plan_data = None  # the plan as accepted; an unsandboxed worker reads it from the run dir
    live_n = 0  # the number of delegate calls with a live file so far

    @cached_property
    def worker(self):
        return WorkerCall(self, Ops(schema_for, strict, unstrict, validate, summarize, read_only_command, self.blocked_for, stop_why,
                                    stop_say, self.after_call))

    def after_call(self, c, res):
        """A node's answer was taken: its detail lines, then what was odd about it."""
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

    def sh(self, cmd, timeout=3600, check=False, save=None, env=None, pin=False, idle=0):
        """A command: a string goes through bash with -e and pipefail (checks, profile commands), so a red command in a
        `;` list or a pipe fails it (lifesim-gfr.31.1: `just unity-check > log; ! grep ...` passed with unity-check
        red); `! cmd` and `cmd || true` still pass. A list runs as is (no quoting rules). pin=True: an engine git command, run
        with GIT_DIR/GIT_WORK_TREE of the slot; checks and gates run unpinned (they may run git on other repos)."""
        cid = self.log.next_id("m")
        self.log.emit(rec.CmdStart(id=cid, text=cmd if isinstance(cmd, str) else " ".join(cmd), cwd=str(self.wt)))
        # Its own process group, so a timeout stops the whole tree (dotnet build nodes, Unity) and not just the shell;
        # the worker env, so a check never inherits this launcher's Claude session.
        bash = shutil.which("bash") if isinstance(cmd, str) else None  # plans write bash
        run = [bash, "-e", "-o", "pipefail", "-c", cmd] if bash else cmd
        started = time.time()
        p, hold = sproc.popen_held(run, shell=isinstance(run, str), cwd=self.wt,  # tl-10s: see TermHold
                                   env=dict(sproc.current_env(), **(tl.pinned_env(self.wt) if pin else {}), **(env or {})),
                                   stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        self.hung, self.killed, self.kill_t, self.kill_why, self.last_event_t, self._event_frozen = False, False, 0.0, "", started, False
        self._event_lock = threading.Lock()
        try:
            hold.replay()
            if idle:
                out, rc = self.watch_output(p, timeout, idle)
            else:
                out, _ = p.communicate(timeout=timeout)
                rc = p.returncode
        except subprocess.TimeoutExpired as e:
            if not self.killed:
                self._freeze_check("timeout")
            sproc.stop_tree(p)
            out, _ = p.communicate()
            out = (e.output or b"") + out if idle else out  # the watched path read the output itself: keep what it collected
            out += b"\n(timed out after %g min: the engine stopped it and everything it started)" % round(timeout / 60, 2)
            rc = 124
        except BaseException:  # stopped: never leave a check (just check, Unity) running
            if not self.killed:
                self._freeze_check("interrupted")
            sproc.stop_tree(p)
            self.log.emit(rec.Kill(what="check" if idle else "command", why=self.kill_why, secs=round(self.kill_t - started), hung=bool(self.hung),
                                   started_t=started, last_event_t=self.last_event_t if idle else None, kill_t=self.kill_t, observed_t=self.kill_t))
            self.log.emit(rec.CmdEnd(id=cid, exit=-1, secs=round(time.time() - started, 1)))
            raise
        text = out.decode("utf-8", "replace")
        if self.killed:  # only a stop the engine performed; a command that exits 124 by itself is not a kill
            self.log.emit(rec.Kill(what="check" if idle else "command", why=self.kill_why, secs=round(self.kill_t - started), exit=rc,
                                   hung=bool(self.hung), started_t=started, last_event_t=self.last_event_t if idle else None, kill_t=self.kill_t,
                                   observed_t=self.kill_t))
        if save:
            Path(save).write_text(text, encoding="utf-8")
        tail = "\n".join(text.strip().splitlines()[-15:])
        self.log.emit(rec.CmdEnd(id=cid, exit=rc, secs=round(time.time() - started, 1), out=tail[-600:] if rc else ""))
        if check and rc:
            raise Blocked("failed: `%s` exit %d\n%s" % (cmd, rc, tail), kind=oc.Kind.FAULT_INFRA)
        return rc, tail

    def _freeze_check(self, why, idle=None, now=None):
        """Freeze the check's last observed activity and kill time before signaling or draining output. With `idle`,
        read the current activity and decide under the same lock, so a stale read cannot hide recent output."""
        with self._event_lock:
            if self._event_frozen:
                return False
            if idle is not None:
                now = time.time() if now is None else now
                if now - self.last_event_t <= idle:
                    return False
            self._event_frozen = True
            self.kill_t = time.time()
            self.last_event_t = min(self.last_event_t, self.kill_t)
            self.killed, self.kill_why = True, why
            return True

    def watch_output(self, p, timeout, idle):
        """Collect p's output until it ends. Stopped as hung when, for `idle` seconds, all three are flat: its output, any
        file written under the worktree (a check that redirects to a file is not silent), the CPU time of its process tree.
        Then the whole tree is stopped, self.hung is set and the exit is 124 (the output ends with the hang notice).
        `timeout` still applies, as TimeoutExpired carrying the output so far. The last observed activity and the kill
        time are frozen before the stop, so shutdown output and the synthetic hang notice cannot move the boundary."""
        chunks = []

        def mark(t):
            with self._event_lock:
                if not self._event_frozen:
                    self.last_event_t = max(self.last_event_t, t)

        def pump():
            while True:
                b = os.read(p.stdout.fileno(), 65536)
                if not b:
                    return
                chunks.append(b)
                mark(time.time())
        th = threading.Thread(target=pump, daemon=True)
        th.start()
        start = time.time()
        poll, nxt = min(60.0, max(0.3, idle / 4)), start
        seen = {"files": None, "cpu": {}}
        while th.is_alive():
            th.join(0.5)
            now = time.time()
            if now - start > timeout:
                self._freeze_check("timeout")
                sproc.stop_tree(p)
                th.join(5)
                raise subprocess.TimeoutExpired(p.args, timeout, output=b"".join(chunks))
            if th.is_alive() and now >= nxt:
                nxt = now + poll
                if cs.activity(self.wt, p.pid, seen):
                    mark(time.time())  # the scan may have taken longer than the idle limit
            if th.is_alive() and self._freeze_check("hung", idle=idle):
                self.hung = True
                sproc.stop_tree(p)
                th.join(5)
                chunks.append(b"\n(hung: no output, file writes or CPU for %g min; the engine stopped it and everything it started)"
                              % round(idle / 60, 2))
                return b"".join(chunks), 124
        p.wait()
        return b"".join(chunks), p.returncode

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
            for st in (getattr(self, "plan_data", None) or {}).get("stages") or []:
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

    def base_sha(self):
        """Where the task's work starts: an earlier run's commits on the task branch count as the task's diff."""
        return self.git("merge-base", self.cfg.base, "HEAD") or self.cfg.base

    def git(self, *a):
        return tl.git(*a, cwd=self.wt)

    # -- nodes
    def reset(self, bead):
        self.steps.begin("reset", "reset")
        branch = bead.metadata.get("branch") or "task/" + self.bead
        self.fetch(check=True)
        exclude = Path(self.git("rev-parse", "--path-format=absolute", "--git-common-dir")) / "info" / "exclude"
        if ".task/" not in (exclude.read_text() if exclude.exists() else ""):
            with open(exclude, "a") as f:
                f.write("\n.task/\n")
        exists = bool(self.git("rev-parse", "--verify", "-q", "refs/heads/" + branch))
        self.left_dirty = False
        if self.dirty_status():
            if self.git("symbolic-ref", "--short", "-q", "HEAD") != branch:
                raise Blocked("failed: worktree %s has uncommitted work of another branch" % self.wt, kind=oc.Kind.FAULT_SLOT)
            self.wip("left from an earlier run")
            self.left_dirty = True
        if exists and self.fresh:
            # tl-19i: --fresh starts the task again on the base: the old branch is kept as task/<id>-stale-<time>, never reset in place
            # and never checked out (lifesim-6pld ran --fresh on its old branch, 56 commits behind, and failed on a missing recipe)
            self.free_branch(branch)
            if self.git("rev-list", "--count", "%s..%s" % (self.cfg.base, branch)) not in ("", "0"):
                stale = "%s-stale-%s" % (branch, time.strftime("%Y%m%d-%H%M%S"))
                if self.git("rev-parse", "--verify", "-q", "refs/heads/" + stale):
                    stale += "-2"
                rc, tail = self.sh(["git", "branch", "-m", branch, stale], pin=True)
                if rc:
                    raise Blocked("failed: --fresh could not keep the old branch aside as %s: %s" % (stale, tail.strip()[-200:]), kind=oc.Kind.FAULT_SLOT)
                self.log.note("--fresh: the old branch %s is kept as %s; the task starts again on %s" % (branch, stale, self.cfg.base))
                self.comment("Fresh (engine): --fresh: the earlier work on %s is kept as the branch %s; the task starts again on %s." % (
                    branch, stale, self.cfg.base))
            exists = False
        if exists:
            self.free_branch(branch)
            self.sh(["git", "checkout", "-q", branch], check=True, pin=True)
        else:
            self.sh(["git", "checkout", "-q", "-B", branch, self.cfg.base], check=True, pin=True)
        for old in self.task_dir.iterdir():  # earlier runs' files are no facts; only the writer's evidence carries over
            if old.name != "evidence":
                shutil.rmtree(old) if old.is_dir() else old.unlink()
        self.export_brief()
        self.branch = branch
        return branch

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
                        branch, path), kind=oc.Kind.FAULT_SLOT)
                tl.git("checkout", "-q", "--detach", cwd=path)
                self.log.note("%s was checked out in %s: detached it there to resume here" % (branch, path))

    def export_brief(self):
        """The task as workers read it: the bead's own text and the people's comments, never the engine's own records
        (plans, reviews, reflects pile up on every rerun: 40 of lifesim-vbo's 45 KB brief)."""
        bead, comments = tl.peek(self.store, self.bead) or Bead(id=self.bead, title="", status=""), self.store.comments(self.bead)
        text = brief_digest(bead, comments) + linked_text(self.bead, bead, comments, lambda i: tl.peek(self.store, i), self.store.comments)
        said = self.answered_words()  # the owner's typed answer is no comment: the brief carries it for the workers
        if said and self.answered:
            text += "\n## Owner answer (to ask %s)\n%s\n" % (self.answered.id, said)
        self.snap = bead_snapshot(bead, comments)
        (self.run_dir / "brief.md").write_text(text, encoding="utf-8")
        self.brief_file.write_text(text, encoding="utf-8")  # a resumed writer is told where to re-read it (tl-bxk.10.29)
        # the hash is what tells a rerun the owner changed something: the engine's own close line and labels are not that
        ours = [x for x in (self.cfg.pick_label, self.cfg.needs_info_label) if x]
        self.brief_hash = hashlib.sha1(brief_digest(bead, comments, owner_only=True, ignore=ours).encode("utf-8")).hexdigest()
        kb = len(text.encode("utf-8")) / 1024
        if kb > float(self.cfg.brief_kb):
            self.warn("the brief is %.0f KB (over %s KB): the bead may be too big for one task" % (kb, self.cfg.brief_kb))

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
        ran = [c["cmd"] for c in checks if c["exit"] == 0]
        names = [" ".join(x.split()).lower() for x in [self.cfg.gate] + ran if x.strip()]
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
        plan = getattr(self, "plan_data", None) or {}
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

    def backed_by_leftover(self, what):
        """True when an owner-review follow-up bead for this item is already in the leftovers (tl-bxk.13.1): the owner sees
        it there, so it need not stop the land as well (lifesim-iqad twice)."""
        mine = word_set(what)
        if len(mine) < 3:
            return False
        for lo in self.leftovers:  # the beads the engine will file
            t, w = " ".join(str(lo.get("title") or "").split()), str(lo.get("why") or "")
            if not OWNERISH.search(t):
                continue
            theirs = word_set(t + " " + w)
            if len(mine & theirs) >= max(4, int(0.5 * len(mine))):
                return True
        return False

    def case_checks(self):
        return [c["check"] for c in (getattr(self, "plan_data", None) or {}).get("cases") or []
                if c.get("check", "").strip() and c.get("class", "test") == "test" and c.get("proved_by", "check") in ("check", "stage")]

    def cases_of(self, cls):
        """The criteria of the plan's cases of one class (look-objective, taste)."""
        return [c["criterion"] for c in (getattr(self, "plan_data", None) or {}).get("cases") or [] if c.get("class") == cls]

    def cases_text(self):
        cases = (getattr(self, "plan_data", None) or {}).get("cases") or []
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

    def brief_text(self):
        """Inline, never a path: a worker's file tools reach only its worktree (delegate 0.23), and the engine's files
        live outside it so the worker cannot change them."""
        return (self.run_dir / "brief.md").read_text(encoding="utf-8")

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

    def plan_text(self):
        return json.dumps(getattr(self, "plan_data", None) or {}, indent=1)

    def seen_now(self):
        """What a writer session holds of the task once it has answered: the brief's and the plan's hash."""
        h = lambda t: hashlib.sha1(t.encode("utf-8")).hexdigest()  # noqa: E731
        return [h(self.brief_text()), h(self.plan_text())]

    def fresh_above_k(self, family):
        v = self.cfg.write_fresh_above_k
        if isinstance(v, dict):
            key = "codex" if family == "openai" else family
            v = v.get(key, FRESH_ABOVE_K.get(key, 0))
        return float(v or 0)

    def drop_big_writer(self, boundary=False):
        """tl-bxk.10.29: -> why a new writer starts, or "". The session's last context is above write_fresh_above_k for its
        family: it is not resumed (every later turn would carry it all); the next write is a new session. At a stage
        boundary the lower write_fresh_stage_k applies (tl-bxk.13.7): lifesim-yxbb.9 carried 276K into stage 2 (11.7M tokens)."""
        ref, ctx = self.writer.get("delegate"), self.writer.get("ctx")
        limit = self.fresh_above_k(self.writer_family or "")
        if boundary and limit:  # write_fresh_above_k 0 means never: the stage limit does not override it
            b = float(self.cfg.write_fresh_stage_k or 0)
            limit = min(limit, b) if b else limit
        if not ref or not ctx or not limit or ctx <= limit:
            return ""
        self.writer.pop("delegate")
        why = "session at %dk" % ctx
        self.log.note("fresh writer: %s (above %gk for %s)" % (why, limit, self.writer_family))
        return why

    def done_so_far(self):
        """What a fresh writer is told its predecessor did: the diff --stat of the stage so far, and its last summary."""
        tree = self.tree_hash()
        stat = tl.git("diff", "--stat", self.stage_tree or self.base_sha(), tree, cwd=self.wt) if tree else ""
        return DONE_SO_FAR % ((stat or "(no file changed yet)").strip(), (self.last_summary or "(none)").strip(),
                              self.rounds_text(last=4) or "(none)\n")

    def stages_done_text(self):
        """What a fresh writer starting a later stage is told: the accepted stages and their diff from the task's base."""
        tree = self.tree_hash()
        stat = tl.git("diff", "--stat", self.base_sha(), tree, cwd=self.wt) if tree else ""
        goals = "".join("- %s\n" % g for g in self.done) or "(none)\n"
        return STAGES_DONE % (goals, (stat or "(no file changed yet)").strip(), self.rounds_text(last=4) or "(none)\n")

    def write_delta(self, n, goal, files, checks, where, feedback, tail):
        """The prompt of a resumed writer: what changed since its session last saw the brief and the plan. None when the brief
        changed (the owner edited it, an answer came in): that session gets the whole prompt again."""
        seen = self.writer.get("seen")
        if not seen or seen[0] != self.seen_now()[0]:
            return None
        plan = "The plan is unchanged." if seen[1] == self.seen_now()[1] else "The plan changed:\n<plan>\n%s\n</plan>" % self.plan_text()
        return WRITE_RESUME_PROMPT.format(brief=self.brief_file, plan=plan, n=n, goal=goal, files=files, checks=checks,
                                          where=where, feedback=feedback) + tail

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
            try:
                plan = json.loads((tl.config_dir() / "checkpoints" / ("%s.json" % lock["bead"])).read_text()).get("plan") or {}
            except (OSError, ValueError):
                plan = {}
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

    SALVAGE_MAX_FILES = 10  # tl-7y6.2.19: a resume conflict in more files than this starts again; fewer is fixed

    def rebase_onto_base(self, salvage=False):
        """tl-bxk.13.8: a branch resumed from an earlier run is rebased onto the latest base before it is planned or
        re-planned, so the plan and the engine's checks see what main has now (lifesim-ov3w: a gate check named a recipe the
        branch's base lacked, three plans in 11 min). -> "rebased" (the plan count starts again: the earlier plans were made on
        another base), "conflict" (the branch work does not fit main: the caller starts again, tl-19i), "conflict-fixable" (salvage on: the
        rebase stopped on at most SALVAGE_MAX_FILES files and is left running for the caller's fix(conflict)), or "".
        tl-7y6.2.19: more than one commit on the branch (the wip commits) is squashed first, as finish() does, so one conflict
        is fixed once. The branch is left as it was in the conflict (squash undone), and when there is nothing to do."""
        if self.dry or self.dirty_status():  # (the base-ignored files of an old branch, Unity's logs, are no reason not to rebase)
            return ""
        behind = self.git("rev-list", "--count", "HEAD..%s" % self.cfg.base)
        if behind in ("", "0"):
            return ""
        orig = self.git("rev-parse", "HEAD")
        old_parent = self.git("rev-parse", "-q", "--verify", "HEAD~1") if getattr(self, "left_dirty", False) else ""
        self.squashed = False
        mb = self.git("merge-base", "HEAD", self.cfg.base)
        if mb and self.git("rev-list", "--count", "%s..HEAD" % mb) not in ("", "0", "1"):  # the wip commits become one, like finish()
            rc, tail = self.sh(["git", "reset", "-q", "--soft", mb], pin=True)
            if not rc:
                rc, tail = self.sh(["git", "commit", "-q", "--no-verify", "--allow-empty", "-m", "wip (%s): earlier work, squashed" % self.bead], pin=True)
            if rc:  # the branch stays as it was
                self.sh(["git", "reset", "-q", "--hard", orig], pin=True)
            else:
                self.squashed = True
                self.log.note("squashed the branch's wip commits into one before rebasing")
        self.rebase_orig, self.rebase_pre = orig, [x for x in (orig, old_parent) if x]
        rc, tail = self.sh(["git", "rebase", "-q", self.cfg.base], pin=True)
        if rc:
            unmerged = self.git("diff", "--name-only", "--diff-filter=U").split()
            if salvage and unmerged and len(unmerged) <= self.SALVAGE_MAX_FILES:
                self.salvage_tail = "Conflicted files: %s\n%s" % (", ".join(unmerged), tail)
                return "conflict-fixable"
            self.sh(["git", "rebase", "--abort"], pin=True)
            if self.squashed:
                self.sh(["git", "reset", "-q", "--hard", orig], pin=True)
            self.warn("the task branch could not be rebased onto %s before planning: %s"
                      % (self.cfg.base, tail.strip().splitlines()[-1][:200] if tail.strip() else "conflict"))
            return "conflict"
        self.follow_checkpoint()
        self.log.note("rebased the task branch onto the latest %s (%s commits behind) before planning" % (self.cfg.base, behind))
        return self.rebased_plan_count()

    def follow_checkpoint(self):
        """The checkpoint's head follows a rebase (or squash), or the next resume reads this as an edit from outside."""
        try:
            ck = json.loads(self.checkpoint_path().read_text())
            if isinstance(ck, dict) and ck.get("head") in self.rebase_pre:
                # unsquashed, the wip commit reset() made on top of the checkpoint's head is still on top of it
                above = not self.squashed and len(self.rebase_pre) > 1 and ck["head"] == self.rebase_pre[1]
                ck["head"] = self.git("rev-parse", "HEAD~1" if above else "HEAD")
                self.checkpoint_path().write_text(json.dumps(ck, indent=1))
        except (OSError, ValueError):
            pass

    def salvage_resume_conflict(self):
        """tl-7y6.2.19: the resume rebase stopped on a few files: one fix(conflict) round (markers and build only) instead of
        throwing the branch away. -> "rebased" (the run record shows salvaged: true), or "conflict": the fix did not work, the
        branch is back as it was and the caller starts again."""
        fixes, ok = self.fixes, False
        try:
            d = self.fix("conflict", self.salvage_tail, resume=True)
            ok = not self.git("diff", "--name-only", "--diff-filter=U")  # (a fix the review sent back still continued the rebase: the stage checks it again)
            if d != "accept":
                self.warn("resume: the conflict fix did not pass its checks and review; the stage goes on from it")
        except FixFailed as e:
            self.warn("the resume conflict fix failed: %s" % str(e).splitlines()[0][:200])
        finally:
            self.fixes = fixes  # the land's two fix rounds are its own
        gd = Path(self.git("rev-parse", "--absolute-git-dir") or ".")
        if (gd / "rebase-merge").exists() or (gd / "rebase-apply").exists():
            self.sh(["git", "rebase", "--abort"], pin=True)
        if not ok:
            self.sh(["git", "reset", "-q", "--hard", self.rebase_orig], pin=True)  # the work as it was, for start_again_on_base
            return "conflict"
        self.salvaged = True
        self.follow_checkpoint()
        self.log.note("resume conflict fixed in place instead of starting again (salvaged)")
        return self.rebased_plan_count()

    def rebased_plan_count(self):
        if self.planned and self.rebase_resets < MAX_REBASE_RESETS:
            # tl-19i: plans made on the old base say nothing about this one (lifesim-ov3w counted 2). At most twice per bead:
            # a bead whose gate is red for a real reason must still reach the limit while main keeps moving
            self.log.note("the plan count starts again: %d earlier plan%s were made on another base" % (
                self.planned, "" if self.planned == 1 else "s"))
            self.plan_log.append({"mode": "rebase", "counted": False, "why": "the branch moved to a new base; %d plan(s) before it do not count" % self.planned})
            self.planned, self.rebase_resets = 0, self.rebase_resets + 1
        return "rebased"

    def start_again_on_base(self, why):
        """tl-19i: the branch's earlier work conflicts with main, so it cannot go on. It is kept under another name; the task
        starts again on the base with a fresh plan (the owner's answer is in the bead's comments, which the planner reads),
        and nothing so far counts toward the re-plan limit."""
        branch = self.git("symbolic-ref", "--short", "-q", "HEAD")
        if not branch or branch != getattr(self, "branch", branch):
            self.warn("resume conflict, but HEAD is not the task branch (%s): the branch stays as it was" % (branch or "detached"))
            return False
        stale = "%s-stale-%s" % (branch, time.strftime("%Y%m%d-%H%M%S"))
        if self.git("rev-parse", "--verify", "-q", "refs/heads/" + stale):
            stale += "-2"
        rc, tail = self.sh(["git", "branch", "-m", branch, stale], pin=True)
        if rc:  # never reset a branch whose work could not be kept
            self.warn("resume conflict, but the branch could not be kept aside (%s): it stays as it was" % tail.strip()[-160:])
            return False
        self.sh(["git", "checkout", "-q", "-B", branch, self.cfg.base], pin=True, check=True)
        self.drop_checkpoint()
        self.old_plan, self.amend_why, self.amend_text, self.replan_first = None, "", "", False
        self.plan_data, self.plan_summary = None, ""  # verify_answer stays: the owner's word still goes to the planner
        self.done, self.accepted, self.unchecked, self.plan_log, self.planned = [], [], [], [], 0
        self.amended, self.stage_tree, self.writer, self.writer_family = False, "", {}, None
        self.writer_fallback, self.fallback_lane, self.denials, self.fixes, self.replans = False, "", [], 0, 0
        self.unverified, self.accepted_new, self.writer_said, self.last_summary = [], [], "", ""
        self.look_paths, self.look_notes, self.look_unjudged = [], [], {}
        self.rendered_names, self.last_reqs, self.render_stale = set(), [], False
        self.handoff = {"rounds": [], "seen_lows": []}
        self.steps.move("plan", "resume_conflict", "the branch's earlier work conflicts with %s: kept as %s, planning fresh. %s" % (
            self.cfg.base, stale, why[:160]))
        self.log.note("resume conflict: %s kept as %s; the task starts again on %s" % (branch, stale, self.cfg.base))
        self.comment("Resume (engine): the earlier work on %s conflicts with %s. It is kept as the branch %s; the task starts again on "
                     "%s with a fresh plan." % (branch, self.cfg.base, stale, self.cfg.base))
        return True

    # -- tl-bxk.13: the handoff record (docs/design/stages.md section 5): what a stage after this one needs to know
    def deferred_items(self):
        """[(title, why)]: the follow-up work the plan and the reviews already set aside; the engine files each at land."""
        out, seen = [], set()
        for lo in ((getattr(self, "plan_data", None) or {}).get("leftovers") or []) + self.leftovers:
            t = " ".join(str(lo.get("title") or "").split())
            if t and t not in seen:
                seen.add(t)
                out.append((t, " ".join(str(lo.get("why") or "").split())))
        return out

    def deferred_text(self):
        items = self.deferred_items()
        steps = [e for e in self.ledger() if e["proved_by"] == "engine_step"]
        out = ""
        if items:
            lines = "".join("- %s%s\n" % (t[:160], (": " + w[:160]) if w else "") for t, w in items[:10])
            out += ("\nAlready set aside (the plan or an earlier review put each in leftovers; the engine files each as a follow-up "
                    "bead at land, and nobody here can run bd). Never list one as unmet, as a finding or as unchecked, nor ask "
                    "the owner about it:\n" + lines)
        if steps:
            out += ("\nThe engine does these itself, after the stages (the plan's ledger). Never list one as unmet, as a "
                    "finding or as unchecked:\n" + "".join("- %s (%s)\n" % (e["criterion"][:160], e["via"][:60] or "engine step") for e in steps[:8]))
        return out

    # -- tl-bxk.13.16.1: the ledger. The plan says how each criterion is proved; review and verify go by it, not by wording.
    def ledger(self):
        """[{criterion, proved_by, via, text}]: what the plan defers (leftover) or leaves to the engine (engine_step)."""
        out = []
        for c in (getattr(self, "plan_data", None) or {}).get("cases") or []:
            if c.get("proved_by") in ("leftover", "engine_step"):
                out.append({"criterion": c["criterion"], "proved_by": c["proved_by"], "via": c.get("via") or "",
                            "text": "%s %s" % (c["criterion"], c.get("via") or "")})
        for t, _ in self.deferred_items():
            out.append({"criterion": t, "proved_by": "leftover", "via": t, "text": t})
        return out

    def ledger_match(self, what):
        """The ledger entry an item is about: most of the entry's words are the item's (3 at least)."""
        mine = word_set(what)
        if len(mine) < 3:
            return None
        filing = bool(FILING_WORDS.search(what))  # an item about follow-ups, beads, records: the ledger's own subject
        for e in self.ledger():
            theirs = word_set(e["text"])
            shared = len(mine & theirs)
            # a claim about the code that merely shares words with a deferred item is not that item: unless the item is about
            # filing, it must be a near-paraphrase (60% of both sides, 4 words at least)
            if shared >= max(3, int(0.6 * len(theirs) + 0.99)) and (filing or (shared >= 4 and shared >= 0.6 * len(mine))):
                return e
        return None

    def ledger_route(self, what):
        e = self.ledger_match(what)
        return e["proved_by"] if e else ""

    def ledger_fill(self, data):
        """A case deferred in the ledger whose leftover the plan forgot to list: the engine lists it, so the work is filed."""
        have = {" ".join(lo["title"].split()) for lo in data.get("leftovers") or []} | {t for t, _ in self.deferred_items()}
        for c in data.get("cases") or []:
            if c.get("proved_by") != "leftover":
                continue
            via = " ".join((c.get("via") or "").split())
            if via and any(word_set(via) and len(word_set(via) & word_set(t)) >= 0.6 * len(word_set(via)) for t in have):
                continue
            title = (via or c["criterion"])[:120]
            data.setdefault("leftovers", []).append({"title": title, "why": "Deferred by the plan: " + c["criterion"]})
            have.add(title)
            self.log.note("the ledger defers a criterion the leftovers did not list; listed: %s" % title[:160])

    def seen_lows_text(self):
        lows = self.handoff["seen_lows"]
        if not lows:
            return ""
        return ("\nLow findings earlier reviews of this task already noted (do not list one again unless the code under it "
                "changed):\n" + "".join("- %s\n" % x for x in lows[-10:]))

    def rounds_text(self, last=6, each=300, cap=HANDOFF_CAP):
        """The newest rounds first kept, oldest dropped when the text would pass `cap` characters."""
        out, size = [], 0
        for r in reversed(self.handoff["rounds"][-last:]):
            line = "- %s, round %s (%s)" % (r["stage"], r["round"], r["kind"])
            if r.get("writer"):
                line += "; the writer said: %s" % r["writer"][:each]
            if r.get("open"):
                line += "; sent back: " + " | ".join(r["open"])
            line = line[:each + 400]
            if out and size + len(line) > cap:
                break
            out.append(line)
            size += len(line) + 1
        return ("\n".join(reversed(out)) + "\n") if out else ""

    def note_round(self, name, rnd, kind, writer="", open_items=()):
        self.handoff["rounds"].append({"stage": name, "round": rnd, "kind": kind, "writer": " ".join(str(writer).split())[:300],
                                       "open": [" ".join(str(x).split())[:200] for x in list(open_items)[:6]]})
        self.handoff["rounds"] = self.handoff["rounds"][-12:]
        self.save_handoff()

    def note_lows(self, findings):
        for f in findings:
            if f["severity"] == "low":
                x = ("%s:%s %s" % (f["file"], f["line"], " ".join(str(f["fix"]).split())))[:160]
                if x not in self.handoff["seen_lows"]:
                    self.handoff["seen_lows"].append(x)
        self.handoff["seen_lows"] = self.handoff["seen_lows"][-20:]
        self.save_handoff()

    def save_handoff(self):
        try:
            (self.run_dir / "handoff.json").write_text(json.dumps(dict(
                self.handoff, deferred=[{"what": t, "why": w} for t, w in self.deferred_items()],
                filed=self.filed), indent=1))
        except OSError:
            pass

    def run(self):
        return self.run_once()

    def run_once(self):
        outcome, why, sha, spec, kind = "failed", "", "", None, oc.Kind.FAULT_ENGINE
        hb = Lease(self.store, self.bead, os.environ.get("TASK_LOOP_SLOT_BEAD", ""))
        try:
            self.prev_ck = (json.loads(self.checkpoint_path().read_text()) or {}).get("run") or ""
        except (OSError, ValueError, AttributeError):
            self.prev_ck = ""
        try:
            if getattr(self, "stop_pending", False):  # stopped during the claim (run_bead): close it as stopped
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
            self.reset(bead)
            self.budget.labels = list(bead.labels)
            self.check_ask()
            self.grant_cap()
            written = self.answered_words() if self.answered and self.answered.ask_class == AskClass.MISSING_CRITERIA else ""
            if not has_criteria(bead) and not written:
                raise Blocked("ticket: the bead has no acceptance criteria", askspecs.missing_criteria(), kind=oc.Kind.ASK_TICKET)
            self.scope = acceptance_text(bead) or written
            plan, i, state = self.resume_point()
            self.log_run()
            # tl-fsj: the configured checks come from the base's config, so the tree they run on must have what the base has; every
            # resume rebases first, a plan to make or a stage to go on with (lifesim: 8 beads parked on 'just fmt-check-changed')
            at_land = plan is not None and (i >= len(plan["stages"]) or (state or {}).get("fix"))  # a conflict there is the writer's fix round
            moved = "" if at_land else self.rebase_onto_base(salvage=plan is not None)  # (no plan: nothing accepted to salvage)
            if moved == "conflict-fixable":
                self.plan_data = self.plan_data or plan
                moved = self.salvage_resume_conflict()
            if moved == "conflict" and self.start_again_on_base("Its work: %s" % (self.git("log", "--oneline", "-n", "3", "%s..HEAD" % self.cfg.base) or "").replace("\n", "; ")):
                plan, i, state = None, 0, None
            elif moved == "rebased" and plan is not None:
                self.stage_tree = ""  # the stage's diff starts at the base now: the rebase moved what it was measured from
            if plan is None:  # a move here loses nothing: the new image reads the same checkpoint (or none) and plans
                self.safe_point("plan")
            if plan is None:
                plan, i, state = self.plan(again=self.replan_first), 0, None
            while i < len(plan["stages"]):
                d = self.stage(plan, i, state)
                state = None
                if d == "replan":
                    if self.pending_land_validation:
                        self.pending_land_validation += "\n" + self.stuck_why
                        self.save_checkpoint(stage=i, rounds=0, n=0, feedback="", step="write")
                    self.replans += 1
                    self.stats["replans"] = replans = self.replans
                    if replans > int(self.cfg.max_replans) + self.extra:
                        raise self.cap_blocked("stage %d stuck after %s rounds. What failed: %s" % (
                            i + 1, self.cfg.max_rounds, self.stuck_why[:600]))
                    self.accepted = []
                    plan = self.plan(again=True)
                    i = 0
                    continue
                self.accepted.append(i)
                self.done.append(plan["stages"][i]["goal"])
                i += 1
                if i == len(plan["stages"]):
                    self.pending_land_validation = ""  # every recovery stage passed checks and review
                self.save_checkpoint(stage=i, rounds=0, n=0, feedback="", step="write" if i < len(plan["stages"]) else "land")
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
            sha = self.finish(bead)
            outcome = "landed" if sha else "done"
            kind = oc.Kind.LANDED if sha else oc.Kind.DONE
            if sha:
                self.file_owner_look()  # before the checkpoint goes: a crash from here on still files it on resume
            self.drop_checkpoint()
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
                    self.close(outcome, why, sha, spec, kind)
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
            self.steps.move("verify" if gaps else "land", "not_a_check", "%d item%s name a tool the repo does not use" % (
                n_drop, "" if n_drop == 1 else "s"))
            if not gaps:
                counts = ", ".join("%d %s" % (sum(x["verdict"] == k for x in self.verified), k) for k in VERDICTS)
                self.log.note("verify: before land: %s" % counts)
                self.comment("Verify (engine): what the workers could not check, before land: " + "; ".join(
                    "%s: %s, %s" % (x["verdict"], x["what"], '"%s"' % x["evidence"]) for x in self.verified))
                return []
        gaps, failed = self.engine_settles(gaps)  # tl-bxk.10.19: what the engine proves itself is never asked
        gaps = self.engine_steps(gaps)
        items = "".join("%d. %s (%s)\n" % (n, u["what"], u["kind"]) for n, u in enumerate(gaps, 1))
        items += self.look_verify(gaps)
        d = {"items": []}
        if gaps:
            try:
                d, _ = self.ai("verify", "%d unchecked item(s) before land" % len(gaps), VERIFY_PROMPT.format(
                    brief=self.brief_text(), work=self.work_summary(), evidence=self.evidence_dir,
                    checks=self.checks_evidence(), where=self.where("verify"), items=items) + self.deferred_text(),
                    writer_family=self.writer_family, items=len(gaps), at=(self.at_stage, 0, 0))
            except Blocked as b:
                if b.kind in (oc.Kind.FAULT_BAD_REQUEST, oc.Kind.PAUSE_NETWORK, oc.Kind.PAUSE_KILLED):
                    raise  # tl-bxk.10.31: the request is malformed for every bead; the network and a kill resume this step, they do not skip it
                # no verifier now is no reason to land unchecked: the owner checks them, as before
                self.warn("could not self-verify before land, the owner checks every item: %s" % b.why[:300])
                return gaps + failed
            if self.last_flag == "same_family":
                self.warn("the check before land is from the writer's own model family (no other lane was free)")
        said = {}
        for a in d["items"]:
            said.setdefault(a["n"], a)
        still, wrong = [], list(failed)
        for n, u in enumerate(gaps, 1):
            a = said.get(n) or {"verdict": "open", "evidence": "", "why": "the verifier did not answer it"}
            v, why = a["verdict"], a["why"]
            if v == "settled" and not a["evidence"].strip():
                v, why = "open", "settled without quoted evidence"
            if self.is_look(u):
                v, a, why = self.look_verdict(u, v, a, why)
            kind, source = self.resolve_kind(u, a)
            u = dict(u, kind=kind, source=source)
            route = ""
            if v == "open":
                v, a, why, route = self.route_open(u, a, why)
            self.verified.append({"what": u["what"], "kind": u["kind"], "verdict": "open" if route == "unverified" else v,
                                  "evidence": a["evidence"], "why": why})
            if route == "proof":
                wrong.append(dict(u, why=why, proof_round=True))
            elif v != "settled" and route != "unverified":
                (wrong if v == "wrong" else still).append(dict(u, why=why))
        counts = ", ".join("%d %s" % (sum(x["verdict"] == k for x in self.verified), k) for k in VERDICTS)
        self.log.note("verify: before land: %s" % counts)
        self.steps.outcome("wrong" if wrong else "open" if still else "settled", counts)
        self.comment("Verify (engine): what the workers could not check, self-verified read-only before land: " + "; ".join(
            "%s: %s, %s" % (x["verdict"], x["what"], ('"%s"' % x["evidence"]) if x["verdict"] == "settled" else x["why"])
            for x in self.verified))
        if not wrong:
            if still:
                self.steps.move("ask", "verify_open", "%d item%s only the owner can decide" % (
                    len(still), "" if len(still) == 1 else "s"))
            elif self.unverified:
                self.steps.move("land", "unverified", "%d item%s land unverified, for the owner" % (
                    len(self.unverified), "" if len(self.unverified) == 1 else "s"))
            else:
                self.steps.move("land", "verified", counts)
            return still
        if self.fixes >= int(self.cfg.max_fix_rounds):
            self.steps.move("ask", "verify_wrong", "%d found wrong, no fix round left" % len(wrong))
            return still + [dict(u, why="found wrong: %s; no fix round left" % u["why"]) for u in wrong]
        self.steps.move("fix", "verify_wrong", "%d found wrong: %s" % (len(wrong), "; ".join(u["why"] for u in wrong)))
        pending = wrong
        while True:
            # the pending items stay unchecked in the fix's checkpoint: a fix round that pauses resumes at land and verifies
            # them again, never lands them; the fix's review adds what it leaves unproven
            self.unchecked = [u for u in self.unchecked if u["kind"] not in UNCHECKED_KINDS] + still + pending
            before = len(self.unchecked)
            pending = [dict(u, why=u.get("why") or "add a test or check that proves: %s" % u["what"]) for u in pending]
            done = self.fix("verify", "".join("- %s: %s\n" % (u["what"], u["why"]) for u in pending))
            fixed = {u["what"] for u in pending}
            self.unchecked = [u for u in self.unchecked[:before] if u["what"] not in fixed] + self.unchecked[before:]  # what the fix's review added stays
            left = [u for u in self.unchecked if u["kind"] in UNCHECKED_KINDS]
            if done != "accept":
                left += [dict(u, why="found wrong: %s; the fix round did not pass" % u["why"]) for u in pending]
            left = self.route_left(left)
            pending = [u for u in left if u.get("proof_round")]
            if not pending:
                return left
            if self.fixes >= int(self.cfg.max_fix_rounds):  # a bead with an unproven checkable item never lands
                raise self.proof_stuck(pending)
            still = [u for u in left if not u.get("proof_round")]
            self.steps.move("fix", "verify_unproven", "%d still unproven after the fix round" % len(pending))

    def proof_stuck(self, items):
        return Blocked("the check before land: nothing proves %s after %d fix rounds: it needs the owner's hint" % (
            "; ".join(u["what"] for u in items)[:600], int(self.cfg.max_fix_rounds)),
            askspecs.unproven([u["what"] for u in items], int(self.cfg.max_fix_rounds)), kind=oc.Kind.ASK_STUCK)

    def diff_text(self):
        tree = self.tree_hash()
        return (tl.git("diff", self.base_sha(), tree, cwd=self.wt) if tree else "") or ""

    def names_code(self, what):
        """True when the item names something a check can reach: a repo path, a code or config file, or a code symbol
        (CamelCase or snake_case) that is in the task's diff."""
        text = re.sub(r"https?://\S+", " ", what)
        files = set(tl.git("ls-files", cwd=self.wt).splitlines()) | set(self.changed_paths())
        names = {Path(f).name for f in files}
        for t in re.findall(r"[\w][\w./-]*[\w]", text):
            if t in files or t in names or CODE_EXT.search(t):
                return True
        syms = {t for t in SYMBOL.findall(text.replace(".", " "))}
        if syms:
            diff = self.diff_text()
            return any(x in diff for x in syms)
        return False

    def engine_does(self, what):
        """True when the item names an action the engine will in fact perform for this bead."""
        w = " ".join(what.split())
        if ENGINE_FILES.search(w) or ENGINE_BEADS.search(w):  # tl-bxk.13.1: "file beads" is the same step as "file follow-ups"
            return bool(self.leftovers or ((getattr(self, "plan_data", None) or {}).get("leftovers")))
        if ENGINE_SHOTS.search(w):
            vp = self.visual_cfg()
            return bool(vp and visual_hit(vp, self.changed_paths()))
        return bool(ENGINE_LANDS.search(w) or ENGINE_CLOSES.search(w))

    def resolve_kind(self, u, a):
        """(kind, source) for an item: the verifier's kind (it read the code) when it is as strict as the writer's, else the
        writer's. An engine_step the engine will not do, an external_fact with no source, and a taste or external_fact that
        names a path, a code file or a symbol in the diff is checkable, whatever its label."""
        old = u["kind"]
        new = a.get("kind") if a.get("kind") in UNCHECKED_KINDS else old
        if KIND_RANK.get(new, 2) < KIND_RANK.get(old, 2):
            new = old
        source = (a.get("source") or u.get("source") or "").strip()
        if new == "engine_step" and not self.engine_does(u["what"]):
            new = "checkable"
        elif new in ("external_fact", "taste") and (self.names_code(u["what"]) or (new == "external_fact" and not source)):
            new = "checkable"
        return new, source

    def engine_steps(self, gaps):
        """tl-bxk.10.28: an item the writer calls an engine step is settled here, no verifier call, only when it names an
        action the engine will do for this bead (engine_does): lifesim-yxbb.7 and lifesim-fld.25.16 parked on 'the engine
        files them'. A claim about the result ('the beads cover all nine objects') goes to the verifier."""
        out = []
        for u in gaps:
            if u["kind"] == "engine_step" and self.engine_does(u["what"]):  # the writer's own typing of it, when it names the step
                self.settle_engine_step(u)
                continue
            route = self.ledger_route(u["what"])
            if route == "engine_step":  # tl-bxk.13.16.1: the plan's ledger says the engine does it
                self.settle_engine_step(u)
                continue
            if route == "leftover":
                self.add_unverified(u, "the plan defers it to a follow-up bead")
                continue
            if u["kind"] in ("owner_decision", "external_fact", "taste") and self.backed_by_leftover(u["what"]):
                self.add_unverified(u, "a follow-up bead for the owner is filed at land")
            elif u["kind"] in ("engine_step", "external_fact", "taste"):
                out.append(dict(u, kind=self.resolve_kind(u, {"kind": u["kind"], "source": "x"})[0]))  # source is the verifier's to give
            else:
                out.append(u)
        return out

    def settle_engine_step(self, u):
        self.verified.append({"what": u["what"], "kind": u["kind"], "verdict": "settled", "why": "the engine does this at land",
                              "evidence": "the engine does this at land"})

    def route_open(self, u, a, why):
        """tl-bxk.10.28: where an item the verifier left open goes, by its (resolved) kind: (verdict, answer, why, route).
        An engine step is settled; a checkable item goes to the writer for a test (a fix round, counted in max_fix_rounds;
        none left: the bead is stuck, never landed); an item no check can prove lands for the owner (route 'unverified');
        an owner decision, or an old kind, is asked."""
        k = u["kind"]
        route = self.ledger_route(u["what"])
        if route == "leftover":
            self.add_unverified(u, why or "the plan defers it to a follow-up bead")
            return "open", a, why, "unverified"
        if k == "engine_step" or route == "engine_step":
            return "settled", dict(a, evidence="the engine does this at land"), "the engine does this at land", ""
        if k == "checkable":
            if self.fixes >= int(self.cfg.max_fix_rounds):
                raise self.proof_stuck([u])
            return "wrong", a, "add a test or check that proves: %s" % u["what"], "proof"
        if k in ("external_fact", "taste"):
            self.add_unverified(u, why)
            return "open", a, why, "unverified"
        return "open", a, why, ""

    def add_unverified(self, u, why):
        if u["what"] not in {x["what"] for x in self.unverified}:
            self.unverified.append({"what": u["what"], "kind": u["kind"], "why": why, "source": u.get("source") or ""})

    def route_left(self, left):
        """The items still unchecked after a verify fix round, routed: an engine step the engine does is settled; one that
        no check can prove (external_fact with a source, taste) lands unverified; a checkable one (or one a failed proving
        round left) comes back flagged proof_round, to be sent again while a fix round is left; the rest still asks."""
        out = []
        for u in left:
            defect = str(u.get("why") or "").startswith("found wrong:") and not u.get("proof_round")
            route = "" if defect else self.ledger_route(u["what"])  # a defect the verifier found is never the ledger's
            if route == "engine_step":
                self.settle_engine_step(u)
                continue
            if route == "leftover":
                self.add_unverified(dict(u, kind=u.get("kind") or "other"), "the plan defers it to a follow-up bead")
                continue
            k = self.resolve_kind(u, {})[0] if not u.get("proof_round") else "checkable"
            if defect:
                out.append(u)
            elif k == "engine_step":
                self.settle_engine_step(u)
            elif k in ("external_fact", "taste"):
                self.add_unverified(dict(u, kind=k), u.get("why") or "")
            elif k == "owner_decision" and self.backed_by_leftover(u["what"]):
                self.add_unverified(dict(u, kind=k), "a follow-up bead for the owner is filed at land")
            elif k == "checkable":
                out.append(dict(u, kind=k, proof_round=True))
            else:
                out.append(u)
        return out

    GATE_RUNNER = re.compile(r"^(?:just|make|npm run|npm|yarn|pnpm run|pnpm|cargo|task|poe|tox|nox)\s+")
    LINT_DEFAULT = {"ruff": "ruff check .", "flake8": "flake8", "shellcheck": None}
    SAFE_CMD = re.compile(r"[\w./=:,@+*~ -]+")

    def gate_names(self):
        """Names a verify item can use for a check the engine runs by itself (the gate, a configured check, a plan stage
        check or case): its id, its command, and the command without its runner (`just unity-tests` -> unity-tests)."""
        cmds = [self.cfg.gate or ""] + [c.cmd for c in self.cfg.checks] + [
            c for st in (getattr(self, "plan_data", None) or {}).get("stages") or [] for c in st["checks"]] + self.case_checks()
        names = [c.id for c in self.cfg.checks]
        for c in cmds:
            c = " ".join(c.split())
            rest = self.GATE_RUNNER.sub("", c)
            names += [c] + ([rest] if rest != c and ("-" in rest or "_" in rest) else [])
        return [n.lower() for n in dict.fromkeys(names) if len(n) >= 4]

    # tl-bxk.10.19: an item is settled only when it names a configured check and says it passes or runs; an item about
    # coverage, skips, fakes or a check that never ran is a claim about the check, not its result.
    HEDGE_LIGHT = re.compile(r"\b(?:flaky|stale|though|but|yet|however|although|unless|except|new tests?)\b")
    PROVES = re.compile(r"\b(passe[sd]?|passing|is green|stays? green|green|runs?|ran|exits? 0)\b|engine-run")
    NOT_PROOF = re.compile(r"\b(covers?|covered|coverage|a tests? for|skipped|false green|never (?:been )?run|not run|only tested|"
                           r"fake|untested|not tested)\b")

    def engine_settles(self, gaps):
        """tl-bxk.10.19: (items still to verify, items the engine found wrong). An item whose proof is the gate or a stage
        check (matched by check id or command name) is settled as 'the gate runs it at land': the read-only verifier cannot
        run it, and lifesim-5ban.1 stopped on 'could not check: unity-analyzers/unity-tests/unity-play-tests'. An item naming
        a linter the repo has (ruff) is run here; its exit code settles it, a red one goes to a fix round."""
        names, left, failed = self.gate_names(), [], []
        results, current = self.checks_now()
        for u in gaps:
            what = " ".join(u["what"].split()).lower()
            hit = None
            if not self.NOT_PROOF.search(what) and not self.HEDGE_LIGHT.search(what) and self.PROVES.search(what):
                hit = next((n for n in names if re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(n), what)), None)
                if hit and any(c.get("status") == "failed" and hit in (str(c.get("id")).lower(), " ".join(c["cmd"].split()).lower())
                               for c in results):
                    hit = None  # the engine saw it red: nothing is proven
            if hit:
                self.verified.append({"what": u["what"], "kind": u["kind"], "verdict": "settled", "why": "the gate runs it at land",
                                      "evidence": "`%s` is a gate or stage check: the engine runs it, the gate at land (a red one "
                                                  "goes to a fix round)" % hit})
                continue
            proof = None if self.is_look(u) else self.engine_proof(u["what"], results, current)
            if proof:
                self.verified.append({"what": u["what"], "kind": u["kind"], "verdict": "settled", "evidence": proof,
                                      "why": "the engine's own check results settle it"})
                continue
            cmd = self.lint_command(u["what"])
            if not cmd:
                left.append(u)
                continue
            rc, tail = self.sh(cmd, timeout=600)
            if rc in (126, 127):  # the tool cannot start here: nothing was proven, the verifier and the owner still judge it
                left.append(u)
                continue
            out = "ran `%s`: exit %d%s" % (cmd, rc, (" " + tail[-300:]) if rc else "")
            self.verified.append({"what": u["what"], "kind": u["kind"], "verdict": "settled" if rc == 0 else "wrong",
                                  "evidence": out, "why": out})
            if rc:
                failed.append(dict(u, why=out))
        return left, failed

    # tl-bxk.10.25: an item settles from the engine's results only in one narrow form: its sole doubt is that the verifier
    # cannot prove the engine ran or passed check X, every check-like name in it is a known check id, and each such check
    # passed or was skipped by its own path trigger on the current tree. A wrong settle lands broken work unseen; an ask
    # costs a minute. Everything else goes to the verifier, whose brief carries the results (checks_evidence).
    OTHER_DOUBT = re.compile(r"\b(behaviou?rs?|looks?|visual(?:ly)?|screens?|screenshots?|layout|render\w*|devices?|manual(?:ly)?|"
                             r"by hand|ui|ux|taste|feels?|edge cases?|regress\w*|race|crash\w*|coverage|covers?|covered|fake|"
                             r"false green|bug)\b")
    CANNOT_PROVE = re.compile(r"\b(?:cannot|can not|unable to) (?:prove|verify|confirm|see)\b|\bno (?:saved )?logs?\b")
    HEDGE = re.compile(r"\b(?:not|never|no|nor|none|nothing|without|flaky|stale|only|yet|though|but|unless|except|missing|"
                       r"still|also|however|although|wrong|fails?|failed|new tests?)\b|n't")
    CHECK_LIKE = re.compile(r"`([^`]+)`|(?<![\w.-])([\w.]*[-_./*][\w.*/-]*)")

    def engine_proof(self, what, results, current):
        """The evidence text when the item names only known check ids, each green or skipped by its path trigger, on the
        current known tree, and doubts nothing but whether the engine ran or passed them; else ''."""
        what = " ".join(what.split()).lower()
        if not current or not results or not self.CANNOT_PROVE.search(what) or self.OTHER_DOUBT.search(what):
            return ""
        if self.HEDGE.search(self.CANNOT_PROVE.sub(" ", what)):
            return ""
        ids = {str(c.get("id") or "").lower(): c for c in results}
        hits = [c for i, c in ids.items() if len(i) >= 4 and re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(i), what)]
        like = [(m.group(1) or m.group(2)).strip(".,;:").lower() for m in self.CHECK_LIKE.finditer(what)]
        if not hits or any(n not in ids for n in like) or tools_named(what):
            return ""
        parts = []
        for c in hits:
            idn = c["id"][:80]
            if c.get("status") == "ran" and c.get("exit") == 0:
                parts.append("`%s` [%s] passed: exit 0, %s s, log %s" % (idn, c["group"], c.get("secs", "?"), self.log_path_of(c)))
            elif c.get("status") == "skipped" and str(c.get("why") or "").startswith("no change under"):
                parts.append("`%s` [%s] skipped: %s, so the check does not apply to this change" % (idn, c["group"], c["why"]))
            else:
                return ""
        return "the engine's own check results for this tree: " + "; ".join(parts)

    def log_path_of(self, c, full=True):
        """The saved log of a check: absolute in the trace; in a prompt relative to the engine's run folder, since a path
        into it is a file no step can read (the brief is inline, never a path outside the worktree)."""
        return str(self.run_dir / c["log"] if full else c["log"]) if c.get("log") else "none (cached: same tree and base, earlier result)"

    def checks_now(self):
        """(the engine's last check results, whether they ran on the tree as it is now). After a resume the saved
        engine-checks.json stands in for the brief; its tree is unknown, so it settles nothing."""
        checks, tree = self.last_checks, self.checks_tree
        if checks is None:
            try:
                return json.loads((self.run_dir / "engine-checks.json").read_text()), False
            except (OSError, ValueError):
                return [], False
        return checks, bool(tree) and tree == self.tree_hash()

    def checks_evidence(self, checks=None, current=None):
        """The engine's check results as brief text: per check id, group, command, status (pass, fail, skipped and why),
        exit code, duration, log path; said plainly to be the engine's evidence the reader may cite. '' when none ran."""
        if checks is None:
            checks, current = self.checks_now()
        if not checks:
            return ""
        out = []
        for c in checks[:30]:
            st = c.get("status")
            if st == "skipped" or c.get("exit") is None:
                what = "skipped (%s)" % (c.get("why") or "no reason given")
            else:
                what = "%s, exit %s, %s s, log %s" % ("pass" if c["exit"] == 0 else "fail", c["exit"], c.get("secs", "?"),
                                                      self.log_path_of(c, False))
            cmd = "" if c.get("cmd") == c.get("id") else "; command `%s`" % c.get("cmd", "")[:300]
            last = " ".join(" ".join((c.get("tail") or "").strip().splitlines()[-2:]).split())  # the log is no file the verifier can open
            row = ("- `%s` [%s] %s%s" % (str(c.get("id"))[:100], c.get("group"), what, cmd))[:300]
            room = 300 - len(row) - len("; last output: ")
            if last and c.get("exit") == 0 and room >= 20:  # what a pass printed last, within the 300-character row
                row += "; last output: " + last[-min(160, room):]
            out.append(row)
        if len(checks) > 30:
            out.append("- (%d more checks not listed)" % (len(checks) - 30))
        return ("The engine's own check results for %s (the engine's evidence, run by the engine itself: you may cite them as "
                "proof; a log path is relative to the engine's run folder, which you cannot open. A check skipped for "
                "'no change under ...' matched no changed path: it is proven by design that the check does not apply, so an item "
                "whose only doubt is such a skipped check, or a check listed here as pass, is settled; cite this list):\n%s\n" % ("the tree as it is now" if current else
                                      "an earlier tree (files changed since: weigh them accordingly)", "\n".join(out)))

    def lint_command(self, what):
        """The command the engine runs for an item naming a linter this repo uses: the backticked command if it is plain
        words (no shell syntax), else the linter's default; "" when it names none, or the repo does not use it."""
        for tool in tools_named(what):
            if tool not in KNOWN_TOOLS or unused_tool("`%s`" % tool, self.wt, self.cfg):
                continue
            for c in re.findall(r"`([^`]+)`", what):
                if c.split()[:1] == [tool] and self.SAFE_CMD.fullmatch(c):
                    return c.strip()
            if self.LINT_DEFAULT.get(tool):
                return self.LINT_DEFAULT[tool]
        return ""

    def work_summary(self):
        """The task's changed files with their line counts, untracked files included."""
        tree = self.tree_hash()
        return (tl.git("diff", "--stat", self.base_sha(), tree, cwd=self.wt) if tree else "") or "(no files changed)"

    def ask_plan(self, prompt, step, title, mode="plan"):
        """One planner answer. Its checks are validated before any write; the ones that read the tracker, run gate-only
        commands, or cannot run (dry_check) go back once, on the same planner thread, with the exact errors."""
        data, _ = self.ai("plan", title, prompt, step=step, mode=mode, at=(self.planned, 0, 0))
        if self.plan_fits(data):  # checkpoint first: a SIGTERM during the send-back below resumes with this plan
            self.plan_data = json.loads(json.dumps(data))
            self.save_checkpoint(stage=0, rounds=0, n=0, feedback="", step="write")
        bad, gated, dry = lint.tracker_checks(data), lint.gate_only_checks(data, self.cfg), lint.dry_check(data, self.wt)
        rep = self.repeated_slow(data)
        only = gate_only_criteria(data, self.cfg)
        led = (lint.ledger_problems(data) + lint.timeout_problems(data, self.cfg.check_timeout_min)
               + lint.unity_problems(data, self.cfg))
        if led:
            dry = dry + led  # sent back with the checks that cannot run
        # tl-wjj: a plan with no stages, no question and nothing to file breaks the plan contract (lifesim-w6mk failed on it): back
        # to the planner once. With leftovers it is the finished-work plan (tl-bxk.13.2); with the owner's verify answer it may be empty.
        empty = (not data["stages"] and not data["question"].strip() and not data.get("leftovers") and not self.leftovers
                 and not self.verify_answer)
        if bad or gated or dry or rep or empty or only:  # asked once to rewrite them, like an invalid answer; not a counted re-plan
            why = ""
            if empty:
                self.warn("the plan has no stages, no question and nothing to file, sent back")
                why += EMPTY_PLAN_TEXT
            if rep:
                self.warn("the plan's checks run a slow command more than once, sent back: %s" % "; ".join(r[0] for r in rep)[:300])
                why += REPEAT_TEXT % "\n".join("- `%s` in %s" % (part, "; ".join("`%s`" % c[:80] for c in cs) if cs else "a repo check (%s)" % rid)
                                               for part, cs, rid in rep)
            if only:
                self.warn("the plan's acceptance is only the gate, sent back (%s): %s" % (GATE_ONLY_ACCEPTANCE, "; ".join(only)[:300]))
                why += GATE_ONLY_ACCEPTANCE_TEXT % (GATE_ONLY_ACCEPTANCE, self.cfg.gate or "the gate", "\n".join("- %s" % c for c in only))
            if bad:
                self.warn("the plan's checks read the issue tracker, sent back: %s" % "; ".join(bad)[:300])
                why += TRACKER_TEXT % "\n".join("- `%s`" % c for c in bad)
            if gated:
                self.warn("the plan's checks run gate-only commands, sent back: %s" % "; ".join(
                    "%s (%s)" % g for g in gated)[:300])
                why += lint.GATE_ONLY_TEXT % "\n".join("- `%s`: %s" % g for g in gated)
            if dry:
                self.warn("the plan's checks cannot run, sent back: %s" % "; ".join(dry)[:300])
                why += DRY_CHECK_TEXT % "\n".join("- " + e for e in dry)
            self.steps.outcome("sent back", "its checks read the tracker, run gate-only commands, repeat a slow command or cannot run" if not empty
                            else "it has no stages")
            self.steps.move(step, "plan_sent_back", "plan %s" % "; ".join(
                (["has no stages"] if empty else []) + (["checks read the issue tracker"] if bad else []) +
                (["acceptance is only the gate (%s)" % GATE_ONLY_ACCEPTANCE] if only else []) +
                (["checks run gate-only commands"] if gated else []) +
                (["checks repeat a slow command"] if rep else []) + (["checks cannot run"] if dry else [])))
            ref = self.planner_ref
            back = (why.lstrip() + "\n\nYour plan, to correct (same output schema):\n" + json.dumps(data, indent=1)) if ref else prompt + why
            data, _ = self.ai("plan", "rewrite checks", back, step=step, mode="checks_back", resume_ref=ref or None, at=(self.planned, 1, 0))
            bad, gated = lint.tracker_checks(data), lint.gate_only_checks(data, self.cfg)
            only = gate_only_criteria(data, self.cfg)
            if only:
                raise Blocked("failed: the plan's acceptance is still only the gate after one rewrite (%s): %s"
                              % (GATE_ONLY_ACCEPTANCE, "; ".join(only)[:400]), kind=oc.Kind.FAULT_PLAN)
            if bad:
                raise Blocked("failed: the plan's checks still read the issue tracker after one rewrite: %s"
                              % "; ".join(bad)[:400], kind=oc.Kind.FAULT_PLAN)
            if gated:
                raise Blocked("failed: the plan's checks still run gate-only commands after one rewrite: %s"
                              % "; ".join("%s (%s)" % g for g in gated)[:400], kind=oc.Kind.FAULT_PLAN)
            for r in self.repeated_slow(data):  # a heuristic like dry_check: the send-back was the remedy, no second one
                self.warn("the plan's checks still run `%s` more than once after one rewrite" % r[0][:200])
            dry = lint.dry_check(data, self.wt)
            if dry:  # a heuristic: the writer's bad_checks flag decides from here, no second send-back
                self.warn("the plan's checks may still not run after one rewrite: %s" % "; ".join(dry)[:300])
        for c, i in lint.rerun_checks(data, self.cfg):  # still runs as written: a send-back costs a re-plan
            self.warn("`%s` re-runs %s; use $%s" % (c[:100], i, lint.check_env_name(i)))
        return data

    SLOW_RUNNER = re.compile(r"^(?:dotnet|pytest|python3? -m (?:pytest|unittest)|cargo|go test|npm (?:run )?test|yarn test)\b")
    REDIRECT = re.compile(r"\s+(?:\d?>>?\s*\S+|&>\s*\S+)")

    def repeated_slow(self, plan):
        """tl-bxk.13.4: [(command, [plan checks running it], repo check id or "")]: a slow command (a runner such as `just x`,
        `dotnet test`, that the repo's history or its name says takes long) that two plan checks run, or that a repo check
        already runs, redirects aside. lifesim-fld.10: `just unity-tests` three times a round, 99 min in two rounds; the exact
        repeat is reused (tl-bxk.10.27), a repeat wrapped in `mkdir && cmd > a.out && grep` is not."""
        secs, out = self.check_secs(), {}
        repo = {norm_cmd(k.cmd): k.id for k in self.cfg.checks}
        stages = plan.get("stages") or []
        extra = [x["check"] for k in ("risks", "cases") for x in plan.get(k) or []]  # they run with the last stage
        blocks = [list(st["checks"]) + (extra if k == len(stages) - 1 else []) for k, st in enumerate(stages)] or [extra]
        for block in blocks:  # a stage's checks run together; another stage's run in another round
            found = {}
            for c in dict.fromkeys(block):
                parts = split_top(c)
                for part in dict.fromkeys(norm_cmd(self.REDIRECT.sub("", p)) for p, _ in (parts or [(c, "")]) if p.strip()):
                    if not (self.GATE_RUNNER.match(part) or self.SLOW_RUNNER.match(part)):
                        continue
                    if SLOW_CMD.search(part) or secs.get(part, 0) > float(self.cfg.writer_check_max_s):
                        found.setdefault(part, []).append(c)
            for part, cs in found.items():
                if (len(set(cs)) >= 2 or part in repo) and any(norm_cmd(c) != part for c in cs):
                    out.setdefault(part, [])
                    out[part] += [c for c in cs if c not in out[part]]
        return [(part, cs, repo.get(part, "")) for part, cs in out.items()]

    def cap_blocked(self, detail=""):
        """The re-plan cap's ask: the planner ran `planned` times. An answer that allows one more (action rerun) gives one."""
        why = "; ".join("%d. %s: %s" % (k + 1, e["mode"], e["why"]) for k, e in enumerate(self.plan_log))[:1500]
        return Blocked(REPLAN_CAP + "%d times (the limit is %d plan + %d amends): %s%s" % (
            self.planned, 1, int(self.cfg.max_replans) + self.extra, why, ("; " + detail) if detail else ""),
            askspecs.cap_reached(self.planned, [(e["mode"], e["why"]) for e in self.plan_log]), kind=oc.Kind.ASK_STUCK)

    def grant_cap(self):
        """The owner allows one more planner run: they answered the cap's ask with the rerun option, or put the override on the bead
        (`tl override BEAD replan-cap`). Any other answer is recorded and the bead blocks again at the cap. The grant goes into the
        checkpoint's extra, which resume_point adds to."""
        a = self.answered
        by_ask = a is not None and a.ask_class == AskClass.CAP_REACHED
        by_override = (tl.peek(self.store, self.bead) or Bead(id=self.bead, title="", status="")).metadata.get(intake.OVERRIDE) == "replan-cap"
        if self.cap_granted or not (by_ask or by_override):
            return
        self.cap_granted = True
        rerun = a is not None and a.answer is not None and a.answer.action == "rerun"
        said = a.id if a else ""
        if not (by_override or rerun):
            self.log.note("the owner answered the re-plan cap (%s) without allowing more: still blocked. Answer: %s" % (
                said, (self.answered_words() or "(none)")[:300]))
            return
        self.log.note("the owner allowed one more planner run (%s)" % ("the override" if by_override else "ask " + said))
        if by_override:
            tl.attempt(self.store.update, self.bead, BeadPatch(unset_metadata=[intake.OVERRIDE]))
        try:
            ck = json.loads(self.checkpoint_path().read_text())
            ck["extra"] = int(ck.get("extra") or 0) + 1
            self.checkpoint_path().write_text(json.dumps(ck, indent=1))
        except (OSError, ValueError):
            self.extra += 1

    def answered_words(self):
        """What the owner's answer asks the work to do: their text, or the split instruction; a bare rerun or confirm asks for nothing."""
        return asktext.words(self.answered.answer if self.answered else None)

    def kept_whole(self):
        """The owner answered the too-big ask, and not with 'I will split it': the plan goes ahead with all its stages."""
        a = self.answered
        return a is not None and a.ask_class == AskClass.TOO_BIG and (a.answer is None or a.answer.action != "split")

    def plan(self, again=False):
        old = self.old_plan or (self.plan_data if again and getattr(self, "plan_data", None) else None)
        self.amended = self.amended or bool(old)  # tl-bxk.10.24: work exists before this plan's first stage
        mode = "amend" if old else "plan"
        why = ""
        if again:
            try:
                why = (self.run_dir / "replan.md").read_text(encoding="utf-8")[-12500:]
            except OSError:
                pass
        # tl-19i: the owner's answer, or an edit of the bead by the owner, is not a failed plan: it never counts (lifesim-yxbb.3
        # parked 'stuck: re-planned 3 times' on 'the owner answered ask yxbb.3-1')
        owner = (bool(old) and not again and (self.amend_why or "").startswith("bead changed: the owner answered")
                 and not (self.answered and self.answered.ask_class == AskClass.CAP_REACHED))  # a cap ask answered 'split' stays blocked
        if not owner and self.planned >= 1 + int(self.cfg.max_replans) + self.extra:
            raise self.cap_blocked()
        if not owner:
            self.planned += 1
        self.plan_log.append({"mode": mode, "counted": not owner,
                              "why": fmt.clip(self.amend_why or ("a re-plan: " + fmt.clip(why, 160) if again else "first plan"), 240)})
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
        hist = self.rounds_text()
        if hist and (old or again):  # tl-bxk.13.6: replan.md holds the last round only; the planner also sees the rounds before it
            extra += ("\n\nWhat the rounds on this task did so far (the writer's summary, then what was sent back). Do not "
                      "plan a fix that already failed to hold:\n<rounds>\n%s</rounds>\n" % hist)
        if old or again:
            extra += self.deferred_text()
        rules = []
        wr = self.rules_text()
        if wr:
            rules.append("This repo's rules for workers (what runs where, known pitfalls of its tools); the checks you "
                         "write must follow them:\n<worker_rules>\n%s\n</worker_rules>" % wr)
        notes = self.planner_notes()
        if notes:
            rules.append("Facts about this factory and project that the plan must respect:\n" + notes)
        shared = self.shared_text()
        if shared:
            rules.append(shared.strip())
        if self.visual_cfg() and self.shot_methods():  # the classes mean "the engine renders": only with a shot table
            rules.append(VISUAL_PLAN % self.references_text())
            vp = self.visual_cfg()
            rules.append(VISUAL_STAGES % (", ".join(vp.include)[:300], looks.table_text(self.shot_methods())))
        rules.append("Proof files that a check reads or a reviewer looks at (screenshots, logs, probe output) go under "
                     "%s: it is kept across runs, and nothing else under %s is." % (self.evidence_dir, self.task_dir))
        rules.append("Checks run on the uncommitted working tree after each write. The engine runs the gate%s once, on "
                     "the rebased tree at land: never put %s in a stage's checks, and a criterion that names it is proven "
                     "by that land gate: write no case for it." % (
                         (" (`%s`)" % self.cfg.gate) if self.cfg.gate else "",
                         ("`%s`" % self.cfg.gate) if self.cfg.gate else "it"))
        extra_gated = [(c, why) for c, why in lint.gate_only(self.cfg) if c != " ".join(self.cfg.gate.split())]
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
            self.steps.outcome("sent back", "an accepted requirement decides its question")
            self.steps.move(step, "planner_decided", "an accepted requirement decides it: %s" % decided)
            self.planned += 1  # a planner run like the others: the cap counts it
            self.plan_log.append({"mode": "plan", "why": "an accepted requirement decides its question"})
            data = self.ask_plan(prompt + DECIDED_TEXT % (q, decided) + PLAN_DECIDED_TEXT, step, "plan to meet it", "checks_back")
        data = json.loads(json.dumps(data))  # the engine's own copy: cases are added to it as the task runs
        if data["question"].strip() and data.get("irreversible") not in IRREVERSIBLE:
            # tl-ntp: a question about anything that can be undone is an assumption, not an ask (82 item 1)
            asked = data["question"].strip()
            data = self.assume_question(data)
            if not data["stages"] and not data.get("leftovers") and not self.leftovers and not self.plan_assumed:
                self.plan_assumed = True
                self.warn("the planner asked a question about a step that can be undone, sent back: %s" % asked[:300])
                self.steps.outcome("sent back", "its question is about a step that can be undone")
                self.steps.move(step, "planner_assumed", "a question about a reversible step is an assumption: %s" % asked[:200])
                self.planned += 1
                self.plan_log.append({"mode": "plan", "why": "its question is about a step that can be undone"})
                prior = data["assumptions"]
                data = json.loads(json.dumps(self.ask_plan(prompt + ASSUME_TEXT % asked, step, "plan on assumptions", "checks_back")))
                data["assumptions"] = prior + data.get("assumptions", [])
                if data["question"].strip() and data.get("irreversible") not in IRREVERSIBLE:
                    data = self.assume_question(data)
        if self.plan_fits(data):
            # a SIGTERM from here on resumes with this plan (d5f.38 lost a finished 1.1M plan before its checkpoint)
            self.plan_data = data
            self.save_checkpoint(stage=0, rounds=0, n=0, feedback="", step="write")
        if self.verify_answer and not data["stages"] and not data["question"].strip():
            self.log.note("the planner finds the owner's answer asks for nothing more: landing")
            self.plan_leftovers(data)
            return data
        self.plan_summary = data["summary"]
        for c in data.get("cases") or []:
            c.setdefault("by", "plan")
        self.plan_data = data
        if data["question"].strip():
            self.steps.outcome("asks", data["question"][:200])
            raise Blocked("owner decision needed", askspecs.open_question(data["question"], data.get("options")), kind=oc.Kind.ASK_DECISION)
        self.steps.outcome("%d stage%s" % (len(data["stages"]), "" if len(data["stages"]) == 1 else "s"),
                        data["summary"][:200])
        self.check_unresolved(data)
        if not data["stages"]:
            # tl-bxk.13.2: the work is done and only the filing is left: the engine files and closes. Never after a failed
            # stage (a re-plan), and never over work no review accepted: that tree is not "done".
            if (data["leftovers"] or self.leftovers) and not again and (self.done or not self.task_diff().strip()):
                self.log.note("the planner finds the work done and leaves only follow-up beads to file: closing")
                self.plan_leftovers(data)
                self.plan_summary = data["summary"]
                (self.run_dir / "plan.json").write_text(json.dumps(data, indent=1))
                return data
            raise Blocked("failed: the plan has no stages", kind=oc.Kind.FAULT_PLAN)
        big = int(self.cfg.max_stages)
        if len(data["stages"]) > big and not self.kept_whole():
            raise Blocked("ticket: the plan has %d stages (more than %d): the bead may be too big for one task" % (
                len(data["stages"]), big), askspecs.too_big([st["goal"] for st in data["stages"]], big), kind=oc.Kind.ASK_TICKET)
        self.ledger_fill(data)
        self.plan_leftovers(data)
        lines = ["Plan (engine): " + data["summary"]]
        lines += ["%d. %s%s [files: %s] [checks: %s]" % (n + 1, s["goal"], " (hard)" if s["hard"] else "",
                                                          ", ".join(s["files"]), "; ".join(s["checks"]))
                  for n, s in enumerate(data["stages"])]
        lines += ["Risk: %s → %s" % (r["what"], r["check"]) for r in data["risks"]]
        lines += [ASSUMPTION + a["text"] for a in data.get("assumptions") or []]
        self.comment("\n".join(lines))
        (self.run_dir / "plan.json").write_text(json.dumps(data, indent=1))
        self.export_brief()
        self.save_checkpoint(stage=0, rounds=0, n=0, feedback="", step="write")
        return data

    def plan_fits(self, data):
        """A plan worth keeping through a stop: it has stages, asks nothing, and is not a split ask."""
        return bool(data["stages"] and not data["question"].strip() and (
            len(data["stages"]) <= int(self.cfg.max_stages) or self.kept_whole()))

    def plan_leftovers(self, data):
        """The follow-up work the plan wants filed: filed at the close with the reviews' leftovers. Only a plan the run
        goes on with adds them, so a plan that asks the owner is not filed twice by the plan after the answer."""
        have = {lo["title"] for lo in self.leftovers}
        self.leftovers += [lo for lo in data["leftovers"] if lo["title"] not in have]

    # -- checkpoints: where a stopped run was, outside the worktree, so the next run goes on from there
    def check_ask(self):
        """An open ask is never asked again: with the bead unchanged the run waits; a change (the owner's comment or edit) or a
        filed answer answers it, and the run goes on from its checkpoint."""
        state, a = raiser.check(self.stores.asks, self.bead, self.brief_hash, self.fresh, time.time())
        if state == "wait" and a:
            raise Blocked(raiser.waiting_line(a), kind=oc.Kind.WAIT_ASK)
        if state == "answer" and a:
            self.answered = a
            self.export_brief()  # the brief the workers read now carries the owner's answer
            self.log.note("ask %s (%s) is answered: %s" % (a.id, a.kind.value, "the owner's answer is filed on it" if a.answer
                                                           else "the bead changed since it was asked"))

    def raise_ask(self, spec, why, kind):
        """File the ask the stop carries. Lint decides whether it is one an owner can answer: if not, nothing is filed and the stop is
        the engine's own fault, never a prose question. -> the Ask, or None."""
        common = self.git("rev-parse", "--path-format=absolute", "--git-common-dir")
        at = raiser.Asking(bead=self.bead, run=self.log_path.stem, brief_hash=self.brief_hash, now=time.time(), why=why,
                           repo=str(Path(common).parent) if common else str(self.wt), title=getattr(self, "bead_title", "") or "")
        a, problems = raiser.raise_ask(self.stores.asks, spec, at)
        if a is None:
            self.warn("the ask is not one an owner can answer (%s): %s" % ("; ".join(problems), spec.decision[:200]))
            return None
        moved = raiser.leave_queue(self.store, self.bead, self.cfg.pick_label or "", self.cfg.needs_info_label or "") if (
            a.kind.value in ("decision", "ticket") and not self.dry) else ""
        self.comment(asktext.comment(a) + moved)
        return a

    def checkpoint_path(self):
        return tl.config_dir() / "checkpoints" / ("%s.json" % self.bead)

    def save_checkpoint(self, **at):
        # mid-rebase (a conflict fix) HEAD is detached: the checkpoint names the task branch the close goes back to
        branch = self.git("symbolic-ref", "--short", "-q", "HEAD") or getattr(self, "task_branch", "")
        rec = {"v": 1, "bead": self.bead, "branch": branch,
               "rebase_resets": self.rebase_resets,
               "plan": self.plan_data, "planner_ref": self.planner_ref, "planned": self.planned, "extra": self.extra, "plan_log": self.plan_log, "snap": self.snap,
               "done": self.done, "accepted": self.accepted, "replans": self.replans, "fixes": self.fixes, "denials": self.denials,
               "writer": self.writer.get("delegate") or "", "writer_fallback": self.writer_fallback, "fallback_lane": self.fallback_lane,
               "writer_family": self.writer_family or "", "writer_ctx": self.writer.get("ctx"), "writer_seen": self.writer.get("seen"),
               "brief": self.brief_hash, "head": self.git("rev-parse", "HEAD"),
               "unchecked": self.unchecked, "filed": self.filed,
               "look_paths": self.look_paths, "look_notes": self.look_notes, "look_unjudged": self.look_unjudged,
               "look_done": self.look_done, "look_prev": self.look_prev, "rendered": sorted(self.rendered_names),
               "last_reqs": self.last_reqs, "render_stale": self.render_stale,
               "unverified": self.unverified, "handoff": self.handoff, "stage_tree": self.stage_tree, "writer_said": self.writer_said, "accepted_new": self.accepted_new,
               "closed": False,
               "run": self.log_path.stem, "t": time.time(), **at}
        rec["pending_land_validation"] = self.pending_land_validation
        if self.pending_land_validation:
            # fix(), a re-plan, or an interrupted recovery must never turn this into a direct-to-land checkpoint.
            rec.update(step="land-verify-red", feedback=self.pending_land_validation)
        p = self.checkpoint_path()
        p.parent.mkdir(exist_ok=True)
        p.write_text(json.dumps(rec, indent=1))

    def save_unfiled(self, unfiled):
        """The follow-ups bd refused, kept in the checkpoint (title, why) and out of `filed`, so none is lost or counted."""
        try:
            ck = json.loads(self.checkpoint_path().read_text())
        except (OSError, ValueError):
            ck = None
        if ck is not None:
            ck.update(filed=self.filed)
            if unfiled:
                ck["unfiled"] = (ck.get("unfiled") or []) + [{"title": lo["title"], "why": lo["why"]} for lo in unfiled]
            self.checkpoint_path().write_text(json.dumps(ck, indent=1))

    def mark_checkpoint_closed(self, why=""):
        """The close step committed everything: the checkpoint's head is now exactly what the next run should find. A
        red gate at land is no stop: the next run re-plans with the gate's output, or it would rerun the same red gate."""
        try:
            ck = json.loads(self.checkpoint_path().read_text())
        except (OSError, ValueError):
            return
        ck.update(head=self.git("rev-parse", "HEAD"), closed=True, filed=self.filed)
        if why.startswith("gate red") and not ck.get("pending_land_validation"):
            ck.update(step="gate-red", gate_tail=trim.trim_log(why, log=str(getattr(self, "gate_log", "") or "")))
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
        if self.fresh:
            self.drop_checkpoint()
        try:
            ck = json.loads(self.checkpoint_path().read_text())
        except (OSError, ValueError):
            return None, 0, None
        self.ck_run = ck.get("run") or "" if isinstance(ck, dict) else ""
        branch = self.git("symbolic-ref", "--short", "-q", "HEAD")
        if not isinstance(ck, dict) or any(k not in ck for k in CK_FIELDS) or ck["v"] != 1 or ck["branch"] != branch or not ck["plan"]:
            self.drop_checkpoint()
            return None, 0, None
        self.pending_land_validation = ck["pending_land_validation"] or (ck["feedback"] if ck["step"] == "land-verify-red" else "")
        self.look_paths, self.look_notes = list(ck.get("look_paths") or []), list(ck.get("look_notes") or [])
        self.look_done, self.look_prev = int(ck.get("look_done") or 0), list(ck.get("look_prev") or [])
        self.rendered_names, self.last_reqs = set(ck.get("rendered") or []), list(ck.get("last_reqs") or [])
        self.render_stale = bool(ck.get("render_stale"))
        self.look_unjudged = dict(ck.get("look_unjudged") or {})
        self.unverified = list(ck.get("unverified") or [])
        self.handoff = {"rounds": list(ck["handoff"].get("rounds") or []), "seen_lows": list(ck["handoff"].get("seen_lows") or [])}
        self.rebase_resets = int(ck.get("rebase_resets") or 0)
        self.planned = int(ck["planned"])
        self.extra, self.plan_log = self.extra + int(ck.get("extra") or 0), list(ck.get("plan_log") or [])
        self.planner_ref = ck.get("planner_ref") or self.planner_ref
        head = self.git("rev-parse", "HEAD")
        ours = head == ck["head"] or (self.left_dirty and not ck["closed"] and self.git("rev-parse", "HEAD~1") == ck["head"])
        if not ours:  # a commit, or an edit after a clean close, that is not this engine's: the plan may not fit it
            self.log.note("the branch changed since the checkpoint of %s: amending its plan" % ck["run"])
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
        self.stage_tree, self.writer_said = ck.get("stage_tree") or "", ck.get("writer_said") or ""
        self.accepted_new = list(ck.get("accepted_new") or [])
        if ck["writer"]:
            self.writer["delegate"] = ck["writer"]
            self.writer["ctx"], self.writer["seen"] = ck.get("writer_ctx"), ck.get("writer_seen")
            self.fallback_lane = ck.get("fallback_lane") or ""
            self.writer_fallback = bool(ck["writer_fallback"])
            self.writer_family = ck.get("writer_family") or None
        if ck["step"] == "gate-red":
            self.log.note("the gate was red at land in %s: re-planning with its output, keeping %d accepted stage(s)"
                     % (ck["run"], len(self.done)))
            (self.run_dir / "replan.md").write_text(
                "Every stage was accepted, then the gate failed on the tree rebased onto the latest base (often "
                "another task landed first). Plan the fix.\n\n" + ck.get("gate_tail", ""))
            self.replan_first = True
            self.old_plan, self.amend_why = ck["plan"], "gate red at land"
            return None, 0, None
        if ck["step"] == "land-verify-red":
            # A retry fix that failed checks or review is not accepted work, even if its tree passes the gate.
            # Re-plan it through stages so both checks and review must pass before another land attempt.
            self.log.note("retry validation failed in %s: re-planning the unaccepted fix" % ck["run"])
            (self.run_dir / "replan.md").write_text(
                "A push retry's validation fix did not pass checks and review. Plan the fix before landing.\n\n"
                + ck.get("feedback", ""))
            self.replan_first = True
            self.old_plan, self.amend_why = ck["plan"], "retry validation fix failed at land"
            return None, 0, None
        given = self.answered is not None and self.answered.answer is not None  # a filed answer changes what the plan reads, whatever the bead
        if (ck["brief"] != self.brief_hash or given) and ck["step"] == "land" and self.answered and self.answered.ask_class == AskClass.EXTERNAL_FACT:
            self.plan_data, self.plan_summary = ck["plan"], ck["plan"]["summary"]
            answer = self.answered_words()
            if given and self.answered.answer.action == "confirm":
                self.log.note("the owner answered verify ask %s (confirmed): going straight to land" % self.answered.id)
                return ck["plan"], len(ck["plan"]["stages"]), None
            # lifesim-fld.26.15: 'add a test that ..., then land' landed without the test; any answer but a plain yes
            # goes to the planner, which plans what it asks for, or nothing (then the run lands)
            self.verify_answer = answer or "(no comment: the owner edited the bead)"
            self.log.note("the owner answered verify ask %s with more than a yes: planning what it asks, keeping %d "
                             "accepted stage(s)" % (self.answered.id, len(self.done)))
            return None, 0, None
        if ck["brief"] != self.brief_hash or given:
            answer = self.answered_words()
            # a comment alone is context for the next writer (the brief carries it), not an amend: supervisor notes used up
            # the re-plan cap (lifesim d5f.40, fld.27.12). An owner's answer to an ask still amends.
            diff = bead_diff(ck["snap"], self.snap, answer) if ck.get("snap") else None
            if diff and not self.answered and not bead_diff(ck["snap"], self.snap, answer, comments=False):
                diff = ""
            if given and not answer and ck["brief"] == self.brief_hash:
                # tl-bxk.13.16.5: "Run again" changes nothing the plan reads; counted as an amend it used a re-plan (lifesim-fld.10)
                self.log.note("the owner's answer (%s) only asks for a rerun: keeping the plan, no planner run" % self.answered.answer.action)
                diff = ""
            if diff == "":  # the hash moved on a label, a priority or a comment: nothing the plan reads changed
                self.log.note("the bead changed since the checkpoint of %s, but nothing the plan reads: keeping the plan, "
                         "no planner run" % ck["run"])
            else:
                self.log.note("the bead changed since the checkpoint of %s: amending its plan, keeping %d accepted stage(s)"
                         % (ck["run"], len(self.done)))
                self.old_plan = ck["plan"]
                self.amend_why = "bead changed: %s" % ("the owner answered ask %s" % self.answered.id if self.answered
                                                       else "an edit with no ask")
                self.amend_text = diff or "The bead changed since the old plan (the checkpoint holds no copy of the old text): read the task above."
                self.amend_text += "\nAccepted stages (their work is in the tree): " + ("; ".join(self.done) or "none")
                return None, 0, None
        self.plan_data, self.plan_summary, self.accepted = ck["plan"], ck["plan"]["summary"], list(ck["accepted"])
        (self.run_dir / "plan.json").write_text(json.dumps(ck["plan"], indent=1))
        stages = ck["plan"]["stages"]
        again = self.promised_missing(ck["plan"], len(stages) if (ck["step"] == "land" or ck["stage"] >= len(stages)) else ck["stage"])
        if again is not None:
            # tl-bxk.13.16.2: lifesim-d5f.40 resumed in another slot, its stage 1 evidence file stayed behind and the checks of stage 2
            # could never pass (the writer said so 8 times). The stage that made it runs again.
            self.log.note("resuming %s: a file stage %d promised is missing, so that stage runs again" % (ck["run"], again + 1))
            self.accepted = [k for k in self.accepted if k < again]
            redo = {st["goal"] for st in stages[again:]}
            self.done = [g for g in self.done if g not in redo]
            self.unchecked = []
            return ck["plan"], again, None
        if ck["step"] == "land" or ck["stage"] >= len(stages):
            self.unchecked = list(ck.get("unchecked") or [])  # still unproven: verified again before land
            self.log.note("resuming %s: every stage was accepted, going straight to land" % ck["run"])
            return ck["plan"], len(stages), None
        self.log.note("resuming %s at stage %d/%d, round %d (write %d)" % (
            ck["run"], ck["stage"] + 1, len(stages), ck["rounds"] + 1, ck["n"] + 1))
        return ck["plan"], ck["stage"], {"rounds": ck["rounds"], "n": ck["n"], "feedback": ck["feedback"]}

    def promised_missing(self, plan, upto):
        """tl-bxk.13.16.2: the index of the earliest accepted stage (before `upto`) that mentions an evidence file which is gone
        now while a check still to run reads it, or None. A check that writes the file itself (`> path`, tee) does not need it."""
        ev = re.compile(r"\.task/%s/evidence/[^\s\"'<>|;&)]+" % re.escape(self.bead))
        stages = plan.get("stages") or []
        pending = [c for st in stages[upto:] for c in st["checks"]] + [
            x["check"] for x in plan.get("cases") or [] if x.get("check", "").strip() and x.get("class", "test") == "test"]
        need = set()
        for c in pending:
            for p in ev.findall(c):
                if not Path(self.wt, p).exists() and not re.search(r"(?:>>?|tee(?: -a)?)\s*[\"']?%s" % re.escape(p), c):
                    need.add(p)
        early = [k for k, st in enumerate(stages[:upto]) if any(p in c for c in st["checks"] for p in need)]
        return min(early) if early else None

    def stage(self, plan, i, state=None):
        """Write → checks → review until the review is clean. A red check goes straight back to the writer (it never
        reaches the reviewer); max_check_tries red in a row, or a review that sends it back, use up a round; when the
        rounds are used up the stage asks for a re-plan. Accept is a rule: checks green and nothing blocking in the
        review (high/medium findings, unmet requirements). The writer's or the reviewer's question is the owner's."""
        st = plan["stages"][i]
        last = i == len(plan["stages"]) - 1
        state = state or {}
        fix = state.get("fix")
        sk = self.at_stage = 1000 + int(state.get("fix_n") or 0) if fix else i  # the stage's place in a call's key (CallState)
        if not state or fix:  # a resumed stage keeps the checkpoint's start; the first stage starts at the task's base
            self.stage_tree = self.tree_hash() if (i or fix or self.amended) else ""
        name = state.get("name") or "stage %d/%d" % (i + 1, len(plan["stages"]))
        if not state:  # a resumed stage keeps its render rounds (the checkpoint's)
            self.look_done, self.look_prev = 0, []
        feedback, rounds, red, n = state.get("feedback", ""), state.get("rounds", 0), 0, state.get("n", 0)
        failed_cmds = state.get("failed")  # the commands the last engine run found red (None: no check ran red yet)
        shots_fixed = False  # a visual write without shots or a reason is sent back once, at no cost to the rounds (tl-tno)
        red_now = set()  # the commands the last round found red
        acc_first = False  # the last round ran acceptance first
        acc_only = False  # the last round's red checks were all acceptance ones (tl-bxk.13.14)
        where = ({"fix": state.get("fix_n"), "fixes": state.get("fix_of")} if fix else
                 {"stage": i + 1, "stages": len(plan["stages"])})
        while True:
            if not fix:  # a fix runs at land: its checkpoint stays at land, and a resume lands again
                self.save_checkpoint(stage=i, rounds=rounds, n=n, feedback=feedback, step="write")
                self.safe_point("write")  # the round's write, checks and review run on the code that is installed now
            n += 1
            self.stats["writes"] += 1
            if n >= 2:
                self.warn("%s: write %d (round %d)" % (name, n, rounds + 1))
            boundary = n == 1 and i > 0 and not state  # the first write of a later stage
            fresh = self.drop_big_writer(boundary)
            stage_checks = self.stage_checks_text(st["checks"], skip=failed_cmds)
            where_text = self.where("write", [c.cmd for c in self.cfg.checks] + st["checks"], failed_cmds, listed=st["checks"])
            tail = ("\nThe plan's acceptance cases run on the last stage. If you find a case they miss, add it to new_cases (the "
                    "criterion it proves, the check, why); never remove or weaken one." + ("" if last else LATER_CASES) +
                    UNCHECKED_TEXT + self.look_write(st))
            prompt = write_prompt(
                self.rules_text(), brief=self.brief_text(), plan=self.plan_text(), n=i + 1, goal=st["goal"],
                files=", ".join(st["files"]), checks=stage_checks,
                feedback=feedback, evidence=self.evidence_dir, where=where_text, gate=(" (`%s`)" % self.cfg.gate) if self.cfg.gate else "") + tail
            if fresh:
                prompt += self.stages_done_text() if boundary else self.done_so_far()
            dtail = ""  # what a resumed writer still needs that its first prompt did not say for this stage
            if last and not self.writer.get("last_stage"):  # the acceptance cases run now: it has not been told
                dtail += "\nThe plan's acceptance cases run on this last stage. If you find a case they miss, add it to new_cases (the criterion it proves, the check, why); never remove or weaken one."
            if self.unchecked:
                dtail += UNCHECKED_TEXT
            delta = None if fresh else self.write_delta(i + 1, st["goal"], ", ".join(st["files"]), stage_checks, where_text, feedback,
                                                        dtail + self.look_write(st))
            if delta:  # the writer may have edited its copy: the engine's brief goes back before it reads it again
                self.brief_file.write_text(self.brief_text(), encoding="utf-8")
            else:  # a whole prompt (a first write, a fresh writer): what the tasks beside this one are doing (tl-bxk.13.8)
                prompt += self.shared_text() + self.deferred_text()
            w, wfam = self.ai("write", "%s write %d" % (name, n), prompt, delta=delta, resume_key="writer", write=n,
                              visual=self.stage_visual(st), round=rounds + 1, at=(sk, rounds, n), **where)
            self.writer_family = wfam
            self.writer["last_stage"] = last
            wr = self.sessions[-1] if self.sessions else {}
            self.write_rounds.append({"write": n, "round": rounds + 1, "node_id": wr.get("node_id"), "ref": wr.get("ref"),
                                      "resumed": "yes" if wr.get("resume") else "no",
                                      "input_tokens": (wr.get("tokens") or {}).get("in"), "turns": wr.get("turns"),
                                      "prompt_chars": wr.get("prompt_chars"), "context_k": wr.get("context_k"), "fresh": fresh})
            self.writer_said += "\n" + w["summary"]
            self.add_flakes(w.get("flakes") or [])
            self.last_summary = w["summary"]
            wrote_unchecked = w.get("unchecked") or []  # the review decides what is still unproven after the checks
            if w["question"].strip() and w["decided"].strip():  # lifesim-d5f.58: an accepted requirement is no question
                rounds += 1
                self.stats["rounds"] += 1
                self.stuck_why = "the writer asked what an accepted requirement decides: %s" % w["decided"]
                self.warn("%s: %s" % (name, self.stuck_why[:300]))
                if rounds >= int(self.cfg.max_rounds):
                    (self.run_dir / "replan.md").write_text(self.stuck_why + "\n\nThe question: " + w["question"])
                    self.steps.move("replan", "rounds_used", "%d rounds used: %s" % (rounds, self.stuck_why))
                    return "replan"
                self.steps.move("write", "writer_decided", "an accepted requirement decides it: %s" % w["decided"])
                feedback = DECIDED_TEXT % (w["question"], w["decided"])
                continue
            if w["question"].strip():
                self.steps.outcome("asks", w["question"][:200])
                raise Blocked("owner decision needed", question_spec(w), kind=oc.Kind.ASK_DECISION)
            if (self.look_ready(st) and not fix and not shots_fixed and not (w.get("shots") or [])
                    and not (w.get("logic_only") or "").strip()):
                # tl-tno: the review's 'asked for no shots' finding was a writer amend and burned lifesim-d5f.39's re-plan cap; the contract
                # is the engine's to hold: ask again once, with the table, before any check or review runs
                shots_fixed = True
                tip = SHOTS_FIX % looks.table_text(self.shot_methods())
                self.steps.move("write", "shots_contract", "a visual write named no shots and gave no reason: asked once more")
                w2, wfam = self.ai("write", "%s shots contract" % name, prompt + tip, delta=tip, resume_key="writer", write=n,
                                   visual=True, round=rounds + 1, at=(sk, rounds, n + 500), **where)
                self.stats["writes"] += 1
                self.writer_family = wfam
                self.writer["last_stage"] = last
                self.writer_said += "\n" + w2["summary"]
                self.last_summary = w2["summary"]
                if w2["question"].strip():
                    self.steps.outcome("asks", w2["question"][:200])
                    raise Blocked("owner decision needed", question_spec(w2), kind=oc.Kind.ASK_DECISION)
                w = dict(w2, summary=w["summary"] + "\n" + w2["summary"], new_cases=(w.get("new_cases") or []) + (w2.get("new_cases") or []),
                         unchecked=(w.get("unchecked") or []) + (w2.get("unchecked") or []),
                         bad_checks=(w.get("bad_checks") or []) + (w2.get("bad_checks") or []))
            self.add_cases(w.get("new_cases") or [])
            if self.shot_methods() and self.stage_visual(st):
                self.render_stale = True  # a write after the last render: its pictures show an older tree
            back = self.look_step(st, w, name, last)
            if back:  # the look judge found defects: the writer fixes them before the full checks run once
                feedback = back
                continue
            acc_first = acc_only and not acc_first  # once, then the normal order: a check may read what a tests-group check writes
            checks = self.run_checks(dict(st, checks=st["checks"] + (self.case_checks() if last else [])), name,
                                     acceptance_first=acc_first, conflict_fix=state.get("conflict_fix"), round=rounds + 1, **where)
            (self.run_dir / "engine-checks.json").write_text(json.dumps(checks, indent=1))
            (self.run_dir / ("engine-checks.r%d.json" % self.check_round)).write_text(json.dumps(checks, indent=1))
            self.last_checks, self.checks_tree = checks, self.tree_hash()
            self.stats["tests_added"], self.stats["tests_removed"] = count_tests(self.task_diff(), self.cfg.test_pattern)
            if self.stats["tests_removed"]:
                self.warn("the task's diff removes %d tests" % self.stats["tests_removed"])
            failed = [c for c in checks if c["exit"] not in (0, None)]
            prev_red, red_now = red_now, {c["cmd"] for c in failed}  # the commands red last round (tl-bxk.13.11)
            acc_only = bool(failed) and all(c["group"] == "acceptance" for c in failed)
            flagged = {c["cmd"].strip(): why for c in failed for why in [flagged_why(c, w["bad_checks"])] if why}
            wrong = [c for c in failed if c["cmd"].strip() in flagged]
            if wrong:  # a check no code change can satisfy: retrying it is waste, the plan must change
                self.stuck_why = "the writer says these stage checks are wrong: " + "; ".join(
                    "`%s` (exit %s): %s" % (c["cmd"], c["exit"], flagged[c["cmd"].strip()]) for c in wrong)
                self.warn("%s: %s" % (name, self.stuck_why[:300]))
                self.note_round(name, rounds + 1, "bad_checks", w["summary"], [flagged[c["cmd"].strip()] for c in wrong])
                (self.run_dir / "replan.md").write_text(self.stuck_why + "\n\nTheir output:\n" + failure_brief(wrong, self.run_dir))
                self.steps.move("replan", "bad_checks", "the writer says %d check%s cannot pass: %s" % (
                    len(wrong), "" if len(wrong) == 1 else "s", "; ".join(flagged[c["cmd"].strip()] for c in wrong)))
                return "replan"
            if failed:
                red += 1
                failed_cmds = [c["cmd"] for c in failed]
                feedback = ("\nThese checks fail (run by the engine, outside your sandbox). Fix exactly this:\n%s\n"
                            % failure_brief(failed, self.run_dir))
                again = [c["cmd"] for c in failed if c["cmd"] in (prev_red or ()) and c["id"] == c["cmd"]]  # a plan's check, not a repo check
                if again:  # tl-bxk.13.11: lifesim-fdyo tuned contrast to a threshold the plan made up, 3 rounds, 5.98M tokens in one turn
                    feedback += REPEAT_RED % "\n".join("- %s" % c[:200] for c in again)
                red_text = "%d failed: %s" % (len(failed), ", ".join(c["id"][:60] for c in failed))
                self.note_round(name, rounds + 1, "checks_red", w["summary"], [c["id"] for c in failed])
                if red < int(self.cfg.max_check_tries):
                    self.steps.move("write", "checks_red", red_text)
                    continue
                red, rounds = 0, rounds + 1
                self.stats["rounds"] += 1
                self.stuck_why = "checks still red after %s tries: %s" % (self.cfg.max_check_tries, compact(failed))
                if rounds >= int(self.cfg.max_rounds):
                    (self.run_dir / "replan.md").write_text(self.stuck_why + "\n\nTheir output:\n" + failure_brief(failed, self.run_dir))
                    self.steps.move("replan", "rounds_used", "%s; %d rounds used" % (red_text, rounds))
                    return "replan"
                self.steps.move("write", "checks_red", "%s; round %d used" % (red_text, rounds))
                continue
            red = 0
            self.steps.move("review", "checks_green", "%d passed" % sum(1 for c in checks if c["exit"] == 0))
            self.stats["reviews"] += 1
            open_items = list({u["what"]: u for u in ([] if fix else self.unchecked) + wrote_unchecked}.values())
            kinds = self.new_by_kind()
            review, _ = self.ai("review", name, review_prompt(
                brief=self.brief_text(), plan=self.plan_text(), n=i + 1, goal=st["goal"],
                work=self.stage_work(kinds["unexplained"], kinds["ignored"]), checks=compact(checks), summary=w["summary"], evidence=self.evidence_dir,
                gate=(" (`%s`)" % self.cfg.gate) if self.cfg.gate else "",
                added=self.stats["tests_added"], removed=self.stats["tests_removed"],
                fix=fix, last=last, fix_scope=state["scope"] if fix else "") +
                ("\n" + self.where("review") if self.where("review") else "") + self.cases_text() +
                ("The engine ran every case above with the checks, so a case is never an unchecked item; a case whose "
                 "check does not prove its criterion is a finding.\n" if last and self.case_checks() else "") +
                ("\nNobody has checked these yet (earlier stages or the writer could not; the engine's checks above ran "
                 "after them); put in your unchecked only what is still unproven:\n" + "".join(
                     "- %s (%s)\n" % (u["what"], u["kind"]) for u in open_items) if open_items else "") +
                ("" if last else LATER_CASES) + self.deferred_text() + self.seen_lows_text() + self.flakes_text() + UNCHECKED_TEXT + self.look_review(st, w, fix) +
                (self.new_files_brief(kinds["unexplained"]) if kinds["unexplained"] else ""),
                writer_family=wfam, visual=not fix and self.stage_visual(st), round=rounds + 1, at=(sk, rounds, n), **where)
            self.accepted_new += [p for p in review.get("accept_files") or [] if p in kinds["unexplained"] and p not in self.accepted_new]
            review = dict(review, findings=list(review["findings"]))
            kept = [u for u in review["unmet"] if not self.ledger_route(u)]  # tl-bxk.13.16.1: the ledger settles these
            if len(kept) != len(review["unmet"]):
                self.log.note("%d unmet item%s dropped: the plan's ledger defers or gives them to the engine: %s" % (
                    len(review["unmet"]) - len(kept), "" if len(review["unmet"]) - len(kept) == 1 else "s",
                    "; ".join(u[:80] for u in review["unmet"] if u not in kept)))
                review["unmet"] = kept
            for p in self.undecided_new(kinds["unexplained"], review):  # never a silent drop: the writer names it or deletes it
                review["findings"].append({"file": p, "line": 0, "severity": "medium", "fix":
                    "decide: unexplained new file %s (name it in your summary if the task needs it, else delete it)" % p})
            # lifesim-gfr.31.1: a stage-1 item that stage 2 ran green still stopped the land; each review re-judges what
            # is open, so its list replaces it. A fix at land reviews only the fix: it adds, never clears.
            judged = self.out_of_scope(self.engine_unproven(review.get("unchecked") or [], checks))
            self.unchecked = self.unchecked + judged if fix else judged
            self.look_judged(review, st, w, fix)
            self.link_judged(review)
            same = self.last_flag == "same_family"
            if same:
                self.warn("%s: the review is from the writer's own model family (no other lane was free)" % name)
            if review["findings"] or review["unmet"] or same:
                self.comment("Review (engine, %s%s): " % (name, ", same family as the writer" if same else "") + "; ".join(
                    ["%s:%s [%s] %s" % (f["file"], f["line"], f["severity"], f["fix"]) for f in review["findings"]] +
                    ["unmet: " + u for u in review["unmet"]]) or "no findings")
            self.leftovers += review["leftovers"]
            self.note_lows(review["findings"])
            if review["question"].strip() and review["decided"].strip():  # lifesim-d5f.58: a fix round, not an ask
                self.log.note("%s: the review asked what an accepted requirement decides (%s): sending it back"
                         % (name, review["decided"][:200]))
                review["unmet"] = review["unmet"] + ["%s (an accepted requirement decides it: meet it) %s" % (
                    review["decided"], review["question"])]
            elif review["question"].strip():
                self.steps.outcome("asks", review["question"][:200])
                raise Blocked("owner decision needed", askspecs.open_question(review["question"], review.get("options")), kind=oc.Kind.ASK_DECISION)
            blocking = [f for f in review["findings"] if f["severity"] in ("high", "medium")]
            said = "%d finding%s, %d unmet" % (len(blocking), "" if len(blocking) == 1 else "s", len(review["unmet"]))
            if not blocking and not review["unmet"]:
                low = len(review["findings"])
                self.steps.outcome("clean", "%d low finding%s" % (low, "" if low == 1 else "s") if low else "")
                self.steps.move("next", "accepted", "%s accepted" % name)
                return "accept"
            self.steps.outcome("sent back", said)
            self.note_round(name, rounds + 1, "review", w["summary"], review["unmet"] + [
                "%s:%s %s" % (f["file"], f["line"], f["fix"]) for f in blocking])
            rounds += 1
            self.stats["rounds"] += 1
            self.stuck_why = "the review still sends it back: %s" % "; ".join(
                review["unmet"] + ["%s:%s %s" % (f["file"], f["line"], f["fix"]) for f in blocking])
            if rounds >= int(self.cfg.max_rounds):
                (self.run_dir / "replan.md").write_text(self.stuck_why)
                self.steps.move("replan", "rounds_used", "review sent it back: %s; %d rounds used" % (said, rounds))
                return "replan"
            failed_cmds = None
            self.steps.move("write", "review_sendback", "%s: round %d" % (said, rounds + 1))
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
        if cmd == self.cfg.gate:
            return True
        return s > float(self.cfg.writer_check_max_s) if s is not None else bool(SLOW_CMD.search(cmd))

    def stage_checks_text(self, checks, skip=None):
        """The stage's check list split for the writer: the fast ones it may run, the slow ones the engine runs alone.
        `skip`: the commands the last engine run found red: where() lists those, so each command is named once (tl-7y6.6.12)."""
        checks = list(dict.fromkeys(checks))
        if not checks:
            return "- (none named)"
        if skip is not None:
            gone = {norm_cmd(c) for c in skip}
            checks = [c for c in checks if norm_cmd(c) not in gone]
            if not checks:
                return "- (the failed ones are listed below)"
        secs = self.check_secs()
        slow = [c for c in checks if self.engine_only(c, secs)]
        fast = [c for c in checks if c not in slow]
        text = ""
        if fast:
            text += "You may run these:\n" + "\n".join("- " + c for c in fast)
        if slow:
            text += ("\n" if text else "") + "The engine runs these, do not run them:\n" + "\n".join("- " + c for c in slow)
        return text

    def where(self, node, checks=(), failed=None, listed=()):
        """What the step is for, never what its sandbox allows: delegate tells each worker that (worker-run v2).
        For the writer: which checks it may run (fast ones) and which are the engine's (slow ones), minus `listed` (the
        commands the stage's own check list already names)."""
        if node == "write":
            secs = self.check_secs()
            pool = list(dict.fromkeys(checks)) if failed is None else list(dict.fromkeys(failed))
            if failed is None:  # the stage's own checks are in stage_checks_text: name each command once (tl-7y6.6.12)
                have = {norm_cmd(c) for c in listed}
                pool = [c for c in pool if norm_cmd(c) not in have]
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
        state = self.tree_state()
        memo = getattr(self, "_tree_hash_memo", None)
        if state and memo and memo[0] == state:
            return memo[1]
        with tempfile.TemporaryDirectory() as d:
            env = dict(tl.git_env(self.wt), GIT_INDEX_FILE=os.path.join(d, "index"))
            for args in (["read-tree", "HEAD"], ["add", "-A"], ["write-tree"]):
                r = subprocess.run(["git"] + args, cwd=self.wt, env=env, capture_output=True, text=True)
                if r.returncode != 0:
                    raise TreeHashError("git %s failed (%d): %s" % (args[0], r.returncode, (r.stderr or "").strip()[:300]))
        if state:
            self._tree_hash_memo = (state, r.stdout.strip())
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
        out = self._run_checks(st, name, acceptance_first=acceptance_first, groups=groups, conflict_fix=conflict_fix, **meta)
        self.assert_tree("checks", "after")
        return out

    def _run_checks(self, st, name, acceptance_first=False, groups=None, conflict_fix=None, **meta):
        """One engine step, no AI: the repo's checks (engine.checks) and the stage's acceptance checks, grouped
        static → tests → acceptance; a red group skips the groups after it. A repo check with `when` runs only when the
        task changed a matching path; `retry` reruns a red one (known flaky). A repo check that passed on the same tree
        and base is not run again, unless it says `"cache": false`; a stage check always runs, since a plan's check can
        read what git cannot see (a running editor, a log, a bead comment). The gate is not here: it runs once, on the rebased tree, at land.
        conflict_fix (tl-7y6.2.18; the plan's check commands the fix skips, else None): a conflict fix runs the marker check and
        the repo's build checks only; every other check is recorded as skipped (conflict_fix) and the gate verifies the result."""
        self.steps.begin("checks", "checks: %s" % name, **meta)
        self.check_round += 1
        items = [{"id": c.id, "cmd": c.cmd, "group": c.group, "when": list(c.when), "retry": c.retry,
                  "timeout": float(c.timeout_min or self.cfg.check_timeout_min), "cache": c.cache is not False,
                  "idle": float(self.cfg.check_idle_min if c.idle_min is None else c.idle_min) * 60,
                  "inputs": check_inputs(c), "inputs_only": c.inputs_only, "exclude": list(c.exclude), "env": dict(c.env),
                  "repo": True} for c in self.cfg.checks]
        items += [{"id": c, "cmd": c, "group": "acceptance", "when": [], "retry": 0,
                   "timeout": float(self.cfg.check_timeout_min), "cache": False, "inputs": [], "inputs_only": False, "env": {},
                   "idle": float(self.cfg.check_idle_min or 0) * 60} for c in st["checks"]]
        pre_skipped = []
        if conflict_fix is not None:
            keep = [c for c in items if c["cmd"] == self.MARKERS or (c.get("repo") and CONFLICT_BUILD.search(c["id"] + " " + c["cmd"]))]
            pre_skipped = [dict(cmd=c["cmd"], id=c["id"], group=c["group"], exit=None, status="skipped", why="conflict_fix", tail="")
                           for c in items if c not in keep]
            pre_skipped += [dict(cmd=x, id=x, group="acceptance", exit=None, status="skipped", why="conflict_fix", tail="")
                            for x in dict.fromkeys(conflict_fix) if x != self.MARKERS and x not in {c["cmd"] for c in items}]
            items = keep
        if groups:  # tl-bxk.13.15: only these groups (the cheap checks before a render)
            items = [c for c in items if c["group"] in groups]
        # Cheapest first, by the median of earlier runs of the same command (unknown = cheap), so a red verdict comes
        # before the slow Unity runs. A check reading $TL_CHECK_LOG_<X> stays after X. When the last round failed only in
        # acceptance, acceptance goes before tests at equal cost (tl-bxk.13.14: lifesim-fdyo reran 11 minutes of unity tests
        # before a 3-second verdict check failed).
        history = cs.load_durations(self.wt)
        # A stage check whose segment is exactly a repo check's command (`mkdir -p e && just unity-tests > e/log && grep ...`)
        # reads that check's log instead of running it again, when the repo check ran green in this round (see cs.reuse_log).
        # Anything else (args, an env prefix, `||`, `!`, a subshell, a quoted mention) runs as written, and so does the repo check.
        repo = [c for c in items if c["group"] != "acceptance"]
        needs = {}  # id(wrapper) -> [repo checks whose log it reads]
        for w in items:
            if w["group"] != "acceptance":
                continue
            cmd_w = w["cmd"]
            for r in repo:
                var = lint.check_env_name(r["id"])
                if not cs.contains_cmd(cmd_w, r["cmd"], unquoted=True) or var in cmd_w or var.replace("_LOG_", "_RC_") in cmd_w:
                    continue
                new = cs.reuse_log(cmd_w, r["cmd"], var, self.wt)
                if new:
                    cmd_w = new
                    needs.setdefault(id(w), []).append(r)
            w["run_cmd"] = cmd_w
        rank = {"static": 0, "acceptance": 1, "tests": 2} if acceptance_first else {"static": 0, "tests": 1, "acceptance": 2}
        env_of = {lint.check_env_name(c["id"])[len("TL_CHECK_LOG_"):]: c for c in items if c["group"] != "acceptance"}
        deps = {id(c): [env_of[m] for m in dict.fromkeys(re.findall(r"TL_CHECK_(?:LOG|RC)_(\w+)", c["cmd"])) if m in env_of]
                + needs.get(id(c), []) for c in items}
        # tl-7y6.7.16: the Unity group (a repo check naming Unity) goes last: an acceptance check that reads no TL_CHECK_* is
        # judged before it, and a red anywhere skips the Unity group with the reason. An acceptance copy of a repo check
        # waits for that check and takes its result (tl-7y6.7.11).
        unity = {id(c) for c in repo if cs.UNITY.search(c["id"] + " " + c["cmd"])}
        for w in items:
            if w["group"] == "acceptance":
                deps[id(w)] += [r for r in repo if cs.canon(r["cmd"]) == cs.canon(w["cmd"]) and r not in deps[id(w)]]
        items = cs.order_by_cost(items, history, lambda c: rank.get(c["group"], 1), deps, late=unity)
        cache_path = tl.config_dir() / "check-cache" / ("%s.json" % self.bead)
        try:
            cache = json.loads(cache_path.read_text())
        except (OSError, ValueError):
            cache = {}
        tree = self.tree_hash()
        key = "%s %s" % (tree, self.git("rev-parse", self.cfg.base))
        by_inputs = cache.get("inputs") if isinstance(cache.get("inputs"), dict) else {}  # per-check: command + hash of its `inputs` files
        keys = cs.InputKeys(self.wt, tree, self.git("rev-parse", self.cfg.base))  # per-check keys, listed lazily
        logs = self.run_dir / "checks"
        logs.mkdir(exist_ok=True)
        timings = []  # (cmd, secs) of what ran, for the duration history
        red_skipped = set()  # ids of items left out because a group was red
        out, red, changed, ran, env_logs = list(pre_skipped), None, None, {}, {}  # ran: what ran in this block -> its result; env_logs: its logs, for later checks
        for n, c in enumerate(items):
            base = {"cmd": c["cmd"], "id": c["id"], "group": c["group"]}
            if red and (c["group"] != red or cs.expected_secs(c["cmd"], history) >= cs.CHEAP_S or id(c) in unity
                        or any(id(d) in red_skipped for d in deps.get(id(c), ()))):  # a check reading a skipped check's log has none
                # a red group skips the groups after it, and any red skips every expensive check (the cheap ones of its own
                # group run to the end, so the writer sees all the cheap failures at once; the Unity group never runs after a red)
                out.append(dict(base, exit=None, status="skipped", why="%s failed first" % red, tail=""))
                self.checklog.close(c, out[-1], None, self.check_round)
                red_skipped.add(id(c))
                continue
            if c["when"]:
                changed = self.changed_paths() if changed is None else changed
                if not any(fnmatch.fnmatch(p, g) for p in changed for g in c["when"]):
                    out.append(dict(base, exit=None, status="skipped", tail="",
                                    why="no change under %s" % ", ".join(c["when"])))
                    self.checklog.close(c, out[-1], None, self.check_round)
                    continue
            cmd = c["cmd"]
            same = (cs.canon(cmd), str(self.wt))  # what a result is a fact about: the command (setup and redirects aside), directory
            seen_before = ran.get(same)
            # each distinct command runs once per block (tl-bxk.10.27), whatever limit its copy carries (tl-7y6.7.11); the limit
            # matters only when the first run timed out under a shorter one. A green wrapper that reads a repo check's log runs
            # its own part instead (it writes the file the rest of the plan reads); a red one is not launched again.
            if seen_before and (seen_before[0]["exit"] != 124 or seen_before[1] >= c["timeout"]) and not (
                    seen_before[0]["exit"] == 0 and id(c) in needs and norm_cmd(cmd) != same[0]):
                self.log.note("`%s` already ran in this block: its result is reused" % cmd[:120])
                res = dict(seen_before[0], **base)
                res.update(cached=False, reused=True)
                out.append(res)
                self.checklog.close(c, res, None, self.check_round)
                if res["exit"] != 0:
                    red = c["group"]
                continue
            ikey, nocache, cid = "", False, None
            if c["cache"] and c["inputs"]:  # a green result is a fact about the check's own inputs, not the whole tree or base
                ikey = keys.key(c)
                dead = keys.dead(c)
                for g in dead:
                    self.warn("inputs glob %s matches no tracked file; not cached" % g)
                if dead:  # a glob that selects nothing would cache a green over changed code
                    ikey = ""
                    nocache = True
                hit = by_inputs.get(ikey) if ikey else None
            else:
                hit = c["cache"] and cache.get(key, {}).get(c["cmd"])
            if hit:
                res = dict(base, **hit)
                res.update(cached=True, status=hit.get("status") or ("ran" if hit["exit"] == 0 else "failed"))
                if ikey:
                    res["cached_note"] = "inputs unchanged since round %s" % (hit.get("round") or "?")
                    self.log.note("cached: %s, %s" % (c["id"], res["cached_note"]))
            else:
                t, tries, seen = time.time(), 0, ""
                xcmd, reads = cmd, needs.get(id(c), [])
                if reads and all(lint.check_env_name(r["id"]) in env_logs and env_logs.get(lint.check_env_name(r["id"]).replace("_LOG_", "_RC_")) == "0"
                                 for r in reads):
                    xcmd = c["run_cmd"]
                    self.log.note("`%s` reuses the log of %s: only its own part runs" % (cmd[:100], ", ".join("`%s`" % r["id"] for r in reads)))
                log_name = "%02d-%s.r%d.log" % (n, re.sub(r"[^\w.-]+", "_", c["id"])[:40], self.check_round)
                cid = self.checklog.start(c, self.check_round, "checks/" + log_name)
                while True:
                    tries += 1
                    t_try = time.time()
                    rc, tail = self.sh(xcmd, timeout=c["timeout"] * 60, save=logs / log_name, env=env_logs, idle=c["idle"])
                    hung = self.hung
                    try:
                        seen = (logs / log_name).read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        seen = tail
                    self.note_slot_waits(seen, time.time() - t_try)
                    if rc == 0:
                        break
                    if hung:  # silent for check_idle_min: a rerun hangs the same way, and this round has waited enough
                        self.warn("`%s` hung: no output, file writes or CPU for %g min, stopped; not retried" % (c["id"], c["idle"] / 60))
                        break
                    if rc == 124:  # the engine's timeout or the command's own: a rerun hangs the same way
                        if c["retry"]:
                            self.warn("`%s` failed (exit 124), no retry: timed out after %g min" % (
                                c["id"], round((time.time() - t_try) / 60, 1)))
                        break
                    kind = failure_kind(seen)
                    if kind == "deterministic":  # a rerun fails the same way, seconds later (tl-bxk.10.17)
                        if c["retry"]:
                            self.warn("`%s` failed (exit %d) with a compile error: not retried" % (c["id"], rc))
                        break
                    if kind == "lock":
                        for w_n, wait in enumerate(lock_waits(), 1):
                            self.warn("`%s` is held by an editor or project lock; waiting %d s (%d)" % (c["id"], wait, w_n))
                            wid = self.wait_start(WaitWhat.EDITOR_LOCK)
                            time.sleep(wait)
                            self.add_wait(wait, WaitWhat.EDITOR_LOCK, wid)
                            rc, tail = self.sh(xcmd, timeout=c["timeout"] * 60, save=logs / log_name, env=env_logs)
                            seen = (logs / log_name).read_text(encoding="utf-8", errors="replace")
                            self.note_slot_waits(seen, time.time() - t_try)
                            if rc == 0 or failure_kind(seen) != "lock":
                                break
                        if rc and failure_kind(seen) == "lock":
                            pid = lock_holder(seen, self.wt)
                            tail += "\n(still locked after %d s of waiting%s)" % (
                                LOCK_WAIT_MAX, "; the lock holder is pid " + pid if pid else "")
                        break
                    if tries > (max(c["retry"], 1) if kind == "import" else c["retry"]):
                        break
                    self.warn("`%s` failed (exit %d), retrying: it is marked flaky" % (c["id"], rc))
                if rc and c.get("repo"):
                    stale = STALE_TREE.search((seen or tail)[-500:])  # its last lines: a test that talks about recipes is no stale tree
                    if stale:  # tl-fsj: not a writer's amend; the engine's tree is older than the config it runs
                        raise Blocked("failed: infrastructure: the configured check `%s` needs something this tree lacks (\"%s\"): the "
                                      "tree is older than the base's .task-loop.json, which no writer can fix" % (c["id"], stale.group(0)), kind=oc.Kind.FAULT_STALE_BASE)
                if rc is not None and rc < 0 and not hung and not self.killed:  # tl-y35: a signal ended it, not its verdict
                    raise Blocked("failed: stopped: check `%s` was killed by signal %d; the bead goes back to open and the next run "
                                  "runs it again (no fix round, no failure counted)" % (c["id"], -rc), kind=oc.Kind.PAUSE_KILLED)
                res = dict(base, exit=rc, status="ran" if rc == 0 else "failed", tries=tries, tail=tail[-1500:],
                           secs=round(time.time() - t), log="checks/" + log_name, log_abs=str(logs / log_name), hung=bool(hung))
                if hung:
                    res["tail"] = "HUNG (no output, file writes or CPU for %g min), last output:\n%s" % (c["idle"] / 60, tail[-1400:])
                if rc == 0:  # only a green run says what the check costs: a red one stops early
                    timings.append((cmd, time.time() - t))
                if rc == 0 and c["cache"] and not nocache:  # only a pass is a fact about the tree; a failure can come from outside git (stale
                    if ikey:  # build output, a held editor, a flake) and must rerun
                        by_inputs = {k: v for k, v in by_inputs.items() if v.get("cmd") != c["cmd"]}  # one entry per check
                        by_inputs[ikey] = dict(res, round=self.check_round)
                    else:
                        cache.setdefault(key, {})[c["cmd"]] = res
            out.append(res)
            self.checklog.close(c, res, cid, self.check_round)
            ran[same] = (res, c["timeout"])
            if c["group"] != "acceptance" and res.get("exit") is not None:  # later checks read its log: $TL_CHECK_LOG_<ID>
                lp = (logs / log_name) if not res.get("cached") else (
                    Path(res["log_abs"]) if res.get("log_abs") and Path(res["log_abs"]).is_file() else self.run_dir / res.get("log", ""))
                if lp.is_file():
                    env_logs[lint.check_env_name(c["id"])], env_logs[lint.check_env_name(c["id"]).replace("_LOG_", "_RC_")] = str(lp), str(res["exit"])
            if res["exit"] != 0:
                red = c["group"]
        for c in out:
            mark = "⏸ hung" if c.get("hung") else {"ran": "✓", "failed": "✗", "skipped": "–"}[c["status"]]
            self.detail(["%s [%s] `%s` %s%s" % (mark, c["group"], c["id"], c["status"] if c["exit"] is None else
                                                "exit %d" % c["exit"], " (" + c["why"] + ")" if c.get("why") else
                                                " (%s)" % (c.get("cached_note") or "same tree and base: earlier result") if c.get("cached") else
                                                " (same command ran earlier in this block)" if c.get("reused") else "")] +
                        (c["tail"].splitlines()[-(8 if c.get("hung") else 3):] if c["status"] == "failed" else []))
        cache_path.parent.mkdir(exist_ok=True)
        cs.record_durations(self.wt, timings)
        saved = {key: cache[key]} if key in cache else {}  # only the latest tree is worth keeping
        if by_inputs:
            saved["inputs"] = by_inputs
        cache_path.write_text(json.dumps(saved))
        bad = [c for c in out if c["status"] == "failed"]
        hung = [c for c in bad if c.get("hung")]
        self.steps.outcome("red" if bad else "green", "%d failed%s: %s" % (len(bad), " (%d hung: no output, file writes or CPU, stopped)" % len(hung) if hung else "",
                                                                       ", ".join(c["id"][:60] for c in bad))
                        if bad else "%d passed" % sum(1 for c in out if c["status"] == "ran"))
        self.checklog.round(self.steps.id, self.check_round, out, tree)
        return out

    def landed_already(self, fetch=True):
        """tl-7y6.2.13: a push that died of the network after origin took it. The task branch's tip is the land commit
        (titled `... (<bead>)`) and it is on the base: it landed, and nothing is pushed twice. -> its sha, or ''."""
        if self.dry or (fetch and self.fetch()[0]):
            return ""
        tip = self.git("rev-parse", "--verify", "-q", "HEAD")
        if not tip or not self.git("log", "-1", "--format=%s").endswith("(%s)" % self.bead):
            return ""
        return tip if self.sh(["git", "merge-base", "--is-ancestor", tip, self.cfg.base], pin=True)[0] == 0 else ""

    def landed_found(self, sha):
        self.landed_sha = sha
        tl.cmd_land(Args(id=self.bead, sha=sha, worktree=self.wt))
        self.steps.outcome("landed", sha[:12])
        self.warn("the push had already gone through (%s is on %s): not pushed again" % (sha[:12], self.cfg.base))
        return sha

    def finish(self, bead):
        if self.pending_land_validation:
            raise Blocked("land retry validation still needs accepted checks and review; branch kept", kind=oc.Kind.FAULT_LAND)
        found = self.landed_already()  # the last run's push may have gone through before the network cut its answer
        if found:
            return self.landed_found(found)
        if not self.git("status", "--porcelain"):
            if self.git("rev-list", "--count", "%s..HEAD" % self.cfg.base) in ("", "0"):
                self.log.note("nothing changed")
                return ""
        # one commit per task, titled after the bead: earlier runs' wip commits are folded in
        base = self.git("merge-base", "HEAD", self.cfg.base)
        if base:
            self.sh(["git", "reset", "-q", "--soft", base], check=True, pin=True)
        self.copy_looks()
        self.stage_all(check=True)
        self.quarantine_strays()
        msg = "%s (%s)" % (bead.title[:72], self.bead)
        rc, tail = self.sh(["git", "commit", "-q", "-m", msg], pin=True)
        if rc:
            raise Blocked("failed: commit refused (hooks)\n" + tail, kind=oc.Kind.FAULT_LAND)
        if self.dry:
            self.log.note("dry run: not landing")
            return ""
        flaky_push, rest, net_failed = 0, False, False
        self.task_branch = self.git("symbolic-ref", "--short", "-q", "HEAD")
        while True:  # one land at a time per repo: rebase, gate and push see the latest base; a fix runs outside the lock
            problem = None
            if rest:  # a network failure, with the lock let go: wait for the network, then fetch and look again
                waited, back = self.worker.acts.await_net(self.worker.acts.net_up(), lp.KNOBS["net_wait_cap_s"])
                if not back:
                    raise Blocked("paused: no network for the land push after %d s; the branch is kept and the next run lands it" % waited,
                                  kind=oc.Kind.PAUSE_NETWORK)
                rest = False
            with self.land_lock():
                pushes = 0
                while True:  # initial push plus at most two main-moved retries in this hold
                    self.steps.begin("land", "land (try %d)" % (pushes + 1), **{"try": pushes + 1})
                    self.quarantine_strays()
                    rc, tail = self.fetch()
                    if rc == 0 and (pushes or net_failed):
                        found = self.landed_already(fetch=False)  # an earlier push of this land may have gone through
                        if found:
                            return self.landed_found(found)
                    if rc == 0:
                        rc, tail = self.sh(["git", "rebase", "-q", self.cfg.base], pin=True)
                    if rc:
                        unmerged = self.git("diff", "--name-only", "--diff-filter=U")
                        if not unmerged:
                            self.sh(["git", "rebase", "--abort"], pin=True)
                            raise Blocked("failed: fetch or rebase onto %s failed; branch kept\n%s" % (self.cfg.base, tail), kind=oc.Kind.FAULT_LAND)
                        problem = ("conflict", "Conflicted files: %s\n%s" % (", ".join(unmerged.split()), tail))
                        self.steps.outcome("conflict", ", ".join(unmerged.split()))
                    if not problem and pushes:
                        # Revalidate the rebased inputs. Repo checks reuse their input cache; stage/case checks
                        # remain conservative because they can depend on state outside the tracked tree.
                        checks = list(dict.fromkeys(c for st in (self.plan_data or {}).get("stages") or []
                                                    for c in st["checks"]))
                        checks = list(dict.fromkeys(checks + self.case_checks()))
                        # A stop during checks or just after they return must resume through acceptance.
                        # Save that barrier first, then let sh() receive SIGTERM and stop its process tree.
                        with self.stop_deferred() as stop:
                            self.pending_land_validation = "land retry checks require successful checks and review before landing"
                            self.save_checkpoint(stage=len((self.plan_data or {}).get("stages") or []), rounds=0, n=0,
                                                 feedback="", step="land-verify-red")
                        if stop:
                            raise Blocked("failed: stopped (SIGTERM)", kind=oc.Kind.PAUSE_KILLED)
                        results = self.run_checks({"checks": checks, "files": []}, "land retry")
                        with self.stop_deferred() as stop:
                            bad = [c for c in results if c["status"] == "failed"]
                            if bad:
                                problem = ("verify", failure_brief(bad, self.run_dir))
                                self.pending_land_validation = problem[1]
                            else:
                                self.pending_land_validation = ""
                            self.save_checkpoint(stage=len((self.plan_data or {}).get("stages") or []), rounds=0, n=0,
                                                 feedback="", step="land-verify-red" if bad else "land")
                        if stop:
                            raise Blocked("failed: stopped (SIGTERM)", kind=oc.Kind.PAUSE_KILLED)
                        self.steps.begin("land", "land (try %d)" % (pushes + 1), **{"try": pushes + 1})
                    if not problem and self.cfg.gate:
                        self.gate_log = self.run_dir / ("gate.r%d.log" % (self.fixes + 1))
                        gtree = self.git("rev-parse", "HEAD^{tree}")
                        gate_t, gate_skipped = time.time(), False
                        self.log.emit(rec.GateStart(cmd=self.cfg.gate, log=str(self.gate_log), tree=gtree))
                        if self.gate_green(gtree):  # the gate already passed on exactly this tree (a push rejected, a re-land)
                            self.log.note("gate skipped: `%s` already passed on tree %s" % (self.cfg.gate[:80], gtree[:12]))
                            rc, tail, gate_skipped = 0, "", True
                        else:
                            green = self.green_checks(gtree)  # repo checks green on this tree's inputs: the gate may skip their part
                            rc, tail = self.sh(self.cfg.gate, save=self.gate_log, timeout=float(self.cfg.gate_timeout_min) * 60,
                                               env={"TL_CHECKS_GREEN": ",".join(green)} if green else None)
                            if rc == 0:
                                self.gate_record(gtree)
                        self.log.emit(rec.GateEnd(exit=rc, secs=round(time.time() - gate_t), skipped=gate_skipped))
                        if rc < 0 and not self.killed:  # tl-y35: killed by a signal (an operator's SIGTERM, the machine): not the code's fault
                            raise Blocked("failed: stopped: the gate was killed by signal %d; the bead goes back to open and the next run "
                                          "runs the gate again (no fix round, no failure counted)" % -rc, kind=oc.Kind.PAUSE_KILLED)
                        if rc:
                            problem = ("gate", tail)
                            self.steps.outcome("gate red", (tail.strip().splitlines() or [""])[-1])
                    if not problem:
                        with self.stop_deferred() as stop:  # a push half done is no state to stop in: finish it, then stop
                            gated = self.git("rev-parse", "HEAD^{tree}")  # a pre-push hook may skip a gate this exact tree passed
                            rc, tail = self.sh(self.cfg.land, pin=True, env={"TASK_LOOP_GATED_TREE": gated, "TL_GATE_PASSED": gated}
                                               if self.cfg.gate else None)
                            if rc == 0:
                                self.landed_sha = sha = self.git("rev-parse", "HEAD")
                                tl.cmd_land(Args(id=self.bead, sha=sha, worktree=self.wt))
                        if rc == 0:
                            self.steps.outcome("landed", sha[:12])
                            if stop:
                                self.warn("a stop came during the land: landed first, closing now")
                            return sha
                        if stop:
                            raise Blocked("failed: stopped (SIGTERM)", kind=oc.Kind.PAUSE_KILLED)
                        if not re.search(r"rejected|non-fast-forward|fetch first|stale info", tail):
                            if TRANSIENT_PUSH.search(tail[-600:]):  # the push's own last lines, not a hook's test output before them
                                if self.worker.acts.net_up() is not False:  # the probe cannot see the fault: counted, a proxy or DNS looks like this
                                    flaky_push += 1
                                if flaky_push >= PUSH_UP_FAILS:
                                    raise Blocked("paused: the land push failed %d times with a network error while the network looks up; "
                                                  "the branch is kept and the next run lands it again: %s" % (flaky_push, tail.strip()[-200:]),
                                                  kind=oc.Kind.PAUSE_NETWORK)
                                rest = net_failed = True
                                self.warn("the push failed with a network error, trying again when the network is back: %s" % tail.strip()[-160:])
                                self.steps.move("land", "push_network", "network error on the push; the land looks again after the network is back")
                                break
                            raise Blocked("land failed\n" + tail, kind=oc.Kind.FAULT_LAND)
                        pushes += 1
                        self.steps.outcome("rejected", "main moved")
                        if pushes >= 3:
                            raise Blocked("land rejected 3 times: main moves too fast", kind=oc.Kind.FAULT_LAND)
                        self.warn("push rejected (main moved), try %d of 3" % (pushes + 1))
                        self.steps.move("land", "push_race", "push rejected (main moved): try %d of 3" % (pushes + 1))
                        continue
                    break  # a red check/gate or conflict is fixed outside the land lock
            if rest:
                continue
            if self.fixes < int(self.cfg.max_fix_rounds):
                self.steps.move("fix", {"gate": "gate_red", "verify": "checks_red", "conflict": "conflict"}[problem[0]],
                                "gate red on the rebased tree: %s" % (problem[1].strip().splitlines() or [""])[-1][:200]
                                if problem[0] == "gate" else problem[1].splitlines()[0])
            fixed = self.fix(*problem)
            if problem[0] == "verify" and fixed != "accept":
                self.pending_land_validation += "\n" + self.stuck_why
                self.save_checkpoint(stage=len((self.plan_data or {}).get("stages") or []), rounds=0, n=0,
                                     feedback="", step="land-verify-red")
                raise Blocked("land retry validation fix did not pass its checks and review; branch kept", kind=oc.Kind.FAULT_LAND)
            if problem[0] == "verify":
                self.pending_land_validation = ""
                self.save_checkpoint(stage=len((self.plan_data or {}).get("stages") or []), rounds=0, n=0,
                                     feedback="", step="land")
            if problem[0] == "verify" and self.git("status", "--porcelain"):
                # Unlike verification before finish(), a retry check's fix follows the task commit.
                self.stage_all(check=True)
                self.sh(["git", "commit", "-q", "--no-verify", "--amend", "--no-edit"], check=True, pin=True)

    def gate_file(self):
        return tl.config_dir() / "check-cache" / ("%s.gate.json" % self.bead)

    def gate_green(self, tree):
        try:
            got = json.loads(self.gate_file().read_text())
        except (OSError, ValueError):
            return False
        return bool(tree) and got.get("tree") == tree and got.get("cmd") == cs.norm(self.cfg.gate or "")

    def gate_record(self, tree):
        try:
            self.gate_file().write_text(json.dumps({"tree": tree, "cmd": cs.norm(self.cfg.gate or "")}))
        except OSError:
            pass

    def green_checks(self, tree):
        """Ids of the repo checks with a green result on this tree: by their inputs hash, else by tree and base."""
        try:
            cache = json.loads((tl.config_dir() / "check-cache" / ("%s.json" % self.bead)).read_text())
        except (OSError, ValueError):
            return []
        by_inputs = cache.get("inputs") if isinstance(cache.get("inputs"), dict) else {}
        whole = cache.get("%s %s" % (tree, self.git("rev-parse", self.cfg.base))) or {}
        keys, out = cs.InputKeys(self.wt, tree, self.git("rev-parse", self.cfg.base)), []
        for c in self.cfg.checks:
            if c.cache is False:
                continue
            d = dict(dataclasses.asdict(c), inputs=check_inputs(c))
            if d["inputs"]:
                ok = not keys.dead(d) and bool(by_inputs.get(keys.key(d) or "-"))
            else:
                ok = c.cmd in whole
            if ok:
                out.append(c.id)
        return out

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

    def fix(self, kind, tail, resume=False):
        """One fix round at land: write → checks (a conflict fix: markers and build only; else every stage's checks, again) → a review of the fix only. A gate fix is
        folded into the task's commit; a conflict fix continues the rebase; a verify fix (what the verifier found wrong,
        before the task's commit) stays in the tree. max_fix_rounds per bead, then stuck. Returns the fix stage's end.
        resume: the conflict is the resume rebase's (tl-7y6.2.19), so the checkpoint stays where it is."""
        self.fixes += 1
        limit = int(self.cfg.max_fix_rounds)
        what = {"gate": "gate red on the rebased tree", "conflict": "merge conflict with main",
                "verify": "the check before land found defects"}[kind]
        if self.fixes > limit:
            if kind == "conflict":
                self.sh(["git", "rebase", "--abort"], pin=True)
            trimmed = trim.trim_log(tail, log=str(getattr(self, "gate_log", "") or "") if kind == "gate" else "")
            raise (FixFailed if kind == "conflict" else Blocked)("%s after %d fix rounds: it needs the owner's hint\n%s" % (
                what, limit, trimmed), askspecs.no_progress(what, limit, trimmed), kind=oc.Kind.ASK_STUCK)
        self.warn("%s: %s, fix round %d of %d" % ("resume" if resume else "land", what, self.fixes, limit))
        if not resume:
            self.save_checkpoint(stage=len((self.plan_data or {}).get("stages") or []), rounds=0, n=0, feedback="", step="land")
        checks = list(dict.fromkeys(c for s in (self.plan_data or {}).get("stages") or [] for c in s["checks"]))
        skip = None
        if kind == "conflict":  # tl-7y6.2.18: markers and build only; the plan's checks are skipped, the gate runs once on the result
            skip = list(dict.fromkeys(checks + self.case_checks()))
            checks = [self.MARKERS]
        goal, text = self.FIX[kind]
        st = {"goal": "Fix: " + goal, "files": [], "checks": checks, "hard": False}
        d = self.stage({"stages": [st]}, 0, {
            "fix": True, "conflict_fix": skip, "name": "fix %d/%d" % (self.fixes, limit), "fix_n": self.fixes, "fix_of": limit,
            "failed": [self.cfg.gate or "rebase"] if kind == "gate" else None,
            "feedback": text % tail if kind == "verify" else text % (
                (" (`%s`)" % self.cfg.gate) if kind == "gate" and self.cfg.gate else "",
                failure_brief([{"cmd": self.cfg.gate or "rebase", "exit": 1, "status": "failed", "group": "gate",
                                "tail": tail, "log": str(getattr(self, "gate_log", "") or "")}], self.run_dir)
                if kind == "gate" else compact([{"cmd": "rebase", "exit": 1, "status": "failed", "group": "gate",
                                                 "tail": tail}])),
            "scope": "the fix only: it must %s without breaking what the accepted stages built" % goal})
        if kind == "conflict":
            if self.sh(self.MARKERS, pin=True)[0]:
                return self.fix("conflict", "conflict markers are still in the tree after the fix", resume=resume)
            self.stage_all(check=True)
            rc, out = self.sh(["git", "-c", "core.editor=true", "rebase", "--continue"], pin=True)
            if rc:
                self.sh(["git", "rebase", "--abort"], pin=True)
                raise FixFailed("failed: the rebase did not continue after the conflict fix\n" + out, kind=oc.Kind.FAULT_LAND)
        elif kind == "gate" and self.git("status", "--porcelain"):
            self.stage_all(check=True)
            self.sh(["git", "commit", "-q", "--no-verify", "--amend", "--no-edit"], check=True, pin=True)
        if d != "accept" and kind != "verify":
            self.warn("land: the fix round did not pass its checks and review; landing tries the gate again")
        return d

    @contextlib.contextmanager
    def land_lock(self):
        """One land at a time per repo, across slots and sessions: an flock the OS drops when the process dies."""
        path = tl.land_lock_path(self.git("remote", "get-url", "origin") or str(self.wt))
        with self.locked("land_lock", path):
            yield path

    # -- look and feel (tl-bxk.10.23): screenshots for a visual change, judged by the agent, held for the owner's batch
    def visual_cfg(self):
        vp = self.cfg.visual_paths
        return vp if vp and vp.include else None

    def is_look(self, u):
        return bool(self.visual_cfg()) and bool(LOOK_ITEM.search(u["what"]))

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
        if getattr(self, "_shot_methods", None) is None:
            self._shot_methods = {}
            rel = (self.cfg.shot_table or "").strip()
            if rel:
                text = self.git("show", "%s:%s" % (self.cfg.base, rel))
                methods, err = looks.parse_table(text) if text else ({}, "%s is not on %s" % (rel, self.cfg.base))
                if err:
                    self.warn("engine.shot_table: %s; visual stages work the old way" % err)
                self._shot_methods = methods
        return self._shot_methods

    def look_ready(self, st):
        return bool(self.shot_methods()) and self.stage_visual(st)

    def planner_notes(self):
        """engine.planner_notes: text, or "@path" of a repo file (read from the worktree), at most 2000 characters."""
        v = (self.cfg.planner_notes or "").strip()
        if v.startswith("@"):
            try:
                v = (Path(self.wt) / v[1:]).read_text(encoding="utf-8").strip()
            except OSError:
                self.warn("engine.planner_notes: %s cannot be read" % v)
                return ""
        return v[:2000]

    def assume(self, data, text):
        """tl-ntp: record an Assumption on the plan (typed: step, text, reversible) and keep going."""
        data.setdefault("assumptions", []).append({"step": "plan", "text": " ".join(text.split())[:600], "reversible": True})

    def assume_question(self, data):
        """A plan question about a step that can be undone becomes an Assumption; the plan goes on without the ask."""
        q = " ".join(data["question"].split())
        self.assume(data, "no owner answer; planned on the bead text and the repo. Open question: " + q)
        data["question"], data["options"], data["irreversible"] = "", [], ""
        self.log.note(ASSUMPTION + q[:300])
        return data

    def check_unresolved(self, data):
        """tl-bxk.13.16.3, tl-ntp: inputs the planner could not find. A file that is there after all drops out; one a case defers
        (proved_by leftover) is a follow-up; the rest is an Assumption in the plan: missing reference material is not a reason to
        ask the owner (tl-7y6.6.15 stopped on study files no worktree can read)."""
        gone, open_ = [], []
        deferred = [word_set("%s %s" % (c["criterion"], c.get("via") or "")) for c in data.get("cases") or [] if c.get("proved_by") == "leftover"]
        deferred += [word_set(lo["title"] + " " + lo["why"]) for lo in data.get("leftovers") or []]
        for u in data.get("unresolved") or []:
            path = (u.get("path") or "").strip()
            if path and ".." not in path and (Path(path) if path.startswith("/") else Path(self.wt) / path).exists():
                continue  # it is there
            if any(len(word_set(u["what"]) & d) >= 2 for d in deferred):
                gone.append(u)
                continue
            open_.append(u)
        if gone:
            self.log.note("inputs not found, their criteria deferred: %s" % "; ".join(u["what"][:100] for u in gone))
        for u in open_:
            self.assume(data, "%s (%s%s) is not available; planned from the bead text and the repo" % (
                u["what"], u["kind"], ", expected at " + u["path"] if u.get("path") else ""))
            self.log.note(ASSUMPTION + u["what"][:300])

    def references_text(self):
        """What the planner is told the task already has to look at: image files its text names, and the last landed shots."""
        found = []
        for rel in dict.fromkeys(re.findall(r"[\w./-]+\.(?:png|jpe?g)\b", self.brief_text(), re.I)):
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
            if err:
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
        refs = [r for r in re.findall(r"[\w./-]+\.(?:png|jpe?g)\b", self.brief_text(), re.I) if (Path(self.wt) / r).is_file()]
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
        if any(c["exit"] not in (0, None) for c in cheap):
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
            if re.search(r"\bunverified\b", line, re.I):
                self.add_unverified({"what": "%s (link: %s)" % (fmt.clip(line, 200), url), "kind": "external_fact", "source": url},
                                    "the engine could not open %s (%s); the owner checks it" % (url, why))
                continue
            review["findings"].append({"file": path, "line": 0, "severity": "medium", "fix":
                "the link %s did not open from the engine's host (%s). Replace it with a source that opens. If the site only blocks "
                "bots, keep it and write `unverified` on the same line, so the owner is asked about the claim it carries. Never "
                "call a link verified that you could not open." % (url, why)})

    def look_judged(self, review, st, w, fix):
        """No screenshot and no logic-only reason on a visual stage is a medium finding; the reviewer's look is kept."""
        if fix or not self.stage_visual(st):
            return
        if (review.get("look") or "").strip() and self.shots():
            self.look_notes = [review["look"].strip()]  # the last round's judgement only
        if not self.shots() and not (w.get("logic_only") or "").strip():
            review["findings"] = review["findings"] + [{
                "file": str(self.evidence_dir), "line": 0, "severity": "medium",
                "fix": ("this stage changes visual paths but asked for no shots: name the shot methods to render in `shots`, "
                        "or say in logic_only why nothing on screen differs" if self.shot_methods() else
                        "this stage changes visual paths but saved no screenshot of any changed screen or state: save them "
                        "in %s/ (descriptive names), or say in logic_only why nothing on screen differs" % self.evidence_dir)}]

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
        try:
            ck = json.loads(self.checkpoint_path().read_text())
            ck.update(look_paths=self.look_paths, look_notes=self.look_notes, look_unjudged=self.look_unjudged,
                      unverified=self.unverified)
            self.checkpoint_path().write_text(json.dumps(ck, indent=1))
        except (OSError, ValueError):
            pass

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

    def wip(self, why):
        self.stage_all(everything=True)  # tl-g6a: nothing the bead made is left behind in a slot that is reset to the base
        # --no-verify: a wip commit saves work, it does not judge it; formatting is the checks' and the gate's job. A pre-commit
        # hook that refused it left staged files in the slot and failed the next bead there (lifesim-6pld, then rl4s)
        rc, tail = self.sh(["git", "commit", "-q", "--no-verify", "-m", "wip (%s): %s" % (self.bead, why)], pin=True)
        if rc:
            self.warn("the wip commit (%s) failed, the work stays uncommitted in %s: %s" % (why, self.wt, (tail or "").strip()[-300:]))
            self.log.note("wip commit failed: %s" % (tail or "").strip()[-300:])
        return rc == 0

    def close(self, outcome, why, sha, spec, kind=None):
        old = None
        if hasattr(signal, "SIGTERM") and threading.current_thread() is threading.main_thread():
            old = signal.signal(signal.SIGTERM, signal.SIG_IGN)  # a second stop must not break the close-out
        branch = self.git("symbolic-ref", "--short", "-q", "HEAD")
        try:
            self._close(outcome, why, sha, spec, kind)
            if not self.dry:
                with contextlib.suppress(Exception):  # last: the trace and the comments above read the branch
                    self.leave_slot(outcome, branch)
        finally:  # what the process starts after this (a notify command, the next test) must stay stoppable
            if old is not None:
                signal.signal(signal.SIGTERM, old)

    def repo_id(self):
        return self.git("remote", "get-url", "origin") or str(self.wt)

    def decide_close(self, outcome, why, kind):
        """The close's Kind after POLICY: a fault seen too often on one bead becomes one ask; the trace fields, the
        fingerprint and the storm check (never for a pause or an ask) are set here. kind None: the verify-gaps ask."""
        self.disp = None
        if kind is None:
            return None
        now = self.clock.now()
        o = oc.make(kind, why)
        self.fp = o.fingerprint
        try:
            history = loop_health.recent_closes(tl.config_dir() / "traces.jsonl", self.repo_id(), now)
        except OSError:
            history = []
        self.disp = oc.apply(o, self.bead, history, now)
        self.kind = self.disp.kind
        if self.disp.escalated:
            self.warn("the same fault %d times on this bead: asking the owner once" % oc.KNOBS["fault_retries"])
        trip = loop_health.storm_trip(history, self.bead, kind, o.fingerprint, now)
        if trip and not self.dry:
            path = loop_health.storm_path(tl.config_dir(), self.repo_id())
            if loop_health.write_storm(path, trip, now, why):
                self.storm = loop_health.banner(trip)
                self.warn(self.storm)
                say(self.storm)
        return self.kind

    def leave_slot(self, outcome, branch):
        """tl-g6a: a bead that parked leaves its work on its own branch (wip committed above) and the slot at the detached base,
        not on an old branch whose untracked files made the next runs fail as 'uncommitted work of another branch'."""
        if outcome in ("landed", "done") or not branch or branch != getattr(self, "branch", None):
            return
        if self.dirty_status() or self.git("symbolic-ref", "--short", "-q", "HEAD") != branch:
            return  # work that could not be committed, or files stage_all left out, stay where they are for the next run
        rc, tail = self.sh(["git", "checkout", "-q", "--detach", self.cfg.base], pin=True)
        if rc:
            self.warn("the slot could not be left at the base: %s" % tail.strip()[-160:])

    def _close(self, outcome, why, sha, spec, kind=None):
        why = why or ("stopped before a reason was recorded" if outcome == "failed" else "")
        bad = (raiser.problems(spec) if spec else ["the stop carries no ask"]) if kind in oc.ASKS else []
        if bad:  # an ask that is no ask an owner can answer is the engine's own fault; no prose question takes its place
            why, kind, spec = "failed: ask_lint: %s (%s)" % ("; ".join(bad)[:300], why.splitlines()[0][:200] if why else ""), oc.Kind.FAULT_ENGINE, None
        kind = self.decide_close(outcome, why, kind)
        outcome = outcome_for(kind, why) if kind and kind not in oc.FINISH else outcome
        if self.disp and self.disp.escalated and spec is None:
            spec = askspecs.repeated_fault(oc.KNOBS["fault_retries"], why.splitlines()[0][:200])
        mins = (time.time() - self.t0) / 60
        gd = Path(self.git("rev-parse", "--absolute-git-dir") or ".")
        if (gd / "rebase-merge").exists() or (gd / "rebase-apply").exists():  # stopped mid-conflict-fix: back to the branch
            self.sh(["git", "rebase", "--abort"], pin=True)
        branch = self.git("symbolic-ref", "--short", "-q", "HEAD")
        new = list({lo["title"]: lo for lo in self.leftovers if lo["title"] not in self.filed}.values())  # a title once
        if outcome not in ("landed", "done") and branch and branch == getattr(self, "branch", None):
            if self.git("status", "--porcelain"):
                self.wip(outcome)  # the next run continues this branch
            self.mark_checkpoint_closed(why)
        stats = "cost=$%.2f; minutes=%d; %s" % (self.cost, mins, "; ".join("%s=%s" % kv for kv in self.stats.items()))
        self.log_run()
        last = self.steps.cur or self.steps.last
        if last and (self.steps.moved_from != last.n or self.steps.moved_to not in ("ask", "pause", "close")):
            # no move out of the run was logged from the last node: the close is it
            to, cause = close_move(outcome, why, kind)
            self.steps.move(to, cause, why.splitlines()[0][:200] if why else outcome)
        self.steps.end(node_outcome(outcome, why, kind))
        self.steps.begin("close", "close: %s" % outcome)
        self.log.emit(rec.Close(outcome=Outcome(outcome), why_code=runtrace.why_code(kind.value if kind else "", outcome), sha=sha or "", why=why[:500]))
        self.steps.outcome(outcome, why.splitlines()[0][:200] if why else "")
        self.steps.end()
        self.reflection = self.reflect_run(outcome, why)  # after the close node: the outcome is decided and nothing here changes it
        self.file_trace(outcome, why, sha)
        self.detail([stats] + ([why[:400]] if why else []) + (["question: " + spec.decision[:400]] if spec else []))
        if outcome == "failed":
            self.warn("task failed: %s" % why.splitlines()[0][:200])
        if self.dry:
            self.log.note("dry run: bead left as it was. %s" % stats)
            return
        if kind == oc.Kind.WAIT_ASK or (kind is None and why.startswith("waiting:")):  # asked already: the bead stays as the ask left it, nothing is said twice
            self.log.note(why)
            return
        self.asked = bool(kind in oc.ASKS and spec and outcome not in ("landed", "done") and self.raise_ask(spec, why, kind))
        if outcome in ("landed", "done"):
            old = self.stores.asks.get(self.bead)
            if old:
                self.stores.asks.close(self.bead, old.id, "the run landed")
        if self.unverified and outcome in ("landed", "done"):
            self.comment("Land (engine): " + self.unverified_text())
        look = [u for u in self.unchecked if u["kind"] == "other" and not self.is_look(u)]
        if look and outcome in ("landed", "done"):
            tl.attempt(self.store.add_label, self.bead, "needs-owner-check")
            self.comment("Look (engine): landed, but nobody checked: " + "; ".join(u["what"] for u in look))
        shots = self.keep_evidence()
        if shots:
            self.comment("Evidence (engine): %s" % ", ".join(str(p) for p in shots))
        unfiled = []
        for lo in new:
            made, err = self.create_checked(NewBead(title=lo["title"], description=lo["why"], deps=["discovered-from:" + self.bead]))
            if made:
                self.filed.append(lo["title"])  # only a create that worked; the checkpoint follows at once (a kill loses no title)
                self.save_unfiled([])
            else:
                unfiled.append(lo)
                self.warn("follow-up not filed: %s: %s" % (lo["title"][:80], err[:200]))
        if unfiled:
            self.comment("Follow-up (engine): bd refused %d follow-up(s), none was filed: %s" % (
                len(unfiled), "; ".join("%s (%s)" % (lo["title"], lo["why"][:120]) for lo in unfiled)))
            self.save_unfiled(unfiled)
        if outcome == "landed":
            self.file_owner_look()
        verified = ("; self-verified=" + ", ".join("%d %s" % (sum(x["verdict"] == k for x in self.verified), k)
                                                   for k in VERDICTS)) if self.verified else ""
        self.comment("Reflect (engine): outcome=%s;%s filed=%d;%s %s%s%s; trace=%s (tl trace %s)" % (
            outcome, reflection_text(getattr(self, "reflection", None)), len(new) - len(unfiled),
            (" unfiled=%d;" % len(unfiled)) if unfiled else "", stats, verified, ("; why=" + why) if why else "",
            self.log_path.stem, self.bead))
        summary = (getattr(self, "plan_summary", "") or "")[:300]
        if outcome == "landed":
            rc = tl.cmd_close(Args(id=self.bead, reason="merged %s to %s: %s; %s" % (
                sha[:12], self.cfg.base.split("/")[-1], summary or "the task's stages passed", stats)))
        elif outcome == "done":
            rc = tl.cmd_close(Args(id=self.bead, reason="done with nothing to land: " + (summary or stats)))
        elif kind and oc.POLICY[kind].bd == "open":  # a machine fault or pause (login, network, lanes, kill): the bead stays open and unassigned
            fault = kind.name.startswith("FAULT_")
            if not fault:
                self.warn(why)
            rc = 0 if tl.attempt(self.store.update, self.bead, BeadPatch(status="open", assignee="")) else 1  # (tl-kwo: it lets go)
            if oc.POLICY[kind].label:
                tl.attempt(self.store.add_label, self.bead, oc.POLICY[kind].label)
            if self.disp.comment:  # a comment, never Notes (tl-7y6.6.2); one per (bead, kind, fingerprint) per hour
                self.comment("Engine %s: %s" % ("failed" if fault else "paused", re.sub(r"^(failed|paused): ", "", why)[:400]))
        else:
            text = why + (("\n\nQuestion: " + spec.decision) if spec else "")
            rc = tl.cmd_block(Args(id=self.bead, why=text))
        if rc:  # a repo's bd rules can refuse (e.g. a minimum reason length): say so, never report a clean close
            self.warn("bd refused to %s %s (exit %s): close it by hand" % ("block" if outcome not in ("landed", "done")
                                                                          else "close", self.bead, rc))


GHERKIN_TEST = re.compile(r"^\s*Scenario( Outline)?:")  # a use-case scenario (Reqnroll, lifesim-fld.26.10)


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


REFLECT_PROMPT = """You write a short reflection on one run of an unattended task engine, for the engineer who maintains the engine. Do not
edit files; judge only from what is below.
Bead %s: %s
Outcome: %s. Why: %s
Counts: %s
The run's worker sessions (cite the session id):
%s
The run's decisions and warnings, oldest first:
%s

Answer:
- went_well: up to 4 lines, each one concrete thing that worked.
- went_badly: up to 4 items; each: what (one line), cause (one of engine, prompt, delegate, repo_profile, bead, sandbox, other), session
  (the session id above it comes from, or "run"), evidence (a number or a quote from above). Empty when nothing went badly.
- wasted: up to 3 lines, where tokens or minutes went for nothing, with the numbers.
- change: up to 3 lines, what to change, naming the cause class.
Cite only what the data above shows; do not guess a cause it does not support."""

engine_written = intake.engine_written  # what the engine (or a receipt of ours) wrote into a bead is never the owner's (tl-7y6.6.2)


def people_lines(text):
    """Notes without the lines the engine appended to it ('Engine paused: ...', 'Engine failed: ...'): the only fields it writes."""
    return "\n".join(l for l in (text or "").splitlines() if not l.lstrip().startswith(("Engine paused:", "Engine failed:"))).strip()


def has_criteria(bead):
    """Acceptance criteria in the bead's field, or in a ## Acceptance Criteria or ## Done when section (or a "Done when:" line) of its description."""
    if bead.acceptance_criteria.strip():
        return True
    m = re.search(r"^#{1,6}\s*(?:Acceptance Criteria|Done when)\s*:?\s*$(.*?)(?=^#{1,6}\s|\Z)", bead.description,
                  re.M | re.S | re.I)
    if m and m.group(1).strip():
        return True
    # tl-bxk.13.2: "Done when: ..." as a line, or "**Done when**" then its list (lifesim-r6z was blocked in 0 s for it)
    return bool(re.search(r"^[ \t>*_#-]*Done when[ \t]*[:*_]+[ \t]*(?:[^\s:*_]|\n\s*[-*\d])", bead.description, re.M | re.I))


def acceptance_text(bead):
    """The bead's acceptance text: its criteria field, and its description from an Acceptance Criteria or Done when heading
    (or line) on."""
    desc = bead.description
    m = re.search(r"^[ \t>*_#-]*(?:Acceptance Criteria|Done when)\b", desc, re.M | re.I)
    return "\n".join(x for x in (bead.acceptance_criteria.strip(), desc[m.start():] if m else "") if x)


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


CK_FIELDS = tuple(("v bead branch rebase_resets plan planner_ref planned extra plan_log snap done accepted replans fixes denials writer "
                   "writer_fallback fallback_lane writer_family writer_ctx writer_seen brief head unchecked filed look_paths look_notes "
                   "look_unjudged look_done look_prev rendered last_reqs render_stale unverified handoff stage_tree writer_said "
                   "accepted_new closed run t pending_land_validation stage rounds n feedback step").split())  # what save_checkpoint writes


ENGINE_LABELS = ("needs-owner-check",)


def question_spec(out):
    """The ask a worker's question makes: its text and the options it offered."""
    return askspecs.open_question(out["question"], out.get("options"))


def brief_digest(bead, comments, owner_only=False, ignore=()):
    """Markdown brief: title, the bead's text fields whole, related beads by title, people's comments whole, and the bead's
    labels. Nothing the engine wrote (comments, Notes lines) is in it (tl-7y6.6.2). owner_only also leaves out the engine's labels:
    the checkpoint compares that text, so an engine run never looks like the owner's edit."""
    out = ["# %s: %s" % (bead.id, bead.title)]
    labels = [x for x in bead.labels if not (owner_only and (x in ENGINE_LABELS or x in ignore))]
    meta = [bead.issue_type, "P%s" % bead.priority if bead.priority is not None else "", ", ".join(labels)]
    if any(meta):
        out.append(" · ".join(m for m in meta if m))
    for key, head in (("description", "Description"), ("acceptance_criteria", "Acceptance criteria"),
                      ("design", "Design"), ("notes", "Notes")):
        text = people_lines(bead.notes) if key == "notes" else getattr(bead, key).strip()
        if text:
            out += ["", "## " + head, text]
    if bead.dependencies:
        out += ["", "## Related beads (titles only)"] + ["- %s %s [%s]" % (d.id, d.title, d.status or "?") for d in bead.dependencies]
    hint = str(bead.metadata.get(intake.HINT) or "").strip()
    if hint:
        out += ["", "## Owner hint", hint]
    people = [c for c in comments if not engine_written(c.text)]
    if people:
        out += ["", "## Comments"] + ["- %s: %s" % (c.author or "?", c.text.strip()) for c in people]
    return "\n".join(out) + "\n"


LINK_CAP = 200  # links opened per review
# tl-bxk.10.17: what a red check's output says about whether running it again could change anything
COMPILE_FAIL = re.compile(r"error CS(?!0006\b|2001\b)\d+|SyntaxError")
IMPORT_RACE = re.compile(r"Library/|Temp/|asset import|importing asset|refresh", re.I)
LOCK_FAIL = re.compile(r"another Unity instance|Multiple Unity instances|It looks like another Unity instance is running", re.I)


LOCK_BACKOFF = (15, 30, 60)  # seconds; the last repeats until LOCK_WAIT_MAX
LOCK_WAIT_MAX = 300


def failure_kind(text):
    """'lock' (an editor or project lock: wait, then rerun), 'deterministic' (a CS compile error or SyntaxError: a rerun
    fails the same way), 'import' (the same, but the log mentions Library/, Temp/ or an asset import: retry once anyway),
    else 'flaky' (today's retry)."""
    if LOCK_FAIL.search(text):
        return "lock"
    if COMPILE_FAIL.search(text):
        return "import" if IMPORT_RACE.search(text) else "deterministic"
    return "flaky"


def lock_waits():
    """The sleeps before each rerun of a check held by a lock: 15, 30, 60, 60 ... s, 5 min in all."""
    out, total = [], 0
    while total < LOCK_WAIT_MAX:
        d = min(LOCK_BACKOFF[min(len(out), len(LOCK_BACKOFF) - 1)], LOCK_WAIT_MAX - total)
        out.append(d)
        total += d
    return out


def lock_holder(text, cwd):
    """Pids that have the project lockfile open (lsof), '' when none or lsof is missing. The path is the one the
    output names, else Temp/UnityLockfile under the tree."""
    names = re.findall(r"(\S*Temp/UnityLockfile)", text)
    cands = [Path(n) if os.path.isabs(n) else Path(cwd) / n for n in names] + sorted(Path(cwd).glob("*/Temp/UnityLockfile"))
    for f in cands:
        if not f.exists():
            continue
        try:
            r = subprocess.run(["lsof", "-t", str(f)], capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            return ""
        pids = [x for x in r.stdout.split() if x.isdigit()]
        if pids:
            return ",".join(pids)
    return ""


SLOT_WAIT = re.compile(r"\bgot slot \S+ after (\d+) ?s\b")
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
            body = " | ".join(x.strip() for x in trim.trim_log(c["tail"], cap=600, tail_lines=3).splitlines())
        else:
            body = " | ".join(([ln for ln in lines[:-1] if NOTABLE.search(ln)][-3:] + lines[-1:]))[-300:]
        out.append("- `%s` exit %d%s" % (c["cmd"], c["exit"], (": " + body) if body else ""))
    return "\n".join(out) or "- (no checks)"


CONFLICT_BUILD = re.compile(r"(?i)(?<![a-z])(build|compile)(?![a-z])")  # a repo check a conflict fix still runs (tl-7y6.2.18)
SLOW_CMD = re.compile(r"(?i)(?<![a-z])(unity|play|test[-_]all|check|build|dotnet)")


STOP_WORDS = {"that", "this", "with", "from", "into", "have", "been", "were", "which", "their", "there", "than", "then", "when",
              "what", "does", "should", "would", "could", "also", "only", "each", "every", "about", "after", "before", "bead",
              "beads", "task", "work", "tests", "test", "file", "files", "code", "check", "checks"}
FILING_WORDS = re.compile(r"\b(?:beads?|follow-?ups?|filed?|filing|issues?|tickets?|records?|recorded|leftovers?|deferred?)\b", re.I)
OWNERISH = re.compile(r"\b(?:owner|sign-?off|approv\w*|review|confirm\w*|decid\w*|decision)\b", re.I)


def word_set(text):
    """The words of `text` worth comparing: lower case, 3+ letters or digits (any script), no filler."""
    return {w for w in re.findall(r"[^\W_]{3,}", str(text).lower()) if w not in STOP_WORDS}


def reflection_text(r):
    """The reflection as one line for the bead's Reflect comment ('' when there is none)."""
    if not r:
        return ""
    bad = "; ".join("[%s] %s (session %s)" % (b["cause"], fmt.clip(b["what"], 160), b["session"]) for b in r.get("went_badly") or []) or "none"
    return " reflection: badly: %s%s%s;" % (fmt.clip(bad, 500), (" | wasted: " + fmt.clip("; ".join(r["wasted"]), 200)) if r.get("wasted") else "",
                                           (" | change: " + fmt.clip("; ".join(r["change"]), 200)) if r.get("change") else "")


GATE_ONLY_ACCEPTANCE = "plan-lint rule gate-only-acceptance"
GATE_ONLY_ACCEPTANCE_TEXT = ("\n\nYour plan was sent back (%s): these acceptance cases or Done-when items are only the "
                             "gate command, and the engine runs the gate (`%s`) once at land on its own:\n%s\nReplace each with what "
                             "the task asks for that the gate does not show (a behaviour, a number, a file), or drop it.")
GATE_FILLER = frozenset("the a an of and or is are be pass passes passed passing green succeed succeeds succeeded success clean ok okay "
                        "exit exits exited code zero 0 run runs running ran must should shall without no error errors fail fails "
                        "failure failures all full complete completes whole gate check checks done when it that on with".split())


def gate_only_criteria(plan, cfg):
    """[criterion]: the plan's cases (its acceptance) whose text is only a gate command, e.g. "`just check` passes" or "just check
    green". The engine runs the gate at land (tl-7y6.7.15); a case for it proves nothing the land does not."""
    clean = lambda t: " ".join(re.sub(r"[`'\"*_.,;:()\[\]]", " ", t).lower().split())  # noqa: E731
    cmds = [clean(c) for c, _ in lint.gate_only(cfg)]
    out = []
    for x in plan.get("cases") or []:
        text = clean(x.get("criterion") or "")
        rest = text
        for c in sorted(cmds, key=len, reverse=True):
            rest = rest.replace(c, " ")
        if rest != text and not [w for w in rest.split() if w not in GATE_FILLER]:
            out.append(x.get("criterion", "").strip())
    return out


def norm_cmd(cmd):
    return " ".join(str(cmd).split())


ELLIPSIS = re.compile(r"\.\.\.|\u2026")


def flagged_why(check, bad_checks):
    """tl-bxk.13.3: the writer's reason when one of its bad_checks names this failed check, else "". It names it by its
    command as listed, whitespace aside; by its id; or shortened (`...` for what it cut, or a stretch of 20+ characters of
    it): lifesim-d5f.40 flagged one broken check in 8 writes and none matched, 43 minutes until the round cap."""
    mine = norm_cmd(check["cmd"])
    for b in bad_checks:
        said = norm_cmd(b["cmd"]).strip("`")
        if not said:
            continue
        if said == mine or said == str(check.get("id") or ""):
            return b["why"]
        if ELLIPSIS.search(said):
            parts = [x.strip() for x in ELLIPSIS.split(said) if len(x.strip()) >= 6]
            at, ok = 0, bool(parts)
            for part in parts:
                at = mine.find(part, at)
                if at < 0:
                    ok = False
                    break
                at += len(part)
            if ok:
                return b["why"]
        elif len(said) >= 20 and (said in mine or mine in said) and min(len(said), len(mine)) >= 0.8 * max(len(said), len(mine)):
            return b["why"]
    return ""


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


def failure_brief(checks, run_dir, each=trim.CAP, total=3 * trim.CAP, lines=trim.TAIL):
    """The failing checks for a prompt: command (cut at 300 chars), log path ("none" when no log), then the saved log
    trimmed by trim.trim_log (failure lines with their context, plus its last `lines` lines), then a timeout note. Each
    check is at most `each` bytes in all, `total` for all checks; the full log stays on disk at the path given."""
    out, left = [], total
    for c in checks:
        log = Path(run_dir, c["log"]) if c.get("log") else None
        try:
            text = log.read_text(encoding="utf-8", errors="replace") if log else c.get("tail") or ""
        except OSError:
            text, log = c.get("tail") or "", None
        code = c.get("exit")
        end = ""
        if isinstance(code, int) and (code == 124 or code < 0):
            secs = c.get("secs")
            end = "timed out after %s s" % (int(secs) if isinstance(secs, (int, float)) else "?")
        cmd = c["cmd"] if len(c["cmd"]) <= 300 else c["cmd"][:300] + "..."
        head = "- `%s` exit %s\n  log: %s" % (cmd, code, log or "none")
        room = min(each, left)
        if room <= len(head) + 80:
            out.append(head + "\n  (output left out: see the log)")
            continue
        body = trim.trim_log(text, cap=room - len(head.encode("utf-8")) - len(end) - 2, tail_lines=lines)
        text = "\n".join(x for x in (body, end) if x)
        left -= len(head.encode("utf-8")) + len(text.encode("utf-8")) + 1
        out.append(head + ("\n" + text if text else ""))
    return "\n".join(out) or "- (no checks)"


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
REPEAT_RED = ("\nThese checks failed in the last round too:\n%s\nIf one measures a threshold the task does not ask for (the task "
              "says the owner judges it, or the number is the plan's own), do not keep tuning the work to it: list it in "
              "bad_checks, with why, and the plan is changed instead.\n")
VISUAL_STAGES = """A stage whose files match this repo's visual paths (%s) changes how something looks. Its writer cannot render: it names the
pictures to render in `shots` (a method from the table below, its args, names) or gives a `logic_only` reason; an answer with
neither is sent back. Plan such stages knowing that, and never plan a check that needs a picture the writer is to make.
Shot methods:
%s"""
SHOTS_FIX = ("\nYour answer named no shots and gave no logic_only reason, but this stage touches visual paths. You cannot render here: the "
             "engine does. Name the pictures to render in `shots` (a method from the table, its args, names), or say in logic_only why "
             "nothing on screen differs. Change nothing else; do not redo the work.\n%s\n")
VISUAL_PLAN = """This repo has visual work (screens). Give every case a class in `class`:
- test: a command proves it (the usual case with its check).
- look-objective: a picture can prove it: it shows, nothing is clipped or overlapped, no error text, magenta or missing
  texture, the state asked for is visible. Leave `check` empty: the engine renders the shots and a look judge reads them.
- taste: someone has to like it ("the owner approves", "reads well", "feels like ..."). Leave `check` empty: it goes to the
  owner after the land and never blocks it.
A number for a look item (a contrast ratio, a size) comes only from the task, the owner or a project standard file (design
tokens, a rule under config/). Never invent one as a check: if you think one is needed, ask it as your question (options with
your proposal first) and plan no check for it.
%s"""
MAX_REBASE_RESETS = 2   # per bead, across runs (tl-19i)
REPLAN_CAP = "stuck: the bead was re-planned "  # the cap's ask; an owner's answer to it allows one more
RULES_MAX = 3 * 1024          # a worker_rules file is inlined once, in the planner's and the writer's first prompts: this many bytes at most
PLAN_BRIEF_KB = 12            # the planner's whole brief should stay under this
DECIDED_TEXT = ("\nYou asked: %s\nAn accepted requirement already decides it: %s\nMeet that requirement: change the "
                "work, never the requirement.\n")
ASSUME_TEXT = ("\nYou asked: %s\nNothing in that question cannot be undone, so the engine does not ask the owner: it records it as an "
               "Assumption. Plan the work on your best assumption now, with at least one stage.\n")
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
- To assert on what a repo check printed, do not run its command again in a plan check: the engine exports the log of
  each repo check that ran before yours as `$TL_CHECK_LOG_<ID>` (its id upper-cased, other characters `_`; its exit code is
  `$TL_CHECK_RC_<ID>`). Example: `grep -q 'Passed: 12' "$TL_CHECK_LOG_UNITY_TESTS"`.
- The engine sets every time limit and runs checks one at a time; never write timeouts, "run alone" or similar notes
  into a check.
- cases: the acceptance cases. At least one per acceptance criterion of the task, each with the criterion it proves
  (quote it) and a check. They run on the last stage and again after any fix at land. A case about what users see uses
  the host's tools and a fact the tool reports (a scenario script, a screenshot saved under the evidence folder, a count
  the editor prints), never only "a screenshot exists".
- Before planning, check that every input the criteria need exists: a file or asset, an object in the content, a platform or
  machine the factory has, the engine or tool the project uses now, an input the task says someone provides. One you could not
  find is listed in unresolved (what, kind, path: the file it should be at, or empty). If the rest of the task can go on
  without it, defer the criteria that need it instead (a case with proved_by leftover, and a leftover) and do not list it.
  A listed input is never an ask: the engine records it as an Assumption and the plan goes on. Material outside the
  worktree (a study, a file under ~/ or Drop) is missing material: plan from the bead text and the repo.
- Each case says in proved_by how its criterion is proved, and via names what proves it: check (a command; the usual
  case), stage (its stage's own checks; via = the stage number), leftover (deferred to a follow-up bead the engine files:
  also list it in leftovers; via = that leftover's title; check empty) or engine_step (the engine does it itself: files the
  leftovers as beads, runs the gate, lands, closes the bead, copies screenshots; via = which; check empty). A criterion
  about filing beads, the gate, the land or closing is an engine_step; one the tracker holds is never a check. The review
  and the verifier are told this ledger and will not call a leftover or engine_step criterion unmet.
- A criterion only the owner can judge (it looks right, feels right, the owner approves) is never a pass/fail check on a
  number you chose: the check proves the evidence exists (the screenshot or sheet is saved, a count the tool reports), and
  the judgement goes in leftovers for the owner. A threshold you invent is a requirement nobody asked for, and the writer
  will tune the work to it.
- Name the risks ahead of time: what could break something users or other code rely on (a saved format, a public
  member, shared files), each with the check that proves it safe. None is fine.
- A check proves the code and the tree only: it never reads the tracker (no `bd`, nothing under `.beads/`) nor
  anything outside the worktree; the writers cannot run bd, so such a check fails whatever they do. Follow-up work the
  task wants filed (a new bead, a later task) goes in leftovers, each a title and why: the engine files them itself,
  and no check or case asks for them.
- question: empty. Assume instead of asking: decide what you can, plan on it, and say it in the summary. Only a step
  that cannot be undone may ask: set irreversible to push_shared (a push to a shared branch), delete_outside (a
  deletion outside the worktree), close_epic (closing an epic) or spend_money, and write the question so it can be
  answered from a phone: what you found, the decision, 2-3 options with costs, your recommendation. A question
  without irreversible is dropped by the engine and recorded as an Assumption. Missing reference material, a missing
  file, an unclear scope, a product or architecture choice are all reversible: assume.
""" + OPTIONS_RULE + "\n" + DECIDED_RULE

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
A check that mentions $TL_CHECK_LOG_<ID> or $TL_CHECK_RC_<ID> reads the log and the exit code of a configured check the engine ran just
before it. Those variables exist only while the engine runs the checks, never in your session: do not ask for them, do not export them,
and do not call it a blocker that they are unset. Make what the check asserts true and run the checks you may run.
Never run the gate{gate} or the issue tracker (bd): the engine runs the gate, and its run is the one that counts.
Repo instructions that say a change is done only when the full gate passes are for people working by hand; here the
engine does that part.
{feedback}
flakes: a test that failed for a reason outside your change (it passed or failed differently on a rerun, or fails on the
untouched base): its name and one line; else empty. The engine tells later tasks of this repo.
bad_checks: a stage check that fails for a reason no code change can fix (wrong arguments, a guard that rejects the
uncommitted work this stage must leave, a pattern that matches harmless text), each with why (cmd: the check's command exactly as listed, never shortened); else empty. The engine
then asks for a new plan instead of retrying.
A check that times out or fails only where you run it is not yours to retry; note it once and move on.
Proof the engine cannot rerun (a test seen failing after a planted fault, then passing once restored; a manual
measurement): save the exact commands and their output as files in {evidence}/ and name those files in the summary.
Only that proof goes there, never your own runs of the checks.
Rules: no suppressions; do not weaken, skip or delete tests; stay inside the
stage. question: empty unless only the owner can decide something about the task itself (then explain it for a
phone); never a question about tools or access.""" + "\n" + OPTIONS_RULE + "\n" + DECIDED_RULE

WRITE_RULES = """
This repo's rules for work in your sandbox (what runs there, what does not):
<worker_rules>
%s
</worker_rules>"""


def write_prompt(rules, **fields):
    """WRITE_PROMPT with the repo's worker rules inlined (a resumed writer's delta never repeats them)."""
    return WRITE_PROMPT.format(rules=WRITE_RULES % rules if rules else "", **fields)


WRITE_RESUME_PROMPT = """You are still the writer of this task, in an unattended engine. Nobody is watching. This session has the
task, the plan and your rules from before; only what changed is below.
The brief is unchanged; it is in {brief}; re-read it if unsure.
{plan}
Your stage: {n}: {goal}
Files: {files}
The stage's checks (the engine runs all of them after you; the split says which you may run):
{checks}
{where}
{feedback}"""

STAGES_DONE = """
Earlier stages of this task are accepted and their work is in this tree; you are a fresh session for the next one (the last
session had grown large). Do not redo them.
Accepted stages:
%sDone so far (git diff --stat from the task's base):
%s
The last rounds (the writer's summary, then what was sent back):
%s"""

DONE_SO_FAR = """
You take over from an earlier writer of this task, whose session grew too large to go on. Its work is in this tree, committed
on this branch or not: do not start over.
Done so far (git diff --stat from where this stage started):
%s
Its last summary: %s
The last rounds (the writer's summary, then what was sent back):
%s"""

REVIEW_PROMPT = """You review one stage of a task, from another model family than the writer. Do not edit files.
<task>
{brief}
</task>
<plan>
{plan}
</plan>
Stage {n}: {goal}
{fix_line}{work}
The engine ran the checks outside any sandbox, one at a time, and they all pass; these results are facts:
{checks}
The engine runs the gate{gate} once, at land, on the tree rebased onto the latest base, before anything merges; a red
gate (coverage included) goes to a fix round. The gate, the checks above and what they prove are never an unchecked item.
The writer says: {summary}
Proof the engine cannot rerun (a test seen failing after a planted fault) is in {evidence}/: a requirement shown
there is met. The engine counted tests in the task's diff: {added} added, {removed} removed.
Return:
- findings: bugs, broken contracts, risky changes (a public member, a test weakened or removed, a suppression, a file
  outside what the stage names, a break of this repo's own conventions: the rules in its AGENTS.md or CLAUDE.md, checked
  on the changed lines), each with file, line, severity and the fix. high and medium send the stage back; low
  is noted only. No style nits.
- unmet: what in {scope} the work does not do yet, each saying what is missing. A requirement shown met by a check or
  by the evidence is met; never list a remark that something is fine.
- question: empty, unless only the owner can decide something about the task itself (then explain it for a phone:
  what you found, the options, your recommendation).
- leftovers: real follow-up work you noticed outside this task, else empty.""" + "\n" + OPTIONS_RULE + "\n" + DECIDED_RULE

def review_prompt(fix, last, fix_scope, **fields):
    """REVIEW_PROMPT for one stage. The scope of the `unmet:` line is a fixed phrase (the template's line never takes text from
    the stage); in a fix round the fix's own scope is a line of its own (tl-7y6.6.11: it was spliced into the sentence)."""
    scope = ("the stage goal" if fix else
             "the stage goal and every requirement and acceptance criterion of the task" if last else
             "the stage goal (later stages cover the rest of the task)")
    return REVIEW_PROMPT.format(scope=scope, fix_line=("Scope of this fix round: %s\n" % fix_scope) if fix else "", **fields)


NEW_FILES_TEXT = ("\nUnexplained new files: untracked, and no stage lists them nor the writer names them. They are NOT in the "
                  "commit unless you accept them, and they are moved out of the tree before the land gate. Decide EVERY one: "
                  "put its path in accept_files if the task needs it (it is staged), or in reject_files if it is a stray (a "
                  "test run's leftover). One you do not decide becomes a medium finding that sends the stage back. Each file "
                  "with its first 80 lines (or its size, if binary):\n")

VERIFY_PROMPT = """Before a task lands, you check what its workers could not check themselves. Do not edit files.
<task>
{brief}
</task>
The work (files the task changed, with line counts):
{work}
Proof the workers saved (command output, logs, pictures) is in {evidence}/.
{checks}{where}
Nobody has checked these items yet:
{items}
Settle each one yourself where you can: read the code, its call sites, sibling files, the saved proof and the engine's check
results above, and run
read-only commands (search, list, compare, count). Answer one entry per item, n its number:
- settled: you proved it right; evidence quotes exactly what proves it (the file and lines, or the command and its
  output).
- wrong: you found a real defect; why says what is wrong and where, so a writer can fix it.
- open: only a person can judge it (taste, a device or a screen you cannot reach, the owner's call); why says what they
  must look at.
When in doubt, it is open: never settle an item you did not prove.
Also give each item its kind (the engine routes by it; an open item of the wrong kind is asked or lands unseen):
- """ + "\n- ".join(KIND_LINES) + """
- other: none of these."""


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
    if b.metadata.get(intake.HOLD):
        return False, "held by the owner (%s): `tl hold %s --release` lets it go" % (b.metadata[intake.HOLD], bead_id)
    release = False
    if who and who != me:
        if not who.startswith("tl-"):
            return False, "claimed by %s" % who
        import loop  # the queue rule; imports engine itself
        if b.status == "blocked" or busy_elsewhere(repo, who, bead_id, store):
            # tl-159, tl-kwo: the claim is the actor's, and a loop's actor is live while the loop runs, whatever bead it is on:
            # lifesim-o67g was 'a live claim' of the loop that was running fld.27.12, and its answered ask waited an hour. A bead
            # a loop has left (parked, or the loop went on to another) is live only if an engine is running it now.
            live = bead_id in loop.running(repo, store)
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
    """The engine lock, with the area check before it under the area lock (loop.area_lock): "" when this run holds the
    worktree, else why not. A bead whose area runs elsewhere: a warning, or refused with --exclusive-area."""
    import loop  # the queue rule; imports engine itself

    def mark():  # the slot says which bead runs in it (held_bead makes its area busy): only once the area is decided
        if sb:
            tl.attempt(tl.bd_store(repo).update, sb, BeadPatch(set_metadata={"held_bead": a.id}))
    if not loop.has_areas(cfg):
        why = lock.take()
        if not why:
            mark()
        return why
    with loop.area_lock(repo, cfg):
        area, busy = loop.area_busy(repo, cfg, tl.peek(tl.bd_store(repo), a.id) or Bead(id=a.id, title="", status=""), {})
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
