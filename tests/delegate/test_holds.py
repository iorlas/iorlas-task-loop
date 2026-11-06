"""Owner holds: record, back_at, stale asks."""

import copy
import io
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from delegate.app import answer, env, fleet, launch, status
from delegate.app import decide as dec
from delegate.app.supervisor import RunHooks
from delegate.cli import verbs
from delegate.contracts import stops
from delegate.contracts.state import RefRecord
from delegate.domain.holds.book import HoldBook
from delegate.domain.lanes.lane import Lane
from support.case import Case
from support.procsim import real_proc

import hermetic  # noqa: F401  (a home of its own for every test)
import routing_support as support
from test_route import CFG, T, argparse_ns, lanes, route


class Holds(Case):
    """delegate-dns: an owner hold {lane, roles, set_by, set_at, until (mandatory), reason}."""

    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(env, "config_dir", return_value=Path(self.tmp.name))
        p.start()
        self.addCleanup(p.stop)

    def main(self, *argv):
        real, sys.stdout = sys.stdout, io.StringIO()
        try:
            code = route.main(list(argv))
            return code, json.loads(sys.stdout.getvalue())
        finally:
            sys.stdout = real

    def test_a_hold_without_until_is_refused(self):
        with pytest.raises(ValueError):
            support.add_hold("OPENAI_SUBSCRIPTION", None, "pause")
        code, out = self.main("hold", "OPENAI_SUBSCRIPTION", "--reason", "pause")
        assert (code, out["ok"]) == (1, False)
        assert "--until" in out["error"]
        assert env.load_state().holds == {}
        for bad in ("yesterday", "1000"):
            assert self.main("hold", "OPENAI_SUBSCRIPTION", "--until", bad)[0] == 1
        assert self.main("hold", "NOPE", "--until", "+2h")[0] == 1
        assert env.load_state().holds == {}
        code, out = self.main(
            "hold", "OPENAI_SUBSCRIPTION", "--until", str(int(time.time()) + 3600), "--reason", "epoch as the command line gives it"
        )
        assert (code, out["ok"]) == (0, True)
        assert self.main("hold", "OPENAI_SUBSCRIPTION", "--until", "2099-01-01T00:00:00+00:00")[0] == 0
        assert len(env.load_state().holds) == 2

    def test_a_refusal_says_why_there_is_no_transcript_and_what_held_the_lane(self):
        support.add_hold("OPENAI_SUBSCRIPTION", "+1h", "x")
        a = argparse_ns(
            "worker", call_id="c#9", task=None, parent=None, title=None, brief=None, timeout=5, unattended=True, schema=None, resume="old"
        )
        with support.fleet_patches(lanes()), mock.patch("sys.stdout", io.StringIO()) as out:
            env.update_state(
                lambda s: s.refs.__setitem__(
                    "old", RefRecord(lane="OPENAI_SUBSCRIPTION", model="gpt-6.1-sol", mode="write", effort="medium")
                )
            )
            verbs.cmd_run(a, copy.deepcopy(CFG))
        r = json.loads(out.getvalue())
        assert (r["transcript_status"], r["call_id"], r["stop"]["reason"]) == ("not_launched", "c#9", "held")
        assert answer.schema_problem(r, stops.CONTRACT["answer_schema"]) is None

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_hold_stops_its_roles_until_it_ends_and_the_trace_says_who(self):
        h = support.add_hold("OPENAI_SUBSCRIPTION", "+2h", "weekly budget", ["worker", "light"], t=T)
        assert (h.set_by, h.until, h.roles) == ("owner", T + 7200, ["light", "worker"])
        st = env.load_state()
        d = support.decide(
            "worker", copy.deepcopy(CFG), lanes(), st, T, {"authored_by": None, "failed": [], "premium": None, "allow_degraded": False}
        )
        assert d["lane"] != "OPENAI_SUBSCRIPTION"
        assert any(x.startswith("OPENAI_SUBSCRIPTION: rejected, held: owner until") and "weekly budget" in x for x in d["trace"]), d[
            "trace"
        ]
        p = support.decide(
            "planner", copy.deepcopy(CFG), lanes(), st, T, {"authored_by": None, "failed": [], "premium": None, "allow_degraded": False}
        )
        assert p["lane"] == "OPENAI_SUBSCRIPTION"  # the hold names roles
        later = support.decide(
            "worker",
            copy.deepcopy(CFG),
            lanes(),
            st,
            T + 7201,
            {"authored_by": None, "failed": [], "premium": None, "allow_degraded": False},
        )
        assert later["lane"] == "OPENAI_SUBSCRIPTION"  # and ends by itself

    def test_a_hold_with_no_roles_stops_the_lane_for_every_role(self):
        support.add_hold("OPENAI_SUBSCRIPTION", "+1h", "", t=T)
        for role in ("planner", "worker", "reviewer"):
            d = support.decide(
                role,
                copy.deepcopy(CFG),
                lanes(),
                env.load_state(),
                T,
                {"authored_by": None, "failed": [], "premium": None, "allow_degraded": False},
            )
            assert d.get("lane") != "OPENAI_SUBSCRIPTION", role

    def test_refusals_under_a_hold_wait_for_its_end_never_one_second(self):
        h = support.add_hold("OPENAI_SUBSCRIPTION", "+3h", "pause", ["worker"], t=T)
        a = argparse_ns("worker", resume="old")
        st = support.doc_of({})
        st.holds[h.id] = h
        st.refs["old"] = RefRecord(lane="OPENAI_SUBSCRIPTION", model="gpt-6.1-sol", mode="write", effort="medium")
        with (
            mock.patch.object(env, "load_state", return_value=st),
            support.fleet_patches(lanes()),
            mock.patch.object(env, "now", return_value=T),
        ):
            d, _, _, _ = dec.decision(a, copy.deepcopy(CFG))
        assert (d["action"], d["retry_after"], d["outcome"]) == ("stop", h.until, "held")
        assert "owner" in d["say"]
        res = launch.launch_worker(
            {"role": "worker", "lane": "OPENAI_SUBSCRIPTION", "how": {"kind": "codex", "sandbox": "workspace-write"}},
            "b",
            argparse_ns("worker"),
            "rid",
            T,
            CFG,
            RunHooks(),
        )
        assert (res["retry_after"], res["outcome"]) == (h.until, "held")

    @real_proc("delegate: a worker, git or CLI process")
    def test_release_and_status_show_the_holder_and_expiry(self):
        h = support.add_hold("OPENAI_SUBSCRIPTION", "+2d", "budget", ["worker"], "alice")
        with support.fleet_patches(lanes()):
            _, st = self.main("status", "--json")
        row = st["holds"][0]
        assert (row["id"], row["set_by"], row["roles"], row["reason"]) == (h.id, "alice", ["worker"], "budget")
        assert row["until"] > time.time()
        assert self.main("release", h.id)[0] == 0
        assert self.main("holds")[1]["holds"] == []
        assert self.main("release", "nothing")[0] == 1


