"""The fake route.py process (tl-7y6.4.3), contract 4, and checkpoint reattachment."""
import contextlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest import mock

from tltestkit import fake_route
from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "task-loop"
sys.path.insert(0, str(SKILL))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402, F401

# isort: split
from support import dlcall  # noqa: E402
from support.argv_of import argv_of  # noqa: E402

from taskloop.adapters import delegate as dl  # noqa: E402
from taskloop.adapters import delegate_wire  # noqa: E402
from taskloop.app.workers import call_state as cs  # noqa: E402
from taskloop.domain.lanes import policy as lp  # noqa: E402
from tlkernel import childenv  # noqa: E402
from tlkernel import runoutcome as oc  # noqa: E402
from tlkernel.env import snapshot  # noqa: E402
from tlkernel.kinds import Kind  # noqa: E402
from tltestkit.narrow import must  # noqa: E402

DELEGATE = fake_route.delegate_dir()
CONTRACT = dl.resolve().contract
FIXTURES = sorted(fake_route.FIXTURE_DIR.glob("*.json"))
FAKE = str(Path(fake_route.__file__))


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
        argv = argv_of(self.req(thread="writer", reviewer_other_family=True, call_id="c", brief_path="b.md", schema_path="s.json",
                        writer_exec=True))
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
            a = lp.decide(must(r.stop), lp.Ctx())
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
        r = self.call(runner=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "Traceback"), thread="writer")
        assert (r.source, must(r.stop).reason) == ("synthesized", "no_answer")  # not delegate's own `crash` (needs_owner)
        assert (must(r.stop).scope, must(r.stop).permanence, must(r.stop).retry_kind) == ("machine", "transient", "none")
        assert must(r.res.stop).ref == ""

    def test_a_wrong_shape_is_a_contract_violation_and_a_call_the_engine_ended_is_a_timeout(self):
        for bad in ('{"v": 2, "status": "done"}', '{"contract": 2, "stop": null}', '{"contract": 4}', '{"contract": 4, "stop": 7}'):
            r = self.call(runner=lambda cmd, _bad=bad, **kw: subprocess.CompletedProcess(cmd, 0, _bad, ""))
            assert must(r.stop).reason == "contract_violation", bad
            assert (must(r.stop).scope, must(r.stop).permanence) == ("machine", "needs_owner")

        def hang(cmd, **kw):
            raise dl.Stopped("no worker output for 20 min")
        r = self.call(runner=hang, thread="writer")
        assert (must(r.stop).reason, must(r.stop).scope, must(r.res.stop).ref) == ("timeout", "bead", "")
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
        assert isinstance(lp.decide(must(k), lp.Ctx()), lp.Yield)
        result = delegate_wire.result_of(fake_route.stop_answer("network", "r1", partial=True))
        n, wire = must(lp.stop_of(result)), must(result.stop)
        assert (n.reason, wire.ref, wire.resumable, wire.partial, n.signal) == ("network", "r1", True, True, 0)
        j = {
            "denied": [
                {"kind": "sandbox_limit", "tool": "Bash", "input": {}},
                {"kind": "policy", "tool": "Bash", "input": {"command": "ls"}},
            ]
        }
        assert [d.kind for d in delegate_wire.denied_of(j["denied"])] == ["policy"]

    def test_a_restart_after_the_first_drop_keeps_the_thread_key(self):
        self.script_with(["network", "done"])
        st = cs.begin(self.dir / "ck", "run-1", "t-1", ("write", 1, 0, 1))
        first = self.call()
        st.note_ref(first.ref)
        what = cs.reattach(cs.load_for(self.dir / "ck", "t-1", ("write", 1, 0, 1)))  # the loop was killed here
        assert must(what)[:2] == ("resume", "fake-1")
        again = self.call(thread="writer")
        assert again.done
        assert "--resume" not in self.argv_log()[-1]


def lp_facts(reason):
    r = CONTRACT["reasons"][reason]
    return (r["scope"], r["permanence"], r["retry"])
