"""Deterministic tests for the delegate router"""

import argparse
import copy
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import hermetic  # noqa: F401  (a home of its own for every test)
import routing_support as support

from delegate.app import decide as dec
from delegate.app import env, net, usage
from delegate.contracts.routing import Settings
from delegate.contracts.state import StateDoc
from delegate.domain.health import ledger as health_ledger
from delegate.domain.lanes.lane import Lane
from tltestkit.procsim import real_proc
from tltestkit.tmpdir import TemporaryDirectory, mkdtemp

ROOT = Path(__file__).resolve().parents[3]
_entry = importlib.util.spec_from_file_location("route", ROOT / "packages" / "delegate" / "src" / "delegate" / "entry.py")
assert _entry is not None
assert _entry.loader is not None
route = importlib.util.module_from_spec(_entry)
sys.modules["route"] = route
_entry.loader.exec_module(route)

net.__dict__.setdefault("REAL_NET_PROBE", net.net_probe)  # a second module that stubs it must not save the stub as the real one
net.net_probe = lambda hosts=None: {
    "up": True,
    "ip_up": True,
    "why": "ok",
    "ms": 1,
    "hosts": {},
    "at": time.time(),
}  # tests open no socket; tests/test_net.py swaps it per case
os.environ["DELEGATE_CONFIG_DIR"] = mkdtemp()  # tests never touch a real config; classes that need their own set one
T = 1_000_000_000.0  # a fixed "now"
LIMIT_S = 30  # StateLock starts 8 interpreters that each import delegate
CFG = json.loads((ROOT / "packages" / "delegate" / "src" / "delegate" / "data" / "routing.json").read_text(encoding="utf-8"))


def obj(x: object) -> Any:
    """A JSON value the test knows is a dict or list: lets it index without narrowing at every step."""
    return x


def need[T](x: T | None) -> T:
    assert x is not None
    return x


def no_reader(lane: Lane, S: Settings, st: StateDoc, t: float, ai_usage: object = None) -> None:
    """A usage reader that reads nothing: the lane keeps the numbers it has."""


def why(r):
    """The reason of a non-done answer; None for a done one."""
    return (r["stop"] or {}).get("reason")


def at(r):
    """The time a stop says it ends or can be tried again; None when it names none."""
    return r["stop"]["retry"]["at"]


def lanes(openai=None, sub=None):
    """Build lane states. Each arg is a dict of Lane attributes; None = healthy default."""

    def mk(name, fam, kind, shared=False):
        return Lane(name, fam, kind, shared)

    o, s = mk("OPENAI_SUBSCRIPTION", "openai", "subscription"), mk("CLAUDE_SUBSCRIPTION", "claude", "subscription", True)
    o.five, o.week, o.pace = 10, 5, 0
    s.five, s.week, s.pace = 30, 40, 0
    for lane, over in ((o, openai), (s, sub)):
        for k, v in (over or {}).items():
            setattr(lane, k, v)
    return {x.name: x for x in (o, s)}


def decide(role, ls, st=None, **args):
    a = {"authored_by": None, "failed": [], "premium": None, "allow_degraded": False}
    a.update(args)
    return support.decide(role, copy.deepcopy(CFG), ls, st or {}, T, a)


def health_mod():
    return health_ledger


def argparse_ns(role, **kw):
    base = {
        "role": role,
        "authored_by": None,
        "premium": None,
        "allow_degraded": False,
        "claude_usage": None,
        "cwd": None,
        "resume": None,
        "cap": None,
    }
    base.update(kw)
    return argparse.Namespace(**base)


def _call(x):
    return x["tool_name"], x["tool_input"]


class Pick:
    @real_proc("delegate: a worker, git or CLI process")
    def test_worker_prefers_codex(self):
        d = decide("worker", lanes())
        assert (d["lane"], d["model"], d["pass"]) == ("OPENAI_SUBSCRIPTION", "gpt-6.1-sol", "strict")

    @real_proc("delegate: a worker, git or CLI process")
    def test_codex_command_handles_non_git_dirs(self):
        with TemporaryDirectory() as d_:
            d = decide("worker", lanes(), cwd=d_)
        assert "--skip-git-repo-check" in d["how"]["cli"]  # not a git work tree
        d2 = decide("worker", lanes(), cwd=str(Path(__file__).resolve().parents[3]))
        assert "--skip-git-repo-check" not in d2["how"]["cli"]  # this repo is one






