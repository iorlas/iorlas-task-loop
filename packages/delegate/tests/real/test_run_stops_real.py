"""`route.py run` stops: network drops, canary and bench, schema re-ask, the answer's stop facts and contract."""

import io
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest import mock

import hermetic  # noqa: F401  (a home of its own for every test)
import pytest
import routing_support as support
from any_agent import reset_parse, watch
from any_agent.classify import classify
from any_agent.supervisor import LaneGoneWatcher
from run_support import RunBase, short_limits
from test_route import CFG, at, need, no_reader, obj, route, why

from delegate.app import answer, env, gaps, launch, net, usage
from delegate.app import decide as dec
from delegate.contracts import history as hist
from delegate.contracts import stops
from delegate.contracts.routing import Settings
from delegate.contracts.state import StateDoc
from delegate.domain.health import ledger as health_ledger
from delegate.domain.lanes.lane import Lane
from tltestkit.fake_worker import Err, Exit, Jump
from tltestkit.procsim import real_proc

THREAD = '{"type":"thread.started","thread_id":"thread-123"}'
ANSWER = '{"type":"item.completed","item":{"id":"i9","type":"agent_message","text":"{\\"findings\\": []}"}}'
TURN_DONE = '{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":40,"output_tokens":7}}'
LIMIT_S = 60  # each test makes several full runs, every run spawns a fake CLI and git


