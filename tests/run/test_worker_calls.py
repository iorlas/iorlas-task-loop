"""tl-ixc: the engine's worker call under the RetryPlan: its rows, a reviewer's wall-time budget (Overrun), a write that timed out or
ended by SIGTERM (a RetryDecision with the timeout and the exit), and the `exit` in CallEnd. The policy's own tables are in
test_lane_policy; the live file and the stop are in test_write_idle and test_procs."""

import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support import engine_case as te
from support.spawn import port_git, real_spawner
from support.who import who

from taskloop.adapters import delegate as dl
from taskloop.adapters.delegate import Stopped
from taskloop.app.run import engine
from taskloop.app.slots import config as wslots_config
from taskloop.domain.lanes import retry
from tlkernel.env import snapshot
from tlkernel.ids import BeadId
from tlkernel.paths import RunFiles
from tltestkit import fake_route
from tltestkit.logs import records


def napper(nap):
    """`time` as lane_acts sees it, with a sleep that only counts (the real one is patched nowhere else: threads sleep too)."""
    return SimpleNamespace(sleep=nap, strftime=time.strftime, localtime=time.localtime, time=time.time)


class RetryRows(Case):
    def test_remaining_kinds_and_every_limit_is_one_row(self):
        got = {r.kind: (r.limit, r.then) for r in retry.ROWS}
        assert got == {
                "invalid_output": (1, "fault"),
                "denied_read": (1, "fault"),
                "denied_secret": (1, "fault"),
                "worker_failed": (1, "ask"),
            }



class Calls(te.EngineTest):
    def go(self, script):
        c = wslots_config.load_cfg(str(self.wt), port_git())
        nap = mock.Mock()
        with te.delegate_stack(script), mock.patch("taskloop.app.workers.lane_acts.time", napper(nap)):
            self.eng = engine.Engine(
                BeadId("t-1"), str(self.wt), c, store=self.store, env=snapshot(), spawner=real_spawner(), git=port_git(), who=who()
            )
            rc = self.eng.run()
        return rc, nap

    def test_a_reviewer_that_never_answers_is_stopped_at_its_budget_and_the_next_rung_reviews(self):
        class Script(fake_route.Script):
            def reply(self, role, *a, **kw):
                if role == "reviewer" and not getattr(self, "hung", False):
                    self.hung = True
                    self.calls.append((role, None, None))
                    self.stop = {"kind": "wall", "why": "wall limit", "alive": []}
                    raise Stopped("wall limit")
                return super().reply(role, *a, **kw)

        script = Script({"plan": [te.PLAN], "write": [te.WRITE], "review": [te.CLEAN]})
        rc, _ = self.go(script)
        assert rc == 0
        over = records(self.eng, "overrun")
        assert len(over) == 1
        assert over[0]["stage"] == "review"
        assert over[0]["budget_s"] == 600.0  # the default: review_budget_min 10
        assert script.nodes.count("review") == 1  # the hung call never answered; the next rung did (the loop went on)

    def test_a_write_that_timed_out_gets_a_retry_decision_with_the_timeout_and_the_exit(self):
        class Script(fake_route.Script):
            def reply(self, role, *a, **kw):
                if role == "worker" and not getattr(self, "timed", False):
                    self.timed = True
                    self.calls.append((role, None, None))
                    return fake_route.answer(self.c, "worker_failed", "r1", exit_code=-15)
                return super().reply(role, *a, **kw)

        script = Script({"plan": [te.PLAN], "write": [te.WRITE], "review": [te.CLEAN]})
        self.go(script)
        dec = records(self.eng, "retry_decision")
        assert dec
        assert dec[0]["plan"] == "worker_failed"
        assert dec[0]["exit"] == -15
        assert dec[0]["action"] == "ask"

    def test_call_end_carries_the_exit_of_the_worker(self):
        script = fake_route.Script({"plan": [te.PLAN], "write": [te.full(te.WRITE, "w1", exit_code=0)], "review": [te.CLEAN]})
        self.go(script)
        ends = [r for r in records(self.eng, "call_end") if r.get("exit") is not None]
        assert [r["exit"] for r in ends] == [0]  # the write's; the planner and the reviewer ran no worker

    def test_call_end_names_where_its_cost_came_from(self):
        script = fake_route.Script({"plan": [te.PLAN], "write": [te.full(te.WRITE, "w1", exit_code=0)], "review": [te.CLEAN]})
        self.go(script)
        ends = records(self.eng, "call_end")
        assert ends
        answered = [r for r in ends if r["status"] != "stopped"]  # an interrupted call has no answer, so no source
        assert answered
        assert {r["cost_source"] for r in answered} - {"harness", "free", "unknown"} == set()

    def write_call_end(self, cost, source):
        usage = {"tokens": {"in_fresh": 200, "cache_read": 800, "cache_write": 70, "out": 50}, "cost": cost or 0.0, "cost_usd": cost,
                 "cost_source": source, "secs": 1, "turns": 1, "context_k": None, "answer_bytes": 0, "ref": "w1"}
        write = te.full(te.WRITE, "w1", exit_code=0, cost=cost or 0.0, usage=usage)
        self.go(fake_route.Script({"plan": [te.PLAN], "write": [write], "review": [te.CLEAN]}))
        return next(r for r in records(self.eng, "call_end") if r.get("exit") is not None)

    def test_call_end_keeps_cache_write_and_an_unknown_cost_is_null_not_zero(self):
        end = self.write_call_end(None, "unknown")
        assert (end["cost"], end["cost_source"], end["tokens"]["cache_write"]) == (None, "unknown", 70)

    def test_call_end_keeps_a_cost_the_harness_gave(self):
        end = self.write_call_end(0.5, "harness")
        assert (end["cost"], end["cost_source"]) == (0.5, "harness")

    def test_every_worker_call_is_told_its_run_through_the_six_names(self):
        seen = []
        real = dl.call

        def spy(*a, **kw):
            if not a[1].title.endswith("reflect"):  # the close reflection is no worker call
                seen.append(kw["env"])
            return real(*a, **kw)

        script = fake_route.Script({"plan": [te.PLAN], "write": [te.WRITE], "review": [te.CLEAN]})
        with mock.patch.object(dl, "call", spy):
            self.go(script)
        e = self.eng
        assert seen
        for env in seen:
            assert env["TL_RUN_ID"] == e.run_id
            assert env["TL_RUN_DIR"] == str(e.run_dir)
            assert env["TL_WORKTREE"] == str(e.wt)
            assert env["TL_ATTEMPT"] == "1"
            assert env["TL_BRANCH"]
            art = Path(env["TL_ARTIFACT_DIR"])
            assert art.parent.parent == RunFiles(e.run_dir).artifacts(1)
            assert art.name == "attempt-1"
            assert art.is_dir()


for _name in dir(te.EngineTest):  # the engine fixture only
    if _name.startswith("test_") and _name not in Calls.__dict__:
        setattr(Calls, _name, None)
