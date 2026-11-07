"""Task-local retries and rejected answer evidence, with two fake ready lanes."""

from dataclasses import replace
from unittest import mock

import routing_support as support
from run_support import RunBase
from test_route import CFG, lanes, why

from delegate.adapters import git
from delegate.app import env, launch
from delegate.contracts import history as hist
from delegate.contracts.routing import CallArgs, Step
from delegate.domain.holds.book import HoldBook
from delegate.domain.routing.router import Router
from tltestkit.procsim import real_proc


class RunReroute(RunBase):
    def schema(self):
        path = self.base / "schema.json"
        path.write_text('{"type":"object","required":["a"]}')
        return str(path)

    def failure(self, outcome="timeout", task="T", role="worker", ts=None):
        env.history_add(
            hist.RunRow(
                ts=env.now() - 10 if ts is None else ts,
                run_id="prior",
                task=task,
                role=role,
                lane="OPENAI_SUBSCRIPTION",
                model="gpt-6.1-sol",
                effort="high",
                done=False,
                outcome=outcome,
            )
        )

    def fake(self, d, *args):
        return {"text": "prose é" * 4000, "data": None, "ref": d["lane"], "tokens": {"in": 10, "cached": 2, "out": 3}, "cost": 0.25}

    def rows(self):
        return [r for r in env.history_store().rows() if isinstance(r, hist.RunRow)]

    @real_proc("delegate: a worker, git or CLI process")
    def test_schema_rejection_keeps_utf8_prefix_and_problem(self):
        with support.fleet_patches(lanes()), mock.patch.object(launch, "launch_worker", side_effect=self.fake):
            _, result = self.run_it("--schema", self.schema(), "--only-family", "openai")
        row = self.rows()[-1]
        expected = ("prose é" * 4000).encode()[: 20 * 1024].decode("utf-8", errors="ignore")
        assert row.raw_answer == expected
        assert "not JSON" in (row.schema_problem or "")
        assert (row.schema_problem or "") in (row.say or "")
        assert why(result) == "schema_invalid"

    @real_proc("delegate: a worker, git or CLI process")
    def test_fresh_task_avoids_recent_timeout_and_schema_invalid(self):
        for outcome in ("timeout", "schema_invalid"):
            with self.subTest(outcome=outcome):
                self.failure(outcome)
                with support.fleet_patches(lanes()):
                    _, result = self.run_it("--task", "T")
                assert result["lane"] == "CLAUDE_SUBSCRIPTION"

    @real_proc("delegate: a worker, git or CLI process")
    def test_avoidance_is_task_role_and_time_bounded(self):
        for override in ({"task": "other"}, {"role": "reviewer"}, {"ts": env.now() - 86400}):
            self.failure(**override)
        with support.fleet_patches(lanes()):
            _, result = self.run_it("--task", "T")
        assert result["lane"] == "OPENAI_SUBSCRIPTION"

    @real_proc("delegate: a worker, git or CLI process")
    def test_no_task_and_resume_keep_the_original_choice(self):
        self.failure()
        with support.fleet_patches(lanes()):
            _, result = self.run_it("--task", "another")
            _, resumed = self.run_it("--task", "T", "--resume", result["ref"])
            _, plain = self.run_it()
        assert (resumed["lane"], plain["lane"]) == ("OPENAI_SUBSCRIPTION",) * 2

    @real_proc("delegate: a worker, git or CLI process")
    def test_pinned_family_reuses_failed_pair_with_warning(self):
        self.failure()
        with support.fleet_patches(lanes()):
            _, result = self.run_it("--task", "T", "--only-family", "openai")
        assert result["lane"] == "OPENAI_SUBSCRIPTION"
        assert "no other" in result["warning"]
        assert "openai" in result["warning"]

    @real_proc("delegate: a worker, git or CLI process")
    def test_busy_alternative_explains_reuse(self):
        self.failure()
        ls = lanes()
        ls["CLAUDE_SUBSCRIPTION"] = ls["CLAUDE_SUBSCRIPTION"].with_busy(env.now() + 90, 4, 4)
        with support.fleet_patches(ls):
            _, result = self.run_it("--task", "T")
        assert result["lane"] == "OPENAI_SUBSCRIPTION"
        assert "no other" in result["warning"]
        assert "rejected, out" in result["warning"]

    @real_proc("delegate: a worker, git or CLI process")
    def test_same_lane_can_use_a_different_model_within_pinned_family(self):
        routing = env.typed_routing(CFG)
        steps = tuple(Step(model=m, effort="high", on="openai") for m in ("gpt-6.1-sol", "gpt-6-luna"))
        role = replace(routing.roles["worker"], steps=steps)
        routing = replace(routing, roles=dict(routing.roles, worker=role))
        pick = Router(routing, HoldBook({}), {}, env.now()).route(
            "worker", CallArgs(only_family=("openai",)), lanes(), avoid=frozenset({("OPENAI_SUBSCRIPTION", "gpt-6.1-sol")})
        )
        assert (pick.as_dict()["lane"], pick.as_dict()["model"]) == ("OPENAI_SUBSCRIPTION", "gpt-6-luna")

    @real_proc("delegate: a worker, git or CLI process")
    def test_second_lane_can_succeed_without_a_third_attempt(self):
        def worker(d, *args):
            res = self.fake(d, *args)
            if d["lane"] == "CLAUDE_SUBSCRIPTION":
                res.update(data={"a": 1}, text='{"a":1}')
            return res

        with support.fleet_patches(lanes()), mock.patch.object(launch, "launch_worker", side_effect=worker) as launched:
            _, result = self.run_it("--schema", self.schema())
        assert result["stop"] is None
        assert launched.call_count == 3
        assert [r.done for r in self.rows()] == [False, True]

    @real_proc("delegate: a worker, git or CLI process")
    def test_schema_reask_failure_launches_one_fresh_different_lane(self):
        with support.fleet_patches(lanes()), mock.patch.object(launch, "launch_worker", side_effect=self.fake) as worker:
            _, result = self.run_it("--task", "T", "--schema", self.schema())
        rows = self.rows()
        assert [r.lane for r in rows] == ["OPENAI_SUBSCRIPTION", "CLAUDE_SUBSCRIPTION"]
        assert [r.outcome for r in rows] == ["schema_invalid"] * 2
        assert [(r.tokens or {})["in"] for r in rows] == [20, 20]
        assert sum(r.cost for r in rows) == 1.0
        assert worker.call_count == 4
        assert worker.call_args_list[2].args[2].resume is None
        assert why(result) == "schema_invalid"

    @real_proc("delegate: a worker, git or CLI process")
    def test_reroute_reports_first_attempt_head_change(self):
        state = {"head": "111111111", "branch": "main"}

        def worker(d, *args):
            res = self.fake(d, *args)
            if d["lane"] == "OPENAI_SUBSCRIPTION":
                state["head"] = "222222222"
            else:
                res.update(data={"a": 1}, text='{"a":1}')
            return res

        with (
            support.fleet_patches(lanes()),
            mock.patch.object(git, "state", side_effect=lambda cwd: dict(state)),
            mock.patch.object(launch, "launch_worker", side_effect=worker) as launched,
        ):
            _, result = self.run_it("--schema", self.schema())
        assert result["stop"] is None
        assert launched.call_count == 3
        assert [r.done for r in self.rows()] == [False, True]
        assert result["git_violation"] == ["HEAD 111111111 -> 222222222"]

    @real_proc("delegate: a worker, git or CLI process")
    def test_schema_single_lane_says_why_it_did_not_reroute(self):
        with support.fleet_patches(lanes()), mock.patch.object(launch, "launch_worker", side_effect=self.fake) as worker:
            _, result = self.run_it("--schema", self.schema(), "--only-family", "openai")
        assert worker.call_count == 2
        assert "no other" in result["say"]
        assert "openai" in result["say"]
        assert len(self.rows()) == 1
