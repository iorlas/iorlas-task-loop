"""Declared capabilities, ratchet mode (CLAUDE.md, Build & Test): a test that needs a process, git, a real clock, a long run, the network
or a thread race says so with `@needs(capability, reason)`. Today's declarations are the baseline (needs_baseline.json); only an increase
fails, and a new reason is said once and in words."""
import ast
import json

from support.procsim import CAPABILITIES

from rules import needs_ratchet as nr


def load():
    return json.loads(nr.BASELINE.read_text(encoding="utf-8"))


def test_no_new_undeclared_need():
    bad = nr.grown(nr.count_tree(), load())
    assert bad == [], "a test gained a capability declaration beyond the baseline: fake it, or move it to real/: " + "; ".join(bad)


def test_a_new_reason_is_said_once_and_in_words():
    bad = nr.weak_new(nr.count_tree(), load())
    assert bad == [], "a new @needs reason must say what only that capability shows for that test: " + "; ".join(bad)


def test_every_declared_capability_is_known():
    assert set(nr.count_tree()) <= CAPABILITIES


def test_declared_reads_the_three_spellings():
    tree = ast.parse(
        "@needs('long_run', 'a worker waits out its grace')\n"
        "@real_proc('r1')\n"
        "@te.real_git(why)\n"
        "def test_x(): pass\n"
    )
    assert nr.declared(tree) == [("long_run", "a worker waits out its grace"), ("process", "r1"), ("git", nr.DYNAMIC)]


def test_grown_and_weak_new_name_only_increases_and_boilerplate():
    base = {"process": {"old reason": 3}}
    now = {"process": {"old reason": 3, "x": 1}, "git": {"y": 2}}
    assert nr.grown(now, base) == ["git: 'y' 2 (baseline 0)", "process: 'x' 1 (baseline 0)"]
    assert nr.grown({"process": {"old reason": 2}}, base) == []
    assert nr.weak_new({"process": {"old reason": 9, "short": 1, "a long enough line of words": 2}}, base) == [
        "process: 'a long enough line of words' is on 2 tests",
        "process: 'short' is under 5 words",
    ]
