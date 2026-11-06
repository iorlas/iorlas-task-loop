"""Deterministic tests for the delegate router"""

import argparse
import copy
import datetime as dt
import importlib.util
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest
from delegate.app import net, usage
from delegate.contracts.routing import Settings
from delegate.contracts.state import StateDoc
from delegate.contracts.stores import locked
from delegate.domain.health import ledger as health_ledger
from delegate.domain.lanes.lane import Lane
from delegate.domain.time import spec

import hermetic  # noqa: F401  (a home of its own for every test)
import routing_support as support

ROOT = Path(__file__).resolve().parents[2]
_entry = importlib.util.spec_from_file_location("route", ROOT / "src" / "delegate" / "entry.py")
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
os.environ["DELEGATE_CONFIG_DIR"] = tempfile.mkdtemp()  # tests never touch a real config; classes that need their own set one
T = 1_000_000_000.0  # a fixed "now"
LIMIT_S = 30  # StateLock starts 8 interpreters that each import delegate
CFG = json.loads((ROOT / "src" / "delegate" / "data" / "routing.json").read_text(encoding="utf-8"))


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


    def test_codex_out_falls_to_claude_subscription_when_healthy(self):
        d = decide("worker", lanes(openai={"out": True, "out_until": T + 3600}))
        assert (d["lane"], d["model"]) == ("CLAUDE_SUBSCRIPTION", "sonnet-5.5")

    def test_burn_prefers_subscription(self):
        d = decide("worker", lanes(openai={"out": True, "out_until": T + 1}, sub={"burn": True, "five": 30}))
        assert d["lane"] == "CLAUDE_SUBSCRIPTION"


class SecondPass:
    def test_relaxed_pass_uses_reserved_subscription_same_step(self):
        ls = lanes(openai={"out": True, "out_until": T + 1}, sub={"week": 92, "five": 40})
        d = decide("worker", ls)
        assert (d["lane"], d["model"], d["effort"], d["pass"]) == ("CLAUDE_SUBSCRIPTION", "sonnet-5.5", "medium", "relaxed")

    def test_relaxed_has_a_ceiling(self):
        ls = lanes(openai={"out": True, "out_until": T + 1}, sub={"week": 96})
        d = decide("worker", ls)
        assert d["action"] == "stop"

    def test_relaxed_never_changes_model_floor(self):
        ls = lanes(openai={"out": True, "out_until": T + 1}, sub={"week": 92})
        d = decide("planner", ls)
        assert (d["model"], d["effort"]) == (
            "sonnet-5.5",
            "high",
        )  # Opus never runs in the loop (delegate-pnz): Sonnet is the planner's Claude rung

    def test_normal_relaxed_beats_degraded_strict(self):
        ls = lanes(openai={"out": True, "out_until": T + 1}, sub={"week": 92})
        d = decide("reviewer", ls, authored_by="openai")
        assert (d["model"], d["effort"], d["pass"]) == ("sonnet-5.5", "medium", "relaxed")


class Roles:
    def test_planner_stop_asks_consent(self):
        ls = lanes(openai={"out": True, "out_until": T + 5000}, sub={"out": True, "out_until": T + 7000})
        d = decide("planner", ls)
        assert d["action"] == "stop"
        assert "ask_user" in d
        assert len(d["resets"]) == 2

    def test_planner_degraded_only_with_consent(self):
        ls = lanes(openai={"out": True, "out_until": T + 5000}, sub={"week": 96, "five": 10})
        assert decide("planner", ls)["action"] == "stop"
        ls2 = lanes(openai={"out": True, "out_until": T + 5000}, sub={"week": 96, "five": 10})
        assert decide("planner", ls2, allow_degraded=True)["action"] == "stop"  # ceiling still binds



    def test_every_reviewer_list_reaches_every_family(self):
        for who, steps in CFG["roles"]["reviewer"]["by_author"].items():
            assert {s["on"] for s in steps} == {"openai", "claude", "deepseek", "zai"}, who  # Grok never reviews (delegate-qjw)
            if who not in ("unknown", "xai"):
                fam = who
                assert steps[-1]["flag"] == "same_family", who
                assert steps[-1]["on"] == fam, who






class Helpers:
    def test_unknown_usage_shapes_are_rejected(self):
        assert usage.normalize_usage({"x": 1}) is None
        assert usage.normalize_usage({"five_hour": {"used": 37}}) is None  # only get_usage's real shape is understood

    def test_real_get_usage_result_is_understood(self):
        real = {
            "plan": {
                "status": "ok",
                "plan": "Max",
                "windows": [
                    {"label": "5-hour limit", "percentUsed": 1, "resetsAt": "2026-10-18T21:29:59.908Z", "resetsIn": "4h 47m"},
                    {"label": "Weekly \u00b7 all models", "percentUsed": 3, "resetsAt": "2026-10-25T13:59:59.908Z", "resetsIn": "6d 21h"},
                    {"label": "Weekly \u00b7 Fable", "percentUsed": 1, "resetsAt": "2026-10-25T13:59:59.908Z"},
                ],
                "extraUsage": {"enabled": True},
            },
            "context": {"percentUsed": 25},
        }
        u = usage.normalize_usage(real)
        assert u is not None
        assert (u["five_hour"]["used"], u["weekly"]["used"], u["fable"]["used"]) == (1.0, 3.0, 1.0)
        assert u["weekly"]["resets_at"] == pytest.approx(
            dt.datetime(2026, 10, 25, 13, 59, 59, 908000, tzinfo=dt.UTC).timestamp(), abs=10**-2
        )
        assert usage.normalize_usage(real["plan"]) == u

    def test_next_weekly(self):
        t = dt.datetime(2026, 10, 18, 17, 1).timestamp()  # Sunday just after 17:00
        n = dt.datetime.fromtimestamp(need(spec.next_weekly("Sun 17:00", t)))
        assert (n.weekday(), n.hour, n.day) == (6, 17, 25)




class StateLock:
    def test_a_lock_that_stays_held_raises_instead_of_running_unlocked(self):
        with (
            tempfile.TemporaryDirectory() as d,
            locked(Path(d) / "x", timeout=5),
            pytest.raises(TimeoutError),
            locked(Path(d) / "x", timeout=0.2),
        ):
            pass

