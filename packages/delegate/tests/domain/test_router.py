"""The router is pure and replays the characterization goldens (golden/decisions.json, taken from route.py before D2 moved it)."""

import builtins
import json
import os
import socket
import time
from pathlib import Path
from typing import Any
from unittest import mock

from delegate.app.fleet import mark_busy
from delegate.contracts import codec
from delegate.contracts.routing import AccountOut, CallArgs, Error, Routing, Run, Stop
from delegate.contracts.state import StateDoc
from delegate.domain.accounts.account import Account
from delegate.domain.health.ledger import PairView
from delegate.domain.holds.book import HoldBook
from delegate.domain.routing.router import Router
from tltestkit.case import Case

ROOT = Path(__file__).resolve().parents[4]

HERE = Path(__file__).resolve().parent
T = 1_000_000_000.0
CFG = json.loads((ROOT / "packages" / "delegate" / "src" / "delegate" / "data" / "routing.json").read_text(encoding="utf-8"))
GOLDEN = json.loads((HERE / "golden" / "decisions.json").read_text(encoding="utf-8"))


def broken(b: dict[str, Any]) -> PairView:
    """A pair view of a golden, whatever it recorded, as a benched one."""
    kw: dict[str, Any] = {**b, "state": "broken", "usable": False}
    return PairView(**kw)


def account_of(spec):
    account = Account(spec["name"], spec["family"], spec["kind"], spec["shared"])
    for k, v in spec.items():
        val = {m: broken(b) for m, b in v.items()} if k in ("benched", "hview") else v
        if k not in ("name", "family", "kind", "shared"):
            setattr(account, k, val)
    return account


def routing(overrides):
    cfg = json.loads(json.dumps(CFG))
    cfg["settings"].update(overrides)
    return codec.from_json(Routing, cfg)


def call_args(a, unattended):
    return CallArgs(
        authored_by=a["authored_by"],
        premium=a["premium"],
        allow_degraded=a["allow_degraded"],
        unattended=unattended,
        resume=a["resume"],
        cap=a["cap"],
    )


def run_scenario(sc):
    r = routing(sc["settings"])
    doc = codec.from_json(StateDoc, dict(sc["state"], v=2))
    accounts = mark_busy({s["name"]: account_of(s) for s in sc["accounts"]}, doc, r.settings, T, lambda: 77)
    router = Router(r, HoldBook(doc.holds), doc.prev, T)
    a = sc["args"]
    return router.route(a["role"], call_args(a, sc["unattended"]), accounts, doc.refs.get(a["resume"] or ""))


class Replay(Case):
    def setup_method(self):
        zone = mock.patch.dict(os.environ, TZ="UTC")
        zone.start()
        self.addCleanup(time.tzset)
        self.addCleanup(zone.stop)
        time.tzset()

    def test_every_golden_decision_is_reproduced(self):
        for sc in GOLDEN:
            with self.subTest(sc["name"]):
                assert run_scenario(sc).as_dict() == {k: v for k, v in sc["expect"].items() if not k.startswith("_")}


class Purity:
    def test_decide_touches_no_filesystem_socket_or_env(self):
        r = routing({})
        accounts = {"OPENAI_SUBSCRIPTION": Account("OPENAI_SUBSCRIPTION", "openai", "subscription", five=10, week=5)}
        router = Router(r, HoldBook({}), {}, T)

        def boom(*a, **k):
            raise AssertionError("the router did I/O")

        with (
            mock.patch.object(builtins, "open", boom),
            mock.patch.object(os, "stat", boom),
            mock.patch.object(os, "listdir", boom),
            mock.patch.object(socket, "socket", boom),
        ):
            d = router.decide("worker", CallArgs(), accounts)
        assert isinstance(d, Run)
        assert (d.account, d.model) == ("OPENAI_SUBSCRIPTION", "gpt-6.1-sol")

    def test_decide_does_not_change_the_accounts_it_is_given(self):
        r = routing({})
        accounts = {
            "OPENAI_SUBSCRIPTION": Account("OPENAI_SUBSCRIPTION", "openai", "subscription", five=10, week=5, out=True, out_until=T + 5)
        }
        before = repr(accounts)
        Router(r, HoldBook({}), {}, T).decide("worker", CallArgs(), accounts)
        assert repr(accounts) == before

    def test_the_decision_kinds(self):
        r = routing({})
        router = Router(r, HoldBook({}), {}, T)
        assert isinstance(router.decide("nope", CallArgs(), {}), Error)
        assert isinstance(router.decide("worker", CallArgs(), {}), Stop)
        assert isinstance(router.resume("worker", CallArgs(resume="x"), None, {}), Error)
        assert isinstance(Account("L", "f", "subscription").with_busy(T, 1, 1), Account)
        assert not hasattr(Account("L", "f", "subscription"), "held")
        assert AccountOut
