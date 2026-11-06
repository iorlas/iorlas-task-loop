"""Network facts (delegate-4n7, delegate-0sf, delegate-dlz): the probe, the words of a dropped connection, network never benching a pair,
roles{} in status --json --cheap, and the adapter registry."""

import contextlib
import io
import json
import os
import re
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any
from unittest import mock

from any_agent import procs
from any_agent.classify import Outcome
from any_agent.drops import looks_dropped
from delegate.adapters import netprobe
from delegate.app import env, harnesses, launch, net
from delegate.app import roles as role_view
from delegate.app.settle import Settler
from delegate.contracts import stops
from delegate.contracts.history import RunRow
from delegate.contracts.routing import BreakerPolicy
from delegate.domain.health.ledger import HealthLedger, failure_fields
from delegate.domain.lanes import profiles
from support.case import Case

import hermetic  # noqa: F401  (a home of its own for every test)
import routing_support as support
from test_route import CFG, T, lanes, route

LANES = Path(__file__).resolve().parents[2] / "src" / "delegate" / "adapters"


@contextlib.contextmanager
def listener():
    """A local TCP server: the probe's 'vendor' that is up."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    try:
        yield f"127.0.0.1:{srv.getsockname()[1]}"
    finally:
        srv.close()


def closed_port():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.close()
    return f"127.0.0.1:{port}"


class Probe:
    def test_up_when_a_host_connects(self):
        with listener() as host:
            r: Any = netprobe.probe([host])
        assert r["up"]
        assert r["hosts"][host] == "ok"

    def test_down_when_nothing_connects(self):
        r: Any = netprobe.probe([closed_port()], connect=lambda addr, timeout: (_ for _ in ()).throw(OSError("refused")))
        assert (r["up"], r["why"]) == (False, "offline")

    def test_a_dns_outage_is_not_up_even_when_an_ip_literal_answers(self):
        def resolve(name, port):
            raise socket.gaierror("no dns")

        r: Any = netprobe.probe(["api.anthropic.com"], resolve=resolve, connect=lambda addr, timeout: None)
        assert (r["up"], r["ip_up"], r["why"]) == (False, True, "dns")
        assert r["hosts"]["api.anthropic.com"] == "dns"

    def test_a_resolver_that_hangs_cannot_hold_the_probe_past_three_seconds(self):
        gate = threading.Event()
        time.time()
        slow: Any = lambda n, p: gate.wait(30)  # noqa: E731  stands in for the resolver, which is typed to answer a str
        r: Any = netprobe.probe(["api.anthropic.com", "chatgpt.com"], resolve=slow, connect=lambda addr, timeout: None)
        gate.set()
        assert not r["up"]
        assert r["hosts"]["chatgpt.com"] == "slow"

    def test_no_subprocess_and_no_vendor_call(self):
        src = (LANES / "netprobe.py").read_text(encoding="utf-8")
        assert not re.search(r"(?m)^\s*(import|from)\s+subprocess", src)
        assert "os.system" not in src

    def test_the_cache_keeps_since_until_up_flips(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "net.json")

            def mk(up, at) -> dict[str, Any]:
                return {"up": up, "ip_up": up, "why": "ok" if up else "offline", "hosts": {"a": "ok" if up else "tcp"}, "at": at}

            netprobe.record(p, mk(True, 100.0))
            netprobe.record(p, mk(True, 200.0))
            assert (netprobe.load(p) or {})["since"] == 100.0
            netprobe.record(p, mk(False, 300.0))
            assert (netprobe.load(p) or {})["since"] == 300.0

    def test_view_is_unknown_when_stale_or_absent(self):
        c: dict[str, Any] = {"up": True, "since": 1, "at": 1000.0, "hosts": {"a": "ok", "b": "tcp"}}
        assert netprobe.view(c, ["a"], 1010.0)["up"] is True
        assert netprobe.view(c, ["b"], 1010.0)["up"] is False
        assert netprobe.view(c, ["a", "b"], 1010.0)["up"] is True
        assert netprobe.view(c, ["zzz"], 1010.0)["up"] is True  # untested host: the overall answer
        assert netprobe.view(c, ["a"], 1000.0 + netprobe.FRESH_S + 1)["up"] is None
        assert netprobe.view(None, ["a"], 5.0)["up"] is None


class Words:
    def test_what_a_dropped_connection_says(self):
        for text in (
            "request failed: getaddrinfo ENOTFOUND chatgpt.com",
            "Reconnecting... waiting for network (Connection failed: error sending request)",
            "stream disconnected before completion: websocket closed by server before response.completed",
            "stream disconnected before completion: idle timeout waiting for websocket",
            "error sending request for url (https://chatgpt.com/backend-api/ps/mcp)",
            "API Error: Unable to connect to API (ECONNRESET)",
            "Connection reset by peer",
            "socket hang up",
            "dns error: failed to lookup address",
        ):
            assert looks_dropped(text), text

    def test_what_is_not_a_drop(self):
        for text in (
            "stream disconnected before completion: Incomplete response returned, reason: max_output_tokens",
            "You have hit your usage limit",
            "model not supported",
            "the test suite failed: 3 errors",
            "",
        ):
            assert not looks_dropped(text), text


class RouteNet(Case):
    def setup_method(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        p = mock.patch.dict(os.environ, {"DELEGATE_CONFIG_DIR": self.d.name})
        p.start()
        self.addCleanup(p.stop)

    def run_main(self, argv, patch_spawns=True):
        out = io.StringIO()
        boom = mock.Mock(side_effect=AssertionError("a process was spawned"))
        with contextlib.ExitStack() as ex:
            if patch_spawns:
                ex.enter_context(mock.patch.object(subprocess, "run", boom))
                ex.enter_context(mock.patch.object(subprocess, "Popen", boom))
            ex.enter_context(mock.patch.object(net, "net_probe", vars(net)["REAL_NET_PROBE"]))
            ex.enter_context(contextlib.redirect_stdout(out))
            rc = route.main(argv)
        return rc, json.loads(out.getvalue())

    def test_route_net_answers_fast_with_no_process(self):
        with listener() as host:
            time.time()
            rc, r = self.run_main(["net", "--host", host])
        assert (rc, r["up"], r["why"]) == (0, True, "ok")

    def test_route_net_down_is_still_exit_zero_with_the_object(self):
        rc, r = self.run_main(["net", "--host", closed_port()])
        assert (rc, r["up"]) == (0, False)

    def test_the_probe_is_cached_for_status_cheap(self):
        with listener() as host:
            self.run_main(["net", "--host", host])
        c: Any = netprobe.load(str(env.net_cache_path()))
        assert c["up"]


class NotTheLanesFault:
    def test_network_never_counts_against_a_pair(self):
        assert not stops.benches_pair("network")
        led = HealthLedger(BreakerPolicy())
        fields: Any = failure_fields("network", "", "error sending request", None)
        rows: list[Any] = [
            RunRow(
                ts=1000.0 + i,
                run_id=f"r{i}",
                task=f"t{i}",
                role="worker",
                lane="OPENAI_SUBSCRIPTION",
                model="m",
                effort="high",
                done=False,
                **fields,
            )
            for i in range(12)
        ]
        st = led.fold(rows)
        v = led.view(st, "OPENAI_SUBSCRIPTION", "m", 1100.0)
        assert (v.state, v.usable, {k: v for k, v in st.keys.items() if '|' in k}, st.outs) == ("up", True, {}, {})

    def test_a_failure_that_names_no_cause_becomes_network_only_when_the_net_is_down(self):
        d: dict[str, Any] = {"lane": "OPENAI_SUBSCRIPTION"}
        down = {"up": False, "ip_up": False, "why": "offline", "ms": 1, "hosts": {}, "at": 1.0}
        for reason in ("hung", "worker_failed", "vendor_blip"):
            o = Outcome(reason, "", "ours")
            with mock.patch.object(net, "net_probe", lambda hosts=None: down):
                assert launch.settler().net_pass(o, d).reason == "network", reason
            assert launch.settler().net_pass(o, d).reason == reason  # test_route's probe says up
        for reason in ("rate_limited", "bad_request", "logged_out", "secrets", "timeout", "credit_exhausted"):
            o = Outcome(reason, "", "ours")
            with mock.patch.object(net, "net_probe", lambda hosts=None: down):
                assert launch.settler().net_pass(o, d).reason == reason, reason  # never second-guessed, never probed

    def test_dropped_words_win_without_a_probe(self):
        probe = mock.Mock(side_effect=AssertionError("probed"))
        with mock.patch.object(net, "net_probe", probe):
            o = launch.settler().net_pass(
                Outcome("worker_failed", "stream disconnected before completion: websocket closed", "event"), {"lane": "X"}
            )
        assert o.reason == "network"

    def test_a_hung_worker_on_a_dead_net_marks_no_lane_out(self):
        d: dict[str, Any] = {"lane": "OPENAI_SUBSCRIPTION", "model": "m"}
        a = mock.Mock(schema=None, timeout=60)
        down = {"up": False, "ip_up": False, "why": "offline", "ms": 1, "hosts": {}, "at": 1.0}
        res: dict[str, Any] = {"hung_words": "printed nothing within 120s", "hung_kind": "first_event", "ref": None}
        with mock.patch.object(net, "net_probe", lambda hosts=None: down), mock.patch.object(Settler, "mark_out") as mark:
            launch.settler().apply(res, Outcome("hung", "", "ours"), d, T, "codex", a)
        mark.assert_not_called()
        assert (res["outcome"], res["resumable"]) == ("network", False)
        assert "hung_words" not in res


class Roles:
    def test_roles_say_usable_and_net(self):
        ls = lanes()
        cached: dict[str, Any] = {"up": True, "since": T - 50, "at": T - 5, "hosts": {"chatgpt.com": "ok", "api.anthropic.com": "tcp"}}
        roles: Any = role_view.roles_view(CFG, ls, support.router(CFG, T), support.doc_of({}), T, cached)
        assert set(roles) == set(CFG["roles"])
        assert roles["planner"]["usable"]
        assert roles["planner"]["lane"] == "OPENAI_SUBSCRIPTION"
        assert "chatgpt.com" in roles["planner"]["hosts"]
        assert roles["planner"]["net"]["up"]  # one of its vendors answers
        assert roles["planner"]["net"]["age_s"] == 5

    def test_an_unusable_role_says_why_and_when(self):
        ls = lanes(
            openai={"out": True, "out_until": T + 600, "out_reason": "limit"},
            sub={"out": True, "out_until": T + 900, "out_reason": "limit"},
        )
        roles: Any = role_view.roles_view(CFG, ls, support.router(CFG, T), support.doc_of({}), T, None)
        assert roles["planner"]["usable"] is False
        assert roles["planner"]["until"] == (T + 600)
        assert roles["planner"]["net"]["up"] is None

    def test_deciding_roles_leaves_the_lanes_as_it_found_them(self):
        ls = lanes()
        role_view.roles_view(CFG, ls, support.router(CFG, T), support.doc_of({}), T, None)
        assert all(not ln.busy and not ln.out for ln in ls.values())

    def test_refresh_brings_net_and_holds_up_to_date_without_a_spawn(self):
        roles = {
            "worker": {
                "usable": True,
                "lane": "OPENAI_SUBSCRIPTION",
                "model": "m",
                "why": None,
                "until": None,
                "hosts": ["chatgpt.com"],
                "net": {"up": None},
            }
        }
        cached: dict[str, Any] = {"up": False, "since": T, "at": T, "hosts": {"chatgpt.com": "tcp"}}
        r: Any = role_view.refresh(
            roles, [{"lane": "OPENAI_SUBSCRIPTION", "roles": ["worker"], "until": T + 100, "reason": "pace"}], cached, T + 1
        )
        assert (r["worker"]["usable"], r["worker"]["net"]["up"]) == (False, False)
        assert r["worker"]["until"] == (T + 100)


class Cheap(Case):
    def setup_method(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        p = mock.patch.dict(os.environ, {"DELEGATE_CONFIG_DIR": self.d.name})
        p.start()
        self.addCleanup(p.stop)

    def cheap(self):
        boom = mock.Mock(side_effect=AssertionError("a process was spawned"))
        out = io.StringIO()
        with (
            mock.patch.object(subprocess, "run", boom),
            mock.patch.object(subprocess, "Popen", boom),
            mock.patch.object(procs, "run_capture", boom),
            mock.patch.object(socket, "create_connection", boom),
            contextlib.redirect_stdout(out),
        ):
            rc = route.main(["status", "--json", "--cheap"])
        return rc, json.loads(out.getvalue())


    def test_cheap_without_any_snapshot_has_empty_roles(self):
        rc, d = self.cheap()
        assert (rc, d["roles"]) == (0, {})
        assert d["network"]["up"] is None


class Adapters:
    def test_the_three_runners_are_data_and_every_cli_has_watchdog_limits(self):
        assert set(profiles.REGISTRY) == {"codex", "opencode", "claude_p"}
        for a in profiles.REGISTRY.values():
            assert a.cli in harnesses.LIMITS
        assert profiles.REGISTRY["opencode"].resume == "untested"
        assert set(launch.PREPARE) == set(
            profiles.REGISTRY
        )  # each runner has one harness preparation, and launch_worker is the only launcher

    def test_every_lane_in_routing_json_has_hosts_to_probe(self):
        for lane in CFG["lanes"]:
            assert profiles.hosts_of(lane), lane