class BackAt:
    def test_a_lane_over_its_ceiling_is_back_at_that_windows_reset(self):
        S = env.settings_of(env.load_routing())
        lane = Lane("OPENAI_SUBSCRIPTION", "openai", "subscription")
        lane.five, lane.five_reset, lane.week, lane.week_reset = 99, 1000.0, 10, 9000.0
        assert lane.back_at(S) == 1000.0
        lane.five, lane.week = 10, 99
        assert lane.back_at(S) == 9000.0
        lane.week = 10
        assert lane.back_at(S) is None
        lane.out, lane.out_until = True, 500.0
        assert lane.back_at(S) == 500.0


class StaleHolds(Case):
    """delegate-eau: a hold whose lane has gone quiet raises ONE ask (a status field)."""

    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(env, "config_dir", return_value=Path(self.tmp.name))
        p.start()
        self.addCleanup(p.stop)

    def lanes(self, week):
        lane = Lane("OPENAI_SUBSCRIPTION", "openai", "subscription")
        lane.week, lane.five = week, 3
        return {lane.name: lane}

    def test_one_ask_for_a_stale_hold_never_a_second_and_nothing_is_printed(self):
        h = support.add_hold("OPENAI_SUBSCRIPTION", "+2d", "weekly spent")
        real, sys.stdout = sys.stdout, io.StringIO()
        try:
            asks, _st = fleet.settle_holds(env.states(), self.lanes(80), env.load_state(), env.now())
            assert asks == []  # the lane is still full: the hold is doing its job
            asks, _st = fleet.settle_holds(env.states(), self.lanes(0), env.load_state(), env.now())
            asks2, st2 = fleet.settle_holds(env.states(), self.lanes(0), env.load_state(), env.now() + 600)
            printed = sys.stdout.getvalue()
        finally:
            sys.stdout = real
        assert printed == ""
        asks_d: list[Any] = [a.as_dict() for a in asks]
        asks2_d: list[Any] = [a.as_dict() for a in asks2]
        assert [(a["kind"], a["id"], a["lane"]) for a in asks_d] == [("hold_stale", h.id, "OPENAI_SUBSCRIPTION")]
        assert asks2_d == asks_d  # the same ask (same id, same raised_at), not a new one
        assert st2.holds[h.id].stale_at == asks_d[0]["raised_at"]
        assert ("route.py release " + h.id) in asks_d[0]["answer"]
        assert HoldBook(st2.holds).rows(env.now())[0]["stale"]

    def test_status_carries_asks(self):
        ck: dict[str, Any] = {
            "v": 1,
            "at": env.now(),
            "legend": {},
            "next_worker": {"action": "stop", "lane": None, "model": None, "effort": None, "say": None},
            "lanes": [],
        }
        payload = status.status_payload(CFG, self.lanes(50), ck, env.load_state(), env.now())
        assert payload["asks"] == []
        assert "health" in payload
