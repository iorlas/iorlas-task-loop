"""The fake route.py process (tl-7y6.4.3), contract 4, and the network-resume done-when (tl-7y6.2.13): a vendor that drops
mid-stream twice and then succeeds is one step, one ref, no lane out, no retry counted. """
import contextlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest import mock

from support.case import Case
from support.tmpdir import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "task-loop"
sys.path.insert(0, str(SKILL))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402, F401

# isort: split
from support import (  # noqa: E402
    dlcall,
    fake_route,
    netgate,
)
from support.fake_clock import FakeClock  # noqa: E402
from support.narrow import must  # noqa: E402

from taskloop.adapters import childenv, delegate_wire  # noqa: E402
from taskloop.adapters import delegate as dl  # noqa: E402
from taskloop.app.loop.net import NetState  # noqa: E402
from taskloop.contracts.env import snapshot  # noqa: E402
from taskloop.contracts.kinds import Kind  # noqa: E402
from taskloop.domain import outcome as oc  # noqa: E402
from taskloop.domain.lanes import policy as lp  # noqa: E402
from taskloop.stores import call_state as cs  # noqa: E402

DELEGATE = fake_route.delegate_dir()
CONTRACT = dl.resolve().contract
FIXTURES = sorted(fake_route.FIXTURE_DIR.glob("*.json"))
FAKE = str(Path(__file__).resolve().parents[1] / "support" / "fake_route.py")