class Roles:


    @real_proc("delegate: a worker, git or CLI process")
    def test_reviewer_prefers_the_other_family_and_authored_by_is_optional(self):
        assert (
            decide("reviewer", lanes())["model"] == "gpt-6.1-sol"
        )  # no author given: Codex first (the most room), no claim of independence
        d = decide("reviewer", lanes(), authored_by="openai")  # Claude is the last lane tried (delegate-m86): Codex reviews Codex, flagged
        assert (d["lane"], d["flag"]) == ("OPENAI_SUBSCRIPTION", "same_family")
        assert "claude is kept as the last resort" in d["warning"]
        out = {"out": True, "out_until": T + 3600}
        assert decide("reviewer", lanes(openai=out), authored_by="openai")["lane"] == "CLAUDE_SUBSCRIPTION"
        assert decide("reviewer", lanes(), authored_by="claude")["lane"] == "OPENAI_SUBSCRIPTION"
        assert decide("reviewer", lanes(), authored_by="gemini")["action"] == "error"

    @real_proc("delegate: a worker, git or CLI process")
    def test_same_family_review_is_the_last_resort_and_flagged(self):
        out = {"out": True, "out_until": T + 3600}
        d = decide("reviewer", lanes(sub=out), authored_by="openai")  # Claude is out: Codex reviews Codex
        assert (d["action"], d["lane"], d["flag"]) == ("run", "OPENAI_SUBSCRIPTION", "same_family")
        d = decide("reviewer", lanes(openai=out), authored_by="claude")  # Codex is out: Claude reviews Claude
        assert (d["action"], d["lane"], d["flag"]) == ("run", "CLAUDE_SUBSCRIPTION", "same_family")
        d = decide("reviewer", lanes(openai=out, sub=out), authored_by="claude")
        assert d["action"] == "stop"  # nobody left: stop, not an exception


    @real_proc("delegate: a worker, git or CLI process")
    def test_only_one_family_up_never_stops_and_warns(self):
        out = {"out": True, "out_until": T + 3600}
        grok = Lane("GROK_SUBSCRIPTION", "xai", "subscription")
        cases = {
            "openai": lambda: lanes(sub=out),
            "claude": lambda: lanes(openai=out),
        }
        for who, mk in cases.items():
            ls = mk()
            if who != "xai":
                grok.out, grok.out_until, grok.out_reason = True, T + 7200, "limit"
            ls["GROK_SUBSCRIPTION"] = grok if who != "xai" else Lane("GROK_SUBSCRIPTION", "xai", "subscription")
            if who != "xai":
                ls["GROK_SUBSCRIPTION"] = grok
            d = decide("reviewer", ls, authored_by=who)
            assert (d["action"], d["flag"]) == ("run", "same_family"), who
            assert d["lane"].split("_")[0] == {"openai": "OPENAI", "claude": "CLAUDE"}[who], who
            assert f"reviewing {who}'s work with {who}: no other family is up" in d["warning"], who
            ud = decide("reviewer", ls, authored_by=who, unattended=True, allow_degraded=True)  # no consent step exists for review
            assert (ud["action"], ud["flag"]) == ("run", "same_family"), who

    @real_proc("delegate: a worker, git or CLI process")
    def test_warning_names_why_other_families_are_down(self):
        out = {"out": True, "out_until": T + 3600, "out_reason": "logged_out"}
        ls = lanes(sub=out)
        g = Lane("GROK_SUBSCRIPTION", "xai", "subscription")
        g.out, g.out_until = True, T + 7200
        ls["GROK_SUBSCRIPTION"] = g
        w = decide("reviewer", ls, authored_by="openai")["warning"]
        assert "xai out until" in w
        assert "claude logged out" in w
        assert "warning" not in decide("reviewer", lanes(), authored_by="claude")

    @real_proc("delegate: a worker, git or CLI process")
    def test_premium_only_when_requested(self):
        assert decide("planner", lanes())["model"] != "fable-5.1"
        d = decide("worker", lanes(), premium="claude")
        assert (d["model"], d["flag"]) == ("fable-5.1", "user_requested_premium")
        d = decide("worker", lanes(), premium="openai")
        assert d["action"] == "error"  # no premium model mapped for openai yet

    @real_proc("delegate: a worker, git or CLI process")
    def test_light_uses_luna_first(self):
        d = decide("light", lanes())
        assert (d["model"], d["mode"]) == ("gpt-6-luna", "read_only")




class Cli:
    @real_proc("delegate: a worker, git or CLI process")
    def test_report_and_next_roundtrip(self):
        with TemporaryDirectory() as d:
            os.environ["XDG_CONFIG_HOME"] = os.environ["DELEGATE_CONFIG_DIR"] = d
            os.environ["APPDATA"] = d
            os.environ["DELEGATE_NOW"] = str(T)
            try:
                route.main(["report", "--lane", "OPENAI_SUBSCRIPTION", "--event", "out", "--until", str(T + 3600)])
                st = env.load_state()
                assert "OPENAI_SUBSCRIPTION" in st.out
                cfg = env.load_routing()
                real = dict(usage.READERS)
                usage.READERS.update(dict.fromkeys(real, no_reader))
                try:
                    ls = dec.fleet_builder(cfg).build(st, T, check_config=False).lanes
                finally:
                    usage.READERS.update(real)
                assert ls["OPENAI_SUBSCRIPTION"].out
                route.main(["report", "--lane", "OPENAI_SUBSCRIPTION", "--event", "ok"])
                assert "OPENAI_SUBSCRIPTION" not in env.load_state().out
            finally:
                for k in ("XDG_CONFIG_HOME", "APPDATA", "DELEGATE_NOW", "DELEGATE_CONFIG_DIR"):
                    os.environ.pop(k, None)


class StateLock:

    @real_proc("delegate: a worker, git or CLI process")
    def test_parallel_processes_lose_no_update(self):
        code = (
            "import sys; sys.path.insert(0, {!r}); from delegate.app import env\n"
            "for _ in range(25): env.update_state(lambda s: s.warned_at.__setitem__('n', s.warned_at.get('n', 0) + 1))".format(
                str(ROOT / "packages" / "delegate" / "src")
            )
        )
        with TemporaryDirectory() as d:
            env = dict(os.environ, DELEGATE_CONFIG_DIR=d)
            ps = [subprocess.Popen([sys.executable, "-c", code], env=env, stderr=subprocess.PIPE) for _ in range(8)]
            self.maxDiff = None
            assert [p.communicate()[1].decode()[-1500:] for p in ps] == [""] * 8
            assert json.loads(Path(d, "state.json").read_text())["warned_at"]["n"] == 200