class RunStops(RunBase):
    @real_proc("delegate: a worker, git or CLI process")
    def test_unattended_never_answers_agent_ask_user_or_needs_input(self):
        [support.put_out(n, env.now() + 3600) for n in ("OPENAI_SUBSCRIPTION", "CLAUDE_SUBSCRIPTION")]
        code, r = self.run_it(role="planner")
        assert (code, why(r)) == (0, "no_lane")
        assert "ask_user" not in r
        assert "needs_input" not in r
        support.clear_out()
        self.codex_out()
        _, r = self.run_it(role="planner")  # no Agent tool here: the subscription runs claude -p (Sonnet; Opus never plans in the loop)
        assert r.get("agent_model") is None
        assert (r["stop"], r["lane"]) == (None, "CLAUDE_SUBSCRIPTION")

    @real_proc("delegate: a worker, git or CLI process")
    def test_every_lane_full_stops_with_a_retry_after_in_one_to_two_minutes(self):
        for i in range(4):
            self.lease(f"o{i}", "OPENAI_SUBSCRIPTION")
            self.lease(f"c{i}", "CLAUDE_SUBSCRIPTION")
        before = time.time()
        _, r = self.run_it()
        assert why(r) == "busy"
        assert before + 55 <= at(r) <= time.time() + 125, at(r)

    @real_proc("delegate: a worker, git or CLI process")
    def test_the_lease_is_released_and_a_history_line_is_written(self):
        _, r = self.run_it("--task", "T-9")
        assert env.load_state().leases == {}
        line = json.loads(env.history_path().read_text().splitlines()[-1])
        assert (line["run_id"], line["task"], line["lane"], line["done"]) == (r["run_id"], "T-9", "OPENAI_SUBSCRIPTION", True)
        assert line["tokens"] == {"in": 100, "cached": 40, "out": 7}
        assert "brief" not in json.dumps(line)
        assert line["overlap"] == []

    @real_proc("delegate: the answer-done stop is judged on a run over a real git work tree")
    def test_answer_done_process_alive_is_done_after_the_grace(self):
        """delegate-itn: turn.completed after the final agent message, then the process never exits: done after the grace,
        whole tree stopped."""
        self.enterContext(short_limits("codex", grace_s=1))
        started = self.play(THREAD, ANSWER, TURN_DONE)
        _, r = self.run_it(timeout=0)
        assert (r["stop"], r["text"], r["lane"]) == (None, '{"findings": []}', "OPENAI_SUBSCRIPTION")
        assert r["warnings"] == ["answer_done_process_alive"]
        assert r["stop"] is None
        assert json.loads(env.history_path().read_text().splitlines()[-1])["warnings"] == ["answer_done_process_alive"]
        assert "OPENAI_SUBSCRIPTION" not in env.load_state().out
        assert [p.stopped for p in started] == [True]  # the whole tree was stopped

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_later_event_resets_the_answer_grace(self):
        self.real_clock()
        self.fast_clock(grace=0.5, stall=900)
        script = self.base / "bin" / "codex"
        script.write_text(self.FAKE_CODEX.replace("sleep 0.5", "sleep 0.2"))
        _, r = self.run_it(mode="progress_then_work", role="reviewer", timeout=1)
        assert why(r) == "timeout"
        assert [(a["kind"], a["outcome"]) for a in r["attempts"]] == [("first", "timeout"), ("worker_retry", "timeout")]
        assert len(self.args_seen().splitlines()) == 2
        assert "answer_done_process_alive" not in r.get("warnings", [])

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_stalled_model_request_is_stopped_and_the_stream_tail_is_logged(self):
        self.fast_clock()
        _, r = self.run_it(mode="stall", timeout=20)
        assert (why(r), r["stop"]["scope"]) == ("hung", "model")
        row = json.loads(env.history_path().read_text().splitlines()[-1])
        assert any('"command_execution"' in x for x in row["stream_tail"])
        self.pid_dead()

    @real_proc("delegate: a worker, git or CLI process")
    def test_sigterm_on_route_py_stops_the_worker_too(self):
        penv = dict(os.environ, FAKE_MODE="hang", PATH=str(self.base / "bin") + os.pathsep + os.environ["PATH"])
        p = subprocess.Popen(
            [sys.executable, str(route.__file__), "run", "worker", "--cwd", self.repo, "--unattended"],
            env=penv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert p.stdin is not None
        assert p.stdout is not None
        assert p.stderr is not None
        p.stdin.write(b"do it")
        p.stdin.close()
        for _ in range(300):
            if Path(os.environ["FAKE_PIDFILE"]).exists() and Path(os.environ["FAKE_PIDFILE"]).read_text().strip():
                break
            if p.poll() is not None:
                pytest.fail(p.stdout.read().decode() + p.stderr.read().decode())
            time.sleep(0.1)
        pid = int(Path(os.environ["FAKE_PIDFILE"]).read_text())
        wp = [v.worker_pid for v in env.load_state().leases.values()]
        assert wp and wp[0], "the lease names the worker before it does any work"
        p.send_signal(signal.SIGTERM)
        p.wait(timeout=15)
        assert f"delegate: worker pid={wp[0]} pgid={wp[0]}" in p.stderr.read().decode()
        p.stdout.close()
        p.stderr.close()
        time.sleep(0.3)
        with pytest.raises(OSError):
            os.kill(pid, 0)
        assert env.load_state().leases == {}

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_state_lock_timeout_is_a_stop_with_a_retry_time(self):
        with mock.patch.object(dec, "decision", side_effect=TimeoutError("state is locked")):
            real, sys.stdout = sys.stdout, io.StringIO()
            try:
                route.main(["run", "worker", "--unattended"])
                out = json.loads(sys.stdout.getvalue())
            finally:
                sys.stdout = real
        assert (why(out), out["stop"]["permanence"]) == ("lock", "transient")
        assert at(out) > time.time()

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_resume_with_no_rollout_subtracts_the_cumulative_the_history_kept(self):
        self.run_it()  # first call: the thread total is 100/40/7, recorded in history
        env.history_add(
            hist.RunRow(
                ts=env.now(),
                run_id="kept",
                role="worker",
                lane="OPENAI_SUBSCRIPTION",
                model="m",
                effort="high",
                done=True,
                ref="thread-123",
                cumulative={"in": 60, "cached": 30, "out": 4},
            )
        )
        _, r = self.run_it("--resume", "thread-123")
        assert r["tokens"] == {"in": 40, "cached": 10, "out": 3}
        assert (r["usage"]["tokens"]["in_fresh"], r["usage"]["tokens"]["cache_read"], r["usage"]["tokens"]["out"]) == (30, 10, 3)

    @real_proc("delegate: a worker, git or CLI process")
    def test_every_answer_carries_the_stop_facts(self):
        r: dict = {}
        cases = {
            "early_error": ("vendor_blip", "lane", "transient"),
            "bad_request": ("bad_request", "caller", "needs_owner"),
            "late_error": ("network", "machine", "transient"),
            "secret": ("secrets", "bead", "needs_owner"),
            "logout": ("logged_out", "lane", "needs_owner"),
            "net": ("network", "machine", "transient"),
            "ok": None,
        }
        for mode, want in cases.items():
            _, r = self.run_it(mode=mode)
            assert r["contract"] == 4
            assert (tuple(r["stop"][k] for k in ("reason", "scope", "permanence")) if r["stop"] else None) == want, mode
            for gone in ("v", "status", "reason", "next", "retry_after"):
                assert gone not in r, mode
            if want and want[2] == "transient":
                assert at(r) > time.time()
        assert r["context"]["instructions"] == []
        assert "PATH" in r["context"]["env_keys"]
        assert "CLAUDE_FOO" not in r["context"]["env_keys"]

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_drop_before_the_first_event_relaunches_once(self):
        _, r = self.run_it(mode="drop_early")
        assert (r["stop"], r["text"]) == (None, "second try")
        assert self.launches() == 2

    @real_proc("delegate: a worker, git or CLI process")
    def test_two_drops_before_the_first_event_stop_with_network_and_launch_no_third_time(self):
        _, r = self.run_it(mode="drop_early_twice")
        assert (why(r), r["stop"]["scope"]) == ("network", "machine")
        assert self.launches() == 2
        assert not r["stop"]["resumable"]
        assert not r["stop"]["partial"]
        assert "OPENAI_SUBSCRIPTION" not in env.load_state().out  # the network is not the lane's fault

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_drop_with_the_net_still_down_is_not_relaunched_in_the_call(self):
        with mock.patch.object(
            net, "net_probe", lambda hosts=None: {"up": False, "ip_up": False, "why": "offline", "ms": 1, "hosts": {}, "at": time.time()}
        ):
            _, r = self.run_it(mode="drop_early")
        assert (why(r), r["stop"]["scope"]) == ("network", "machine")
        assert self.launches() == 1  # the in-call wait expired

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_dropped_stream_keeps_the_ref_in_the_answer_the_stop_and_the_refs_table(self):
        _, r = self.run_it(mode="late_error")
        assert (r["ref"], r["stop"]["ref"]) == ("thread-123", "thread-123")
        assert "thread-123" in env.load_state().refs  # a later --resume finds the lane that made it
        assert (why(r), r["stop"]["resumable"], r["data"]) == ("network", True, None)  # DELRESUME: ref present, resumable, no data
        row = json.loads(Path(env.history_path()).read_text().splitlines()[-1])
        assert (row["outcome"], row["ref"]) == ("network", "thread-123")
        _, r = self.run_it("--resume", "thread-123")  # the retry with that ref goes through
        assert (r["stop"], r["ref"]) == (None, "thread-123")

    @real_proc("delegate: a worker, git or CLI process")
    def test_every_stop_that_has_a_ref_carries_it(self):
        _, r = self.run_it(mode="limit")
        assert (why(r), r["ref"]) == ("rate_limited", "thread-123")
        assert r["stop"]["ref"] == "thread-123"

    @real_proc("delegate: a worker, git or CLI process")
    def test_network_stops_never_bench_the_pair(self):
        for _ in range(5):
            _, r = self.run_it(mode="late_error", unattended=True)
            assert why(r) == "network"
        led = health_ledger.HealthLedger(env.typed_routing(CFG).settings.breaker)
        st = led.fold(env.history_store().rows())
        assert led.view(st, "OPENAI_SUBSCRIPTION", r["model"], time.time()).usable
        assert {k: v for k, v in st.keys.items() if '|' in k} == {}
        _, r = self.run_it()
        assert r["stop"] is None

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_stop_with_nothing_to_wait_for_is_for_the_owner(self):
        assert obj(answer.result("no_lane"))["stop"]["permanence"] == "needs_owner"
        assert obj(answer.result("no_lane", retry_after=5))["stop"]["permanence"] == "transient"
        assert answer.result()["stop"] is None

    @real_proc("delegate: a worker, git or CLI process")
    def test_schema_is_reasked_once_in_the_same_thread(self):
        schema = self.base / "s.json"
        schema.write_text('{"type": "object", "required": ["a"], "properties": {"a": {"type": "integer"}}}')
        _, r = self.run_it("--schema", str(schema), mode="badjson")
        assert (r["stop"], r["data"]) == (None, {"a": 1})
        assert "resume" in self.args_seen().splitlines()[-1]
        assert r["tokens"]["in"] == 200
        _, r = self.run_it("--schema", str(schema), "--only-family", "openai", mode="badjson_always")
        assert (why(r), r["stop"]["permanence"]) == ("schema_invalid", "transient")
        assert "$.a is missing" in r["say"]

    @real_proc("delegate: a worker, git or CLI process")
    def test_contract_json_names_every_reason_and_lane(self):
        real, sys.stdout = sys.stdout, io.StringIO()
        try:
            route.main(["contract", "--json"])
            out = sys.stdout.getvalue()
        finally:
            sys.stdout = real
        assert out.count("\n") == 1
        c = obj(json.loads(out))
        assert c["contract"] == 4
        assert set(obj(c["reasons"])) == set(obj(stops.CONTRACT["reasons"]))
        for row in c["reasons"].values():
            assert {"scope", "permanence", "retry", "health", "wording"} <= set(row)

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_request_fault_leaves_the_lane_in_state_json_alone(self):
        before = env.load_state().out
        self.run_it(mode="bad_request")
        assert env.load_state().out == before

    @real_proc("delegate: a worker, git or CLI process")
    def test_handshake_declares_contract_4_and_the_reason_table(self):
        real, sys.stdout = sys.stdout, io.StringIO()
        try:
            route.main(["contract", "--json"])
            c = obj(json.loads(sys.stdout.getvalue()))
        finally:
            sys.stdout = real
        assert c["contract"] == 4
        assert set(c) == {"contract", "capabilities", "reasons", "run_args"}
        assert "--call-id" in c["run_args"]
        assert "--host" not in c["run_args"]
        assert set(obj(c["reasons"])) == set(obj(stops.CONTRACT["reasons"]))

    @real_proc("delegate: a worker, git or CLI process")
    def test_history_rotates_by_age_once_it_is_big(self):
        p = env.history_path()
        old = json.dumps({"ts": time.time() - 20 * 86400, "run_id": "old", "pad": "x" * 2000})
        p.write_text((old + "\n") * 600)  # about 1.2 MB, all older than 14 days
        self.run_it()
        runs = [json.loads(x)["run_id"] for x in p.read_text().splitlines()]
        assert "old" not in runs
        assert len(runs) == 1

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_gap_over_1800s_is_written_to_history_through_the_watchdog_and_the_fold_ignores_it(self):
        t = [0.0]
        d = {"lane": "OPENAI_SUBSCRIPTION", "model": "gpt-6.1-sol"}
        dog = watch.Watchdog(120, 3600, clock=lambda: t[0])
        for tick in (5, 1805, 4005):  # gaps of 1800 s (not logged) and 2200 s (logged)
            t[0] = tick
            dog.touch()
        assert not dog.poll()
        gaps.flush(dog, env.history_add, d["lane"], d["model"], True)
        rows = env.history_store().rows()
        got = [r for r in rows if isinstance(r, hist.GapRow)]
        assert len(got) == len(rows)
        assert [(type(r).__name__, r.lane, r.model, r.gap_s, r.finished) for r in got] == [
            ("GapRow", "OPENAI_SUBSCRIPTION", "gpt-6.1-sol", 2200.0, True)
        ]
        assert health_ledger.HealthLedger(env.typed_routing(CFG).settings.breaker).fold(rows).keys == {}
        gaps.flush(dog, obj(None), d["lane"], d["model"], True)  # never raises

    @real_proc("delegate: stderr chatter keeps a run alive on a real git work tree")
    def test_any_stream_line_counts_as_activity_even_on_stderr(self):
        self.play(THREAD, *[s for _ in range(8) for s in (Jump(0.4), Err("thinking"))], Exit(0))  # stderr every 0.4 s for 3 s
        with short_limits("codex", silence_s=1):
            _, r = self.run_it(timeout=0)
        assert r["stop"] is None

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_benched_pair_is_skipped_and_the_next_step_runs(self):
        self.hist(self.failed_rows(3, 60))
        _, r = self.run_it(unattended=True)
        assert r.get("model") != "gpt-6.1-sol"
        assert r.get("lane") != "OPENAI_SUBSCRIPTION"

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_pair_whose_bench_ended_gets_one_canary_before_the_real_call(self):
        self.hist(self.failed_rows(3, 1500))  # benched 15 min from the third failure: over 8 min ago
        _, r = self.run_it()
        assert (r["stop"], r["lane"]) == (None, "OPENAI_SUBSCRIPTION")
        calls = self.args_seen().strip().splitlines()
        assert len(calls) == 2
        assert Path(os.environ["FAKE_ARGS"] + ".brief").read_text().strip().splitlines()[-1] == "the brief"
        rows = [json.loads(x) for x in env.history_path().read_text().splitlines()]
        assert [x["kind"] for x in rows[-2:]] == ["canary", "run"]
        _, r = self.run_it()  # the canary passed: the ladder is reset, the next call has none
        assert len(self.args_seen().strip().splitlines()) == 3

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_failed_canary_is_the_answer_and_starts_the_next_rung(self):
        self.hist(self.failed_rows(3, 1500))
        _, r = self.run_it(mode="early_error")
        assert why(r) == "vendor_blip"
        assert r["say"].startswith("canary failed: "), r["say"]
        assert len(self.args_seen().strip().splitlines()) == 1  # the real brief was never sent
        led = health_ledger.HealthLedger(env.typed_routing(CFG).settings.breaker)
        v = led.view(led.fold(env.history_store().rows()), "OPENAI_SUBSCRIPTION", "gpt-6.1-sol", env.now() + 1)
        assert (v.state, v.rung) == ("broken", 2)
        assert need(v.until) - env.now() == pytest.approx(30 * 60, abs=5)

    @real_proc("delegate: a worker, git or CLI process")
    def test_bad_request_never_benches_the_pair(self):
        for _ in range(4):
            _, r = self.run_it(mode="bad_request")
            assert (why(r), r["stop"]["permanence"]) == ("bad_request", "needs_owner")
        _, r = self.run_it()
        assert (r["stop"], r["lane"], r["model"]) == (None, "OPENAI_SUBSCRIPTION", "gpt-6.1-sol")

    @real_proc("delegate: a worker, git or CLI process")
    def test_workers_of_a_lane_marked_out_by_someone_else_are_stopped_within_the_poll_interval(self):
        started = time.time()
        w = LaneGoneWatcher(launch.lane_gone_check("OPENAI_SUBSCRIPTION", started), every=0)
        assert w.poll() is None
        launch.settler().mark_out("OPENAI_SUBSCRIPTION", env.now() + 3600, "limit refusal: usage limit", env.now())
        stop = need(w.poll())
        assert stop.why == "limit"
        for reason, want in (
            ("logged_out", "logged_out"),
            ("credit", "credit_exhausted"),
        ):  # the mark's reason is kept, not collapsed to a limit
            launch.settler().mark_out("OPENAI_SUBSCRIPTION", env.now() + 3600, "other words", env.now(), reason)
            stop = need(w.poll())
            assert stop.why == reason
            assert need(classify(None, structured={"watchdog": stop.why, "msg": stop.msg})).reason == want
        late = LaneGoneWatcher(
            launch.lane_gone_check("OPENAI_SUBSCRIPTION", time.time() + 5), every=0
        )  # a worker that started after the mark is not affected
        assert late.poll() is None

    @real_proc("delegate: a worker, git or CLI process")
    def test_schema_is_passed_and_the_answer_parsed(self):
        schema = self.base / "s.json"
        schema.write_text('{"type": "object"}')
        _, r = self.run_it("--schema", str(schema), mode="json")
        assert (r["stop"], r["data"]) == (None, {"a": 1})
        assert "--output-schema" in self.args_seen()

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_limit_refusal_lasts_until_the_known_reset(self):
        soon = env.now() + 500

        def reading(lane: Lane, S: Settings, st: StateDoc, t: float, ai_usage: object = None) -> None:
            if lane.family == "openai":
                lane.five, lane.five_reset, lane.week, lane.week_reset = 50, soon, 10, soon + 99999

        usage.READERS["codex_app_server"] = reading
        self.run_it(mode="limit")
        assert env.load_state().out["OPENAI_SUBSCRIPTION"].until == pytest.approx(soon, abs=1)
        when, source, _ = reset_parse.limit_until("You've hit your usage limit. ... or try again at 5:50 AM.", env.now(), {})
        assert time.strftime("%H:%M", time.localtime(when)) == "05:50"
        assert env.now() < when <= env.now() + 86400
        assert source == "vendor"
        when, source, _ = reset_parse.limit_until("the batch run is queued behind a rate limit", env.now(), {})
        assert (source, round(when - env.now())) == ("guess", 900)  # nobody said when: refusal time + 15 min

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_reading_with_room_after_the_refusal_clears_the_out(self):
        support.put_out("OPENAI_SUBSCRIPTION", env.now() + 5 * 86400, "limit refusal: x", at=env.now() - 60)

        def reading(lane: Lane, S: Settings, st: StateDoc, t: float, ai_usage: object = None) -> None:
            lane.five, lane.week, lane.read_at = 0, 0, t

        usage.READERS["codex_app_server"] = reading
        _, r = self.run_it()
        assert (r["stop"], r["lane"]) == (None, "OPENAI_SUBSCRIPTION")
        assert "OPENAI_SUBSCRIPTION" not in env.load_state().out

    @real_proc("delegate: a worker, git or CLI process")
    def test_the_model_saying_rate_limit_is_not_a_limit_refusal(self):
        usage.READERS["codex_app_server"] = no_reader
        _, r = self.run_it(mode="saylimit")
        assert "OPENAI_SUBSCRIPTION" not in env.load_state().out
        assert why(r) != "rate_limited"