class Fake(Case):
    def setup_method(self):
        self.tmp = TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.script = self.dir / "script.json"
        self.env = dict(os.environ, FAKE_ROUTE_SCRIPT=str(self.script), FAKE_ROUTE_DELEGATE=str(DELEGATE))
        self.resolved = dl.Resolved(DELEGATE, FAKE, CONTRACT, "explicit")
        self.addCleanup(self.tmp.cleanup)

    def teardown_method(self):
        self.tmp.cleanup()

    def script_with(self, steps, net=None):
        self.script.write_text(json.dumps({"steps": steps, "net": net or [True]}))

    def runner(self, cmd, **kw: Any):  # route.py is fake_route.main(argv) in this process: the same seam, a different script
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, self.env), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = fake_route.main(list(cmd[2:]))
        return subprocess.CompletedProcess(cmd, code, out.getvalue(), err.getvalue())

    def req(self, **kw):
        return dlcall.request("worker", str(self.dir), task="t-1", parent="t-1", title="x", timeout_s=900, **kw)

    def call(self, runner=None, **kw):
        return dlcall.Got(dl.call(self.resolved, self.req(**kw), "do it", {"type": "object"}, runner or self.runner,
                                       childenv.current_env(snapshot())))

    def argv_log(self):
        return [json.loads(x) for x in Path(str(self.script) + ".log").read_text().splitlines()]

    # --- the seam itself -------------------------------------------------------------------------------------------

    def test_argv_uses_only_flags_the_contract_lists(self):
        argv = self.req(resume="r", authored_by="a", call_id="c", brief_path="b.md", schema_path="s.json",
                        writer_exec_allow=[["just", "shot"]]).to_argv("python3", "route.py")
        assert "--host" not in argv
        assert "--no-wait" not in argv
        flags = {x for x in argv if x.startswith("--")}
        assert flags <= set(CONTRACT["run_args"])
        assert "--timeout" in flags
        assert argv[argv.index("--timeout") + 1] == "900"

    def test_a_done_answer_has_no_stop_and_carries_the_ref(self):
        self.script_with([{"step": "done", "data": {"a": 1}}])
        r = self.call()
        assert (r.done, r.stop, r.data, r.ref, r.source) == (True, None, {"a": 1}, "fake-1", "delegate")

    def test_answer_keeps_the_actual_argv_and_unabridged_stdout_and_stderr(self):
        seen = []
        body = fake_route.stop_answer("no_lane", say="no ready lane")
        stdout = "routing trace " + "x" * 500 + "\n" + json.dumps(body)
        stderr = "harness trace " + "y" * 500

        def runner(argv, **kw):
            seen.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, stdout, stderr)

        answer = dl.call(self.resolved, self.req(), "do it", {}, runner, {})
        assert list(answer.argv) == seen[0]
        assert seen[0][seen[0].index("--brief") + 1].endswith("brief.md")
        assert seen[0][seen[0].index("--schema") + 1].endswith("schema.json")
        assert answer.raw == body
        assert answer.trace == stdout + "\n" + stderr

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
            assert must(r.stop).reason == exp, fx.name
            assert (must(r.stop).scope, must(r.stop).permanence, must(r.stop).retry_kind) == lp_facts(exp), fx.name
            a = lp.decide(must(r.stop), lp.Ctx(now=1000.0))
            assert not (isinstance(a, (lp.Yield, lp.Fail)) and oc.make(Kind[a.kind]).rule.makes_ask), fx.name
        assert replayed >= 5

    # --- the contract and the table agree ---------------------------------------------------------------------------

    def test_the_closed_lists_equal_contract_json_and_every_reason_has_a_policy_row(self):
        assert tuple(CONTRACT["scopes"]) == tuple(sorted(lp.SCOPES, key=CONTRACT["scopes"].index))
        assert set(CONTRACT["scopes"]) == set(lp.SCOPES)
        assert set(CONTRACT["permanences"]) == set(lp.PERMANENCES)
        assert set(CONTRACT["retry_kinds"]) == set(lp.RETRY_KINDS)
        for reason, r in CONTRACT["reasons"].items():  # adding a reason without a row fails here
            facts = (r["scope"], r["permanence"], r["retry"])
            assert facts in lp.TABLE, f"reason {reason} has no lane_policy row for {facts}"

    # --- synthesized stops, never a raise ---------------------------------------------------------------------------

    def test_no_answer_is_a_synthesized_stop_of_the_machine_that_tries_again(self):
        r = self.call(runner=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "Traceback"), resume="r1")
        assert (r.source, must(r.stop).reason) == ("synthesized", "no_answer")  # not delegate's own `crash` (needs_owner)
        assert (must(r.stop).scope, must(r.stop).permanence, must(r.stop).retry_kind) == ("machine", "transient", "none")
        assert must(r.stop).ref == "r1"

    def test_a_wrong_shape_is_a_contract_violation_and_a_call_the_engine_ended_is_a_timeout(self):
        for bad in ('{"v": 2, "status": "done"}', '{"contract": 2, "stop": null}', '{"contract": 4}', '{"contract": 4, "stop": 7}'):
            r = self.call(runner=lambda cmd, _bad=bad, **kw: subprocess.CompletedProcess(cmd, 0, _bad, ""))
            assert must(r.stop).reason == "contract_violation", bad
            assert (must(r.stop).scope, must(r.stop).permanence) == ("machine", "needs_owner")

        def hang(cmd, **kw):
            raise dl.Stopped("no worker output for 20 min")
        r = self.call(runner=hang, resume="r9")
        assert (must(r.stop).reason, must(r.stop).scope, must(r.stop).ref) == ("timeout", "bead", "r9")
        assert "no worker output" in r.say

        def backstop(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, 1)
        assert must(self.call(runner=backstop).stop).reason == "timeout"

        def missing(cmd, **kw):
            raise FileNotFoundError("python")
        assert must(self.call(runner=missing).stop).reason == "no_answer"

    def test_a_killed_stop_is_a_signal_and_sandbox_limit_denials_do_not_count(self):
        k = lp.stop_of(delegate_wire.result_of(fake_route.stop_answer("killed", "r1")))
        assert (must(k).scope, must(k).permanence, must(k).retry_kind, bool(must(k).signal)) == ("machine", "transient", "none", True)
        assert isinstance(lp.decide(must(k), lp.Ctx(now=1.0)), lp.Yield)
        n = lp.stop_of(delegate_wire.result_of(fake_route.stop_answer("network", "r1", partial=True)))
        assert (must(n).reason, must(n).ref, must(n).resumable, must(n).partial, must(n).signal) == ("network", "r1", True, True, 0)
        j = {
            "denied": [
                {"kind": "sandbox_limit", "tool": "Bash", "input": {}},
                {"kind": "policy", "tool": "Bash", "input": {"command": "ls"}},
            ]
        }
        assert [d.kind for d in delegate_wire.denied_of(j["denied"])] == ["policy"]

    # --- the done-when: drops twice, then succeeds ------------------------------------------------------------------

    def drive(self, steps, probe, key=("write", 1, 0, 1)):
        """The executor loop of the engine (R21's), in miniature: call, decide, wait for the net, resume the same ref."""
        self.script_with(steps)
        clk, net = FakeClock(), NetState()
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
            while not net.poll(probe, clk.now()):
                clk.advance(netgate.PROBE_EVERY)
            ctx_kw["waited_net_s"] = ctx_kw.get("waited_net_s", 0) + (clk.now() - t0)
            resume = a.resume

    def test_a_vendor_that_drops_twice_then_succeeds_is_one_step_with_one_ref(self):
        probe = netgate.FakeProbe([False, False, True, False, True])
        r, st, actions, calls, _ = self.drive([{"step": "network", "partial": True}, {"step": "network", "partial": True}, "done"], probe)
        assert (r.done, r.stop, calls) == (True, None, 3)
        assert {r.ref, st.ref} == {"fake-1"}                       # the ref of call 1 is the ref of the answer
        runs = [a for a in self.argv_log() if a[0] == "run"]
        assert len(runs) == 3
        assert "--resume" not in runs[0]
        assert [a[a.index("--resume") + 1] for a in runs[1:]] == ["fake-1", "fake-1"]
        assert len(actions) == 2
        assert all(isinstance(a, lp.WaitNet) and a.resume == "fake-1" and a.charges == "" for a in actions)
        assert st.phase == "returned"
        assert must(cs.reattach(cs.load_for(self.dir / "ck", "t-1", ("write", 1, 0, 1))))[0] == "answer"

    def test_a_dropped_call_charges_no_counter_and_marks_no_lane(self):
        r, _st, actions, _calls, _clk = self.drive(["network", "done"], netgate.FakeProbe([False, True]))
        a = actions[0]
        for charged in ("attempt", "crashes", "polls", "waited_lane_s"):
            assert a.charges != charged
        assert not isinstance(a, (lp.Reroute, lp.NewThread, lp.Retry, lp.Fail))
        assert r.done

    def test_a_restart_after_the_first_drop_resumes_the_ref_from_the_call_state(self):
        self.script_with(["network", "done"])
        st = cs.begin(self.dir / "ck", "run-1", "t-1", ("write", 1, 0, 1))
        first = self.call()
        st.note_ref(first.ref)
        what = cs.reattach(cs.load_for(self.dir / "ck", "t-1", ("write", 1, 0, 1)))  # the loop was killed here
        assert must(what)[:2] == ("resume", "fake-1")
        again = self.call(resume=must(what)[1])
        assert (again.done, again.ref) == (True, "fake-1")


def lp_facts(reason):
    r = CONTRACT["reasons"][reason]
    return (r["scope"], r["permanence"], r["retry"])
