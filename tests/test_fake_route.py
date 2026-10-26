"""The fake route.py process (tl-7y6.4.3), contract 3, and the network-resume done-when (tl-7y6.2.13): a vendor that drops
mid-stream twice and then succeeds is one step, one ref, no lane out, no retry counted. The contract is FAKE_ROUTE_DELEGATE's, else
the copy in tests/fixtures/delegate3 (compared to a real delegate checkout when ~/Workspaces/iorlas-delegate-R20 or the env names one)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "task-loop"
sys.path.insert(0, str(SKILL))
import call_state as cs  # noqa: E402
import clock  # noqa: E402
import delegate_link as dl  # noqa: E402
import fake_route  # noqa: E402
import lane_policy as lp  # noqa: E402
import netgate  # noqa: E402
import outcome as oc  # noqa: E402

DELEGATE = fake_route.delegate_dir()
CONTRACT = dl.read_contract(DELEGATE)
FIXTURES = sorted((DELEGATE / "tests" / "contract" / "fixtures").glob("*.json"))
FAKE = str(SKILL / "fake_route.py")


class Fake(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.script = self.dir / "script.json"
        self.env = dict(os.environ, FAKE_ROUTE_SCRIPT=str(self.script), FAKE_ROUTE_DELEGATE=str(DELEGATE))
        self.resolved = dl.Resolved(DELEGATE, FAKE, CONTRACT, "explicit")
        self.addCleanup(self.tmp.cleanup)

    def tearDown(self):
        self.tmp.cleanup()

    def script_with(self, steps, net=None):
        self.script.write_text(json.dumps({"steps": steps, "net": net or [True]}))

    def runner(self, cmd, **kw):  # route.py is fake_route.py: the same process seam, a different script
        cmd = list(cmd)
        cmd[1] = FAKE
        return subprocess.run(cmd, **dict(kw, env=self.env))

    def req(self, **kw):
        return dl.CallRequest("worker", "do it", {"type": "object"}, str(self.dir), task="t-1", parent="t-1", title="x", timeout_s=900, **kw)

    def call(self, **kw):
        return dl.call(self.resolved, self.req(**kw), runner=self.runner)

    def argv_log(self):
        return [json.loads(x) for x in Path(str(self.script) + ".log").read_text().splitlines()]

    # --- the seam itself -------------------------------------------------------------------------------------------

    def test_the_fake_speaks_the_handshake_and_the_net_probe(self):
        self.script_with(["done"], net=[False, True])
        out = subprocess.run([sys.executable, FAKE, "contract", "--json"], capture_output=True, text=True, env=self.env).stdout
        self.assertEqual(sorted(json.loads(out)), ["contract", "reasons", "run_args"])
        self.assertEqual(json.loads(out)["contract"], 3)
        probe = netgate.RouteProbe(FAKE, run=lambda cmd, **kw: subprocess.run(cmd, **dict(kw, env=self.env)))
        self.assertEqual([probe.up(), probe.up(), probe.up()], [False, True, True])

    def test_argv_uses_only_flags_the_contract_lists(self):
        argv = dl.argv_of(self.resolved, self.req(resume="r", authored_by="a", call_id="c"), "b.md", "s.json")
        self.assertNotIn("--host", argv)
        self.assertNotIn("--no-wait", argv)
        flags = {x for x in argv if x.startswith("--")}
        self.assertLessEqual(flags, set(CONTRACT["run_args"]))
        self.assertIn("--timeout", flags)
        self.assertEqual(argv[argv.index("--timeout") + 1], "720")  # 900 - 180

    def test_a_done_answer_has_no_stop_and_carries_the_ref(self):
        self.script_with([{"step": "done", "data": {"a": 1}}])
        r = self.call()
        self.assertEqual((r.done, r.stop, r.data, r.ref, r.source), (True, None, {"a": 1}, "fake-1", "delegate"))

    def test_every_fixture_replays_to_its_expected_reason_and_a_policy_action(self):
        replayed = 0
        for fx in FIXTURES:
            exp = (json.loads(fx.read_text(encoding="utf-8")).get("expected_stop") or {}).get("reason")
            if not exp:
                continue
            self.script.unlink() if self.script.exists() else None
            for p in self.dir.glob("script.json.*"):
                p.unlink()
            self.script_with([fx.stem])
            r = self.call()
            replayed += 1
            self.assertEqual(r.stop.reason, exp, fx.name)
            self.assertEqual((r.stop.scope, r.stop.permanence, r.stop.retry_kind), lp_facts(exp), fx.name)
            a = lp.decide(r.stop, lp.Ctx(now=1000.0))
            self.assertFalse(isinstance(a, (lp.Yield, lp.Fail)) and a.outcome.rule.makes_ask, fx.name)
        self.assertGreaterEqual(replayed, 5)

    # --- the contract and the table agree ---------------------------------------------------------------------------

    def test_the_closed_lists_equal_contract_json_and_every_reason_has_a_policy_row(self):
        self.assertEqual(tuple(CONTRACT["scopes"]), tuple(sorted(lp.SCOPES, key=CONTRACT["scopes"].index)))
        self.assertEqual(set(CONTRACT["scopes"]), set(lp.SCOPES))
        self.assertEqual(set(CONTRACT["permanences"]), set(lp.PERMANENCES))
        self.assertEqual(set(CONTRACT["retry_kinds"]), set(lp.RETRY_KINDS))
        for reason, r in CONTRACT["reasons"].items():  # adding a reason without a row fails here
            facts = (r["scope"], r["permanence"], r["retry"])
            self.assertIn(facts, lp.TABLE, "reason %s has no lane_policy row for %s" % (reason, facts))

    # --- synthesized stops, never a raise ---------------------------------------------------------------------------

    def test_no_answer_is_a_synthesized_stop_of_the_machine_that_tries_again(self):
        r = dl.call(self.resolved, self.req(resume="r1"), runner=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "Traceback"))
        self.assertEqual((r.source, r.stop.reason), ("synthesized", "no_answer"))  # not delegate's own `crash` (needs_owner)
        self.assertEqual((r.stop.scope, r.stop.permanence, r.stop.retry_kind), ("machine", "transient", "none"))
        self.assertEqual(r.stop.ref, "r1")

    def test_a_wrong_shape_is_a_contract_violation_and_a_call_the_engine_ended_is_a_timeout(self):
        for bad in ('{"v": 2, "status": "done"}', '{"contract": 2, "stop": null}', '{"contract": 3}', '{"contract": 3, "stop": 7}'):
            r = dl.call(self.resolved, self.req(), runner=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, bad, ""))
            self.assertEqual((r.source, r.stop.reason), ("synthesized", "contract_violation"), bad)
            self.assertEqual((r.stop.scope, r.stop.permanence), ("machine", "needs_owner"))

        def hang(cmd, **kw):
            raise dl.Stopped("no worker output for 20 min")
        r = dl.call(self.resolved, self.req(resume="r9"), runner=hang)
        self.assertEqual((r.stop.reason, r.stop.scope, r.stop.ref), ("timeout", "bead", "r9"))
        self.assertIn("no worker output", r.say)

        def backstop(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, 1)
        self.assertEqual(dl.call(self.resolved, self.req(), runner=backstop).stop.reason, "timeout")

        def missing(cmd, **kw):
            raise FileNotFoundError("python")
        self.assertEqual(dl.call(self.resolved, self.req(), runner=missing).stop.reason, "no_answer")

    def test_a_killed_stop_is_a_signal_and_sandbox_limit_denials_do_not_count(self):
        k = dl.stop_of(CONTRACT, fake_route.stop_answer("killed", "r1"))
        self.assertEqual((k.scope, k.permanence, k.retry_kind, bool(k.signal)), ("machine", "transient", "none", True))
        self.assertIsInstance(lp.decide(k, lp.Ctx(now=1.0)), lp.Yield)
        n = dl.stop_of(CONTRACT, fake_route.stop_answer("network", "r1", partial=True))
        self.assertEqual((n.reason, n.ref, n.resumable, n.partial, n.signal), ("network", "r1", True, True, 0))
        j = {"denied": [{"kind": "sandbox_limit", "tool": "Bash", "input": {}}, {"kind": "policy", "tool": "Bash", "input": {"command": "ls"}}]}
        self.assertEqual([d["kind"] for d in dl.real_denied(j)], ["policy"])

    def test_the_copy_of_the_contract_in_this_repo_is_delegates(self):
        real = Path(os.environ.get("DELEGATE_R20") or Path.home() / "Workspaces" / "iorlas-delegate-R20")
        mine = fake_route.VENDORED / "skills" / "delegate" / "contract.json"
        if not (real / "skills" / "delegate" / "contract.json").is_file():
            self.skipTest("no delegate checkout of contract 3 here")
        self.assertEqual(json.loads(mine.read_text()), json.loads((real / "skills" / "delegate" / "contract.json").read_text()))

    # --- the done-when: drops twice, then succeeds ------------------------------------------------------------------

    def drive(self, steps, probe, key=("write", 1, 0, 1)):
        """The executor loop of the engine (R21's), in miniature: call, decide, wait for the net, resume the same ref."""
        self.script_with(steps)
        clk, net = clock.FakeClock(), netgate.NetState()
        st = cs.begin(self.dir / "ck", "run-1", "t-1", key, role="worker", now=clk.now())
        resume, ctx_kw, actions, calls = "", {}, [], 0
        while True:
            calls += 1
            r = self.call(resume=resume)
            if r.ref:
                st.note_ref(r.ref, clk.now())
            if r.stop is None:
                st.returned(r.raw, self.dir / "ck" / "write-1.raw.json", clk.now())
                return r, st, actions, calls, clk
            a = lp.decide(r.stop, lp.Ctx(now=clk.now(), resumed=bool(resume), **ctx_kw))
            actions.append(a)
            if not isinstance(a, lp.WaitNet):
                return r, st, actions, calls, clk
            net.mark_down(clk.now())
            t0 = clk.now()
            while net.poll(probe, clk.now()) != "up":
                clk.advance(netgate.PROBE_EVERY)
            ctx_kw["waited_net_s"] = ctx_kw.get("waited_net_s", 0) + (clk.now() - t0)
            resume = a.resume

    def test_a_vendor_that_drops_twice_then_succeeds_is_one_step_with_one_ref(self):
        probe = netgate.FakeProbe([False, False, True, False, True])
        r, st, actions, calls, _ = self.drive([{"step": "network", "partial": True}, {"step": "network", "partial": True}, "done"], probe)
        self.assertEqual((r.done, r.stop, calls), (True, None, 3))
        self.assertEqual({r.ref, st.ref}, {"fake-1"})                       # the ref of call 1 is the ref of the answer
        runs = [a for a in self.argv_log() if a[0] == "run"]
        self.assertEqual(len(runs), 3)
        self.assertNotIn("--resume", runs[0])
        self.assertEqual([a[a.index("--resume") + 1] for a in runs[1:]], ["fake-1", "fake-1"])
        self.assertEqual(len(actions), 2)
        self.assertTrue(all(isinstance(a, lp.WaitNet) and a.resume == "fake-1" and a.charges == "" for a in actions))
        self.assertEqual(st.phase, "returned")
        self.assertEqual(cs.reattach(cs.load_for(self.dir / "ck", "t-1", ("write", 1, 0, 1)))[0], "answer")

    def test_a_dropped_call_charges_no_counter_and_marks_no_lane(self):
        r, st, actions, calls, clk = self.drive(["network", "done"], netgate.FakeProbe([False, True]))
        a = actions[0]
        for charged in ("attempt", "crashes", "polls", "waited_lane_s"):
            self.assertNotEqual(a.charges, charged)
        self.assertNotIsInstance(a, (lp.Reroute, lp.NewThread, lp.Retry, lp.Fail))
        self.assertTrue(r.done)

    def test_a_restart_after_the_first_drop_resumes_the_ref_from_the_call_state(self):
        self.script_with(["network", "done"])
        st = cs.begin(self.dir / "ck", "run-1", "t-1", ("write", 1, 0, 1))
        first = self.call()
        st.note_ref(first.ref)
        what = cs.reattach(cs.load_for(self.dir / "ck", "t-1", ("write", 1, 0, 1)))  # the loop was killed here
        self.assertEqual(what[:2], ("resume", "fake-1"))
        again = self.call(resume=what[1])
        self.assertEqual((again.done, again.ref), (True, "fake-1"))


def lp_facts(reason):
    r = CONTRACT["reasons"][reason]
    return (r["scope"], r["permanence"], r["retry"])


class Resolve(unittest.TestCase):
    def make(self, root, contract):
        d = Path(root) / "delegate"
        (d / "skills" / "delegate").mkdir(parents=True)
        (d / "skills" / "delegate" / "contract.json").write_text(json.dumps({"contract": contract, "reasons": {}}))
        return d

    def test_an_explicit_dir_wins_a_missing_pin_refuses_and_skew_refuses(self):
        with tempfile.TemporaryDirectory() as t:
            d = self.make(t, dl.CONTRACT)
            self.assertEqual(dl.resolve(path=str(d)).source, "explicit")
            self.assertEqual(dl.resolve(pinned=Path(t) / "gone", installed=d).kind, "pin_missing_dir")  # a pin never falls through
            self.assertEqual(dl.resolve(pinned=d, installed=None).source, "pinned")
            self.assertEqual(dl.resolve(pinned=Path(t), installed=None).kind, "pin_unreadable")
            with mock.patch.object(dl, "installed_dir", return_value=None):
                self.assertEqual(dl.resolve(pinned="").kind, "not_installed")
            self.assertEqual(dl.resolve(path=str(self.make(Path(t) / "n", dl.CONTRACT + 1))).kind, "skew_delegate_newer_no_match")
            self.assertEqual(dl.resolve(path=str(self.make(Path(t) / "o", dl.CONTRACT - 1))).kind, "skew_delegate_older")

    def test_installed_dir_reads_the_user_scope_record_not_a_glob(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "plugins").mkdir()
            (Path(t) / "plugins" / "installed_plugins.json").write_text(json.dumps({"plugins": {
                "iorlas-delegate@m": [{"scope": "project", "installPath": "/p"}, {"scope": "user", "installPath": "/u"}]}}))
            self.assertEqual(dl.installed_dir(t), Path("/u"))
            self.assertIsNone(dl.installed_dir(Path(t) / "none"))


if __name__ == "__main__":
    unittest.main()
