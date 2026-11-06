"""`route.py run`: leases and slots, who runs unattended, history and status, limits and resume."""

import dataclasses
import io
import json
import os
import subprocess as sp
import sys
import time
from pathlib import Path
from unittest import mock

import pytest
from delegate.adapters.harness import opencode_sandbox as box
from delegate.app import env, status, usage
from delegate.app.fleet import Fleet
from delegate.contracts.routing import Settings
from delegate.contracts.state import StateDoc, UsageCache
from delegate.domain.lanes import leases
from delegate.domain.lanes.lane import Lane
from stream_proc import proc_start
from support.procsim import real_proc

import hermetic  # noqa: F401  (a home of its own for every test)
import routing_support as support
from run_support import RunBase
from test_route import at, obj, route, why


class RunCommand(RunBase):
    @real_proc("delegate: a worker, git or CLI process")
    def test_no_timeout_unless_the_caller_passes_one(self):
        code, r = self.run_it(timeout=None)
        assert (code, r["stop"]) == (0, None)

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_codex_run_reads_the_codex_usage_before_the_launch_only(self):
        """No second read after the run: the codex app-server spawn cost 1-2 s per run (delegate-2ys)."""
        calls: list[int] = []

        def counting(lane: Lane, S: Settings, st: StateDoc, t: float, ai_usage: object = None) -> None:
            calls.append(1)

        usage.READERS["codex_app_server"] = counting
        self.run_it()
        after_run = len(calls)
        calls.clear()
        route.main(["next", "worker"])
        assert after_run == len(calls)

    @real_proc("delegate: a worker, git or CLI process")
    def test_unattended_keeps_the_orchestrator_reserve(self):
        support.put_out("OPENAI_SUBSCRIPTION", env.now() + 3600)
        f = Path(self.tmp.name) / ".claude" / "state" / "max-limits.json"
        d = json.loads(f.read_text())
        d["rate_limits"]["seven_day"]["used_percentage"] = 93  # above the 90% weekly reserve
        f.write_text(json.dumps(d))
        _, r = self.run_it()
        assert r["stop"] is None  # the relaxed pass (ceiling 95) may still use it
        d["rate_limits"]["seven_day"]["used_percentage"] = 97
        f.write_text(json.dumps(d))
        _, r = self.run_it()
        assert why(r) == "no_lane"

    @real_proc("delegate: a worker, git or CLI process")
    def test_interactive_session_gets_the_agent_step_and_the_consent_question(self):
        self.codex_out()  # Codex plans first, Claude only when it is down
        _, r = self.run_it(role="planner", unattended=False)
        assert (r["stop"], r["lane"], r["agent_model"]) == (None, "CLAUDE_SUBSCRIPTION", "sonnet")
        assert "coordinator" in r["brief_prefix"]
        [support.put_out(n, env.now() + 3600) for n in ("OPENAI_SUBSCRIPTION", "CLAUDE_SUBSCRIPTION")]
        _, r = self.run_it(role="planner", unattended=False)
        assert why(r) == "no_lane"
        assert "ask_user" in r

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_busy_first_choice_waits_unless_told_not_to(self):
        for i in range(4):
            self.lease(f"r{i}", "OPENAI_SUBSCRIPTION")  # Codex, the worker's first choice, has 4 of 4 slots taken
        before = time.time()
        _, r = self.run_it()
        assert (why(r), r["stop"]["permanence"], r["lane"]) == ("busy", "transient", "OPENAI_SUBSCRIPTION")
        assert before + 50 < at(r) < time.time() + 130  # anchored before the run: the margin does not shrink with the load

    @real_proc("delegate: a worker, git or CLI process")
    def test_the_first_choice_is_rung_0_and_no_fallback(self):
        _, r = self.run_it()
        assert (r["lane"], r["rung"], r["fallback"], r["fallback_reason"], r["first_lane"]) == ("OPENAI_SUBSCRIPTION", 0, False, None, None)
        _, r = self.run_it("--resume", "thread-123")
        assert (r["rung"], r["fallback"]) == (0, False)
        self.codex_out()
        _, r = self.run_it()
        assert (r["lane"], r["fallback"], r["fallback_reason"]) == ("CLAUDE_SUBSCRIPTION", True, "out")

    @real_proc("delegate: a worker, git or CLI process")
    def test_three_running_leave_room_for_a_fourth(self):
        for i in range(3):
            self.lease(f"r{i}", "OPENAI_SUBSCRIPTION")
        _, r = self.run_it()
        assert r["lane"] == "OPENAI_SUBSCRIPTION"

    @real_proc("delegate: a worker, git or CLI process")
    def test_expired_leases_do_not_count(self):
        for i in range(4):
            self.lease(f"r{i}", "OPENAI_SUBSCRIPTION", expires=env.now() - 1)
        _, r = self.run_it()
        assert r["lane"] == "OPENAI_SUBSCRIPTION"

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_strained_lane_allows_one(self):
        f = Path(self.tmp.name) / ".claude" / "state" / "max-limits.json"
        d = json.loads(f.read_text())
        d["rate_limits"]["five_hour"]["used_percentage"] = 85
        f.write_text(json.dumps(d))
        support.put_out("OPENAI_SUBSCRIPTION", env.now() + 3600)
        self.lease("c0", "CLAUDE_SUBSCRIPTION")
        _, r = self.run_it()
        assert why(r) == "no_lane"  # one slot, taken: the first choice is out, so nothing waits for a slot

    def strain_openai(self, five=85, week=8):
        def read(lane: Lane, S: Settings, st: StateDoc, t: float, ai_usage: object = None) -> None:
            lane.five, lane.week = five, week

        usage.READERS["codex_app_server"] = read

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_pinned_strained_lane_retries_when_its_one_slot_is_taken(self):
        self.strain_openai()
        self.lease("r0", "OPENAI_SUBSCRIPTION", task="T-busy")
        for unattended in (False, True):
            with self.subTest(unattended=unattended):
                before = time.time()
                code, r = self.run_it("--only-family", "openai", unattended=unattended)
                assert (code, why(r), r["lane"]) == (0, "busy", "OPENAI_SUBSCRIPTION")
                assert (r["stop"]["permanence"], r["stop"]["retry"]["kind"]) == ("transient", "poll")
                assert before + 60 <= at(r) <= time.time() + 120
                assert "openai busy: 1 running, 1 allowed" in r["say"]
                assert "over its limit" not in r["say"]
                if unattended:
                    assert r["transcript_status"] == "not_launched"
                last = json.loads(env.history_path().read_text().splitlines()[-1])
                assert (last["kind"], last["outcome"]) == ("refusal", "busy")
        assert self.args_seen() == ""
        with mock.patch.object(sys, "stdout", new_callable=io.StringIO) as out:
            route.main(["status", "--json"])
            running = json.loads(out.getvalue())["running"]
        assert [(r["run_id"], r["task"]) for r in running] == [("r0", "T-busy")]

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_pinned_family_uses_a_free_lane_or_waits_for_a_busy_one(self):
        cfg = obj(env.load_routing())
        cfg["lanes"]["OPENAI_OTHER"] = dict(cfg["lanes"]["OPENAI_SUBSCRIPTION"])
        self.lease("r0", "OPENAI_SUBSCRIPTION")
        for other_out in (True, False):
            with self.subTest(other_out=other_out):
                fleet = {
                    "OPENAI_OTHER": Lane("OPENAI_OTHER", "openai", "subscription", out=other_out),
                    "OPENAI_SUBSCRIPTION": Lane("OPENAI_SUBSCRIPTION", "openai", "subscription", five=85, week=8),
                }
                builder = mock.Mock()
                builder.build.return_value = Fleet(fleet)
                with (
                    mock.patch.object(env, "load_routing", return_value=cfg),
                    mock.patch("delegate.app.decide.fleet_builder", return_value=builder),
                ):
                    _, r = self.run_it("--only-family", "openai")
                assert why(r) == ("busy" if other_out else None)
                assert r["lane"] == ("OPENAI_SUBSCRIPTION" if other_out else "OPENAI_OTHER")

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_pinned_family_really_out_or_over_ceiling_does_not_poll(self):
        self.lease("r0", "OPENAI_SUBSCRIPTION")
        for out in (False, True):
            with self.subTest(out=out):
                self.strain_openai(five=85, week=8 if out else 100)  # genuinely over the weekly ceiling, even with a free slot
                if out:
                    self.codex_out()
                _, r = self.run_it("--only-family", "openai")
                assert why(r) == "no_lane"
                assert r["stop"]["retry"]["kind"] != "poll"
                assert ("openai out" if out else "openai over its limit") in r["say"]
                assert "openai busy" not in r["say"]

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_pinned_busy_lane_on_hold_does_not_poll_for_a_slot(self):
        self.strain_openai()
        self.lease("r0", "OPENAI_SUBSCRIPTION")
        support.add_hold("OPENAI_SUBSCRIPTION", env.now() + 3600, "owner hold")
        _, r = self.run_it("--only-family", "openai")
        assert why(r) == "no_lane"
        assert r["stop"]["retry"]["kind"] != "poll"

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_pinned_ready_lane_with_an_unsupported_guard_is_not_over_limit(self):
        _, r = self.run_it("--only-family", "openai", "--engine-only", "release-check")
        assert why(r) == "engine_only_unenforced"
        for text in ("OPENAI_SUBSCRIPTION", "--engine-only release-check", "--engine-only-advisory"):
            assert text in r["say"]
        assert "over its limit" not in r["say"]
        assert (r["stop"]["scope"], r["stop"]["permanence"], r["stop"]["retry"]) == ("caller", "needs_owner", {"kind": "none", "at": None})
        assert r["transcript_status"] == "not_launched"
        assert self.args_seen() == ""

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_pinned_codex_writer_can_run_with_engine_only_advisory(self):
        code, r = self.run_it("--only-family", "openai", "--engine-only", "release-check", "--engine-only", "e2e", "--engine-only-advisory")
        assert (code, r["stop"], r["lane"], r["flag"]) == (0, None, "OPENAI_SUBSCRIPTION", "engine_only_advisory")
        assert r["warning"] == "OPENAI_SUBSCRIPTION cannot deny --engine-only release-check, e2e: advisory only, the brief must say so"
        assert self.args_seen()

    @real_proc("delegate: a worker, git or CLI process")
    def test_unpinned_engine_only_still_uses_an_enforcing_lane(self):
        _, r = self.run_it("--engine-only", "release-check")
        assert (r["stop"], r["lane"]) == (None, "CLAUDE_SUBSCRIPTION")
        assert r["flag"] != "engine_only_advisory"
        assert "warning" not in r

    @real_proc("delegate: a worker, git or CLI process")
    def test_unpinned_engine_only_without_an_enforcing_lane_keeps_no_lane(self):
        support.put_out("CLAUDE_SUBSCRIPTION", env.now() + 3600)
        _, r = self.run_it("--engine-only", "release-check")
        assert why(r) == "no_lane"
        assert self.args_seen() == ""

    @real_proc("delegate: a worker, git or CLI process")
    def test_the_same_task_never_runs_twice_at_once(self):
        self.lease("r0", "OPENAI_SUBSCRIPTION", task="T-1")
        _, r = self.run_it("--task", "T-1")
        assert why(r) == "duplicate_task"
        assert "T-1" in r["say"]
        _, r = self.run_it("--task", "T-2")
        assert r["stop"] is None
        env.update_state(lambda s: s.leases.pop("r0"))
        _, r = self.run_it("--task", "T-1")  # a resume after the first run ended is fine
        assert r["stop"] is None

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_final_agent_message_alone_ends_the_run_after_the_grace(self):
        """Rollout 01a177fc: the final message arrived and turn.completed never did."""
        self.fast_clock()
        time.time()
        _, r = self.run_it(mode="message_only", timeout=0)
        assert (r["stop"], r["text"], r["warnings"]) == (None, "final, no turn.completed", ["answer_done_process_alive"])
        self.pid_dead()

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_running_command_keeps_the_long_silence_limit(self):
        self.fast_clock()
        _, r = self.run_it(mode="tool_open", timeout=4)
        assert why(r) == "timeout"

    @real_proc("delegate: a worker, git or CLI process")
    @pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
    def test_read_only_shell_may_write_dot_task_but_nothing_else_in_cwd(self):
        repo = Path(self.repo)
        sh = self.base / "sh-task"
        box.write_shell(self.repo, False, sh)

        def run(c):
            return sp.run([str(sh), "-c", c], cwd=self.repo, capture_output=True, text=True, check=False)

        assert run("mkdir -p .task && touch .task/tmp1").returncode == 0
        assert (repo / ".task" / "tmp1").exists()
        assert run("touch made").returncode != 0
        assert run("touch .taskx").returncode != 0
        assert run("cat ~/.ssh/id_rsa").returncode != 0

    @real_proc("delegate: a worker, git or CLI process")
    def test_external_directory_lets_read_only_lanes_read_runs_and_temp_only(self):
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "/x/cfg"}):
            ext = obj(box.permissions(False))["external_directory"]
        assert ext["*"] == "deny"
        for want in ("/x/cfg/task-loop/runs/**", "/private/tmp/**", "/private/var/folders/**", "/tmp/**", "/var/folders/**"):
            assert ext[want] == "allow"
        assert len(ext) == 6
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XDG_CONFIG_HOME", None)
            assert str(Path.home() / ".config" / "task-loop" / "runs") + "/**" in obj(box.permissions(False))["external_directory"]
        assert obj(box.permissions(True))["external_directory"] == "deny"
        assert obj(box.permissions(False))["read"][str(Path.home() / ".ssh")] == "deny"

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_second_run_of_the_same_task_is_a_retry(self):
        self.lease("run-9", "OPENAI_SUBSCRIPTION", task="T-1")
        _, r = self.run_it("--task", "T-1")
        assert (why(r), r["stop"]["permanence"]) == ("duplicate_task", "transient")

    @real_proc("delegate: a worker, git or CLI process")
    def test_status_json_v1_shape(self):
        self.lease("run-1", "OPENAI_SUBSCRIPTION", task="T-5")
        self.run_it()
        real, sys.stdout = sys.stdout, io.StringIO()
        try:
            route.main(["status", "--json"])
            assert sys.stdout.getvalue().count("\n") == 1
            out = json.loads(sys.stdout.getvalue())
        finally:
            sys.stdout = real
        assert out["v"] == 1
        assert [r["run_id"] for r in out["running"]] == ["run-1"]
        assert out["running"][0]["task"] == "T-5"
        assert "recent" not in out
        assert "OPENAI_SUBSCRIPTION" in out["lanes"]

    @real_proc("delegate: a worker, git or CLI process")
    def test_timeout_kills_the_whole_process_group(self):
        code, r = self.run_it(mode="hang", timeout=2)
        assert (code, why(r)) == (0, "timeout")
        pid = int(Path(os.environ["FAKE_PIDFILE"]).read_text())
        time.sleep(0.3)
        with pytest.raises(OSError):
            os.kill(pid, 0)

    @real_proc("delegate: a worker, git or CLI process")
    def test_status_json_has_a_health_row_per_pair_with_leases_and_last_failures(self):
        self.hist(self.failed_rows(3, 60))
        real, sys.stdout = sys.stdout, io.StringIO()
        try:
            route.main(["status", "--json"])
            payload = json.loads(sys.stdout.getvalue())
        finally:
            sys.stdout = real
        row = next(x for x in payload["health"] if (x["lane"], x["model"]) == ("OPENAI_SUBSCRIPTION", "gpt-6.1-sol"))
        assert (row["state"], row["source"], row["kind"], row["rung"]) == ("broken", "breaker", "worker_failed", 1)
        assert row["leases"] == {"live": 0, "suspect": 0}
        assert len(row["last_failures"]) == 3
        assert row["until"] > env.now() and row["evidence"] == "boom"
        other = next(x for x in payload["health"] if (x["lane"], x["model"]) == ("OPENAI_SUBSCRIPTION", "gpt-6-luna"))
        assert other["state"] == "up"

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_suspect_lease_does_not_count_against_the_lane_cap(self):
        now = env.now()
        quiet = support.lease(
            lane="OPENAI_SUBSCRIPTION", role="worker", start=now - 3000, expires=now + 100, silence_s=2400, last_event=now - 2500
        )
        live = dataclasses.replace(quiet, last_event=now - 10)
        assert leases.suspect(quiet, now)
        assert not leases.suspect(live, now)
        assert not leases.suspect(
            support.lease(lane="x", start=now - 99999, expires=now + 1), now
        )  # an old lease without a limit is not guessed at
        st = support.doc_of({})
        st.leases = {"a": quiet, "b": live}
        assert leases.LeaseBook(st.leases).counts("OPENAI_SUBSCRIPTION", now) == {"live": 2, "suspect": 1}
        assert [r["suspect"] for r in status.running_rows(st, now)] == [True, False]

    @real_proc("delegate: a worker, git or CLI process")
    def test_git_changes_are_reported_not_failed(self):
        code, r = self.run_it(mode="git")
        assert (code, r["stop"]) == (0, None)
        assert any("branch" in x for x in r["git_violation"]), r["git_violation"]

    @real_proc("delegate: a worker, git or CLI process")
    def test_empty_brief_is_an_error_object(self):
        code, r = self.run_it(brief="  ")
        assert (code, why(r)) == (0, "caller")

    @real_proc("delegate: a worker, git or CLI process")
    def test_an_orphaned_worker_of_a_dead_route_py_is_killed_before_the_task_runs_again(self):
        dead = sp.Popen(["true"])
        dead.wait()
        orphan = sp.Popen(["sleep", "300"], start_new_session=True)
        try:
            start = proc_start(orphan.pid)
            support.put_lease(
                "old-run",
                lane="OPENAI_SUBSCRIPTION",
                role="worker",
                pid=dead.pid,
                pid_start="Mon Jan  1 00:00:00 2001",
                start=env.now() - 300,
                expires=env.now() + 60,
                task="T-7",
                worker_pid=orphan.pid,
                worker_start=start,
            )
            _, r = self.run_it("--task", "T-7")
            assert r["stop"] is None  # ran after the orphan was stopped
            assert orphan.poll() is not None
            rows = [json.loads(x) for x in env.history_path().read_text().splitlines()]
            assert (True, orphan.pid) in [(x.get("reaped"), x.get("worker_pid")) for x in rows]
        finally:
            orphan.kill()

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_live_route_py_with_an_expired_lease_keeps_its_worker(self):
        worker = sp.Popen(["sleep", "300"], start_new_session=True)
        try:
            support.put_lease(
                "old-run",
                lane="OPENAI_SUBSCRIPTION",
                role="worker",
                pid=os.getpid(),
                pid_start=proc_start(os.getpid()),
                start=env.now() - 300,
                expires=env.now() - 1,
                task="T-9",
                worker_pid=worker.pid,
                worker_start=proc_start(worker.pid),
            )
            _, r = self.run_it("--task", "T-9")
            assert why(r) == "duplicate_task"
            assert worker.poll() is None
        finally:
            worker.kill()
            worker.wait()

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_reused_pid_is_not_killed(self):
        dead = sp.Popen(["true"])
        dead.wait()
        other = sp.Popen(["sleep", "300"], start_new_session=True)
        try:
            support.put_lease(
                "old-run",
                lane="OPENAI_SUBSCRIPTION",
                role="worker",
                pid=dead.pid,
                pid_start="x",
                start=env.now() - 300,
                expires=env.now() - 1,
                task="T-8",
                worker_pid=other.pid,
                worker_start="Mon Jan  1 00:00:00 2001",
            )
            _, r = self.run_it("--task", "T-8")
            assert r["stop"] is None
            assert other.poll() is None
        finally:
            other.kill()
            other.wait()

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_resume_on_a_lane_with_all_slots_taken_waits_for_a_slot(self):
        self.run_it()
        for i in range(4):
            self.lease(f"run-{i}", "OPENAI_SUBSCRIPTION")
        before = time.time()
        _, r = self.run_it("--resume", "thread-123")
        assert (why(r), r["stop"]["permanence"], r["lane"]) == ("busy", "transient", "OPENAI_SUBSCRIPTION")
        assert before + 50 < at(r) < time.time() + 130
        last = json.loads(env.history_path().read_text().splitlines()[-1])  # refusals are in history too
        assert (last["outcome"], last["resume"], last["kind"]) == ("busy", True, "refusal")

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_plan_with_only_a_weekly_window_reads_it_as_the_week(self):
        res = {
            "ordinaryUsageAllowed": True,
            "rateLimits": {
                "primary": {"usedPercent": 40, "windowDurationMins": 10080, "resetsAt": env.now() + 3 * 86400},
                "secondary": None,
                "rateLimitReachedType": None,
            },
        }
        env.update_state(lambda s: setattr(s, "codex_limits", UsageCache(at=env.now(), data=res)))
        lane = Lane("OPENAI_SUBSCRIPTION", "openai", "subscription")
        self.real["codex_app_server"](lane, env.settings_of(env.load_routing()), env.load_state(), env.now())
        assert (lane.five, lane.week) == (None, 40.0)
        assert lane.pace is not None

    @real_proc("delegate: a worker, git or CLI process")
    def test_resume_continues_on_the_same_lane_and_never_switches(self):
        _, first = self.run_it()
        assert first["ref"] == "thread-123"
        _, r = self.run_it("--resume", "thread-123")
        assert (r["stop"], r["lane"]) == (None, "OPENAI_SUBSCRIPTION")
        assert "exec resume" in self.args_seen()
        assert 'sandbox_mode="workspace-write"' in self.args_seen()
        support.put_out("OPENAI_SUBSCRIPTION", env.now() + 3600)
        n = len(self.args_seen().splitlines())
        _, r = self.run_it("--resume", "thread-123")
        assert (why(r), r["lane"], r["stop"]["permanence"]) == ("rate_limited", "OPENAI_SUBSCRIPTION", "transient")
        assert at(r) > time.time()
        assert "out until" in r["say"]
        assert len(self.args_seen().splitlines()) == n  # nothing was launched
        _, r = self.run_it("--resume", "nope")
        assert why(r) == "caller"


class DepthAndPush(RunBase):
    @real_proc("delegate: a worker, git or CLI process")
    def test_a_caller_that_is_itself_a_worker_is_refused(self):
        os.environ["DELEGATE_DEPTH"] = "1"
        self.addCleanup(os.environ.pop, "DELEGATE_DEPTH", None)
        code, r = self.run_it()
        assert (code, why(r), r["stop"]["scope"]) == (0, "caller", "caller")
        assert "DELEGATE_DEPTH" in r["say"]
        assert not Path(os.environ["FAKE_ARGS"]).exists()  # nothing was launched

    @real_proc("delegate: a worker, git or CLI process")
    def test_every_worker_env_refuses_a_push_and_keeps_the_callers_git_config(self):
        os.environ.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="core.hooksPath", GIT_CONFIG_VALUE_0="/h")
        for k in ("GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0"):
            self.addCleanup(os.environ.pop, k, None)
        e = env.child_env()
        assert e["GIT_CONFIG_COUNT"] == "2"
        assert (e["GIT_CONFIG_KEY_0"], e["GIT_CONFIG_VALUE_0"]) == ("core.hooksPath", "/h")
        assert (e["GIT_CONFIG_KEY_1"], e["GIT_CONFIG_VALUE_1"]) == (f"url.{env.PUSH_REFUSED}.pushInsteadOf", "")
        assert e["DELEGATE_DEPTH"] == "1"

        bare = self.base / "remote.git"
        sp.run(["git", "init", "-q", "--bare", str(bare)], check=True, capture_output=True)
        sp.run(["git", "-C", self.repo, "remote", "add", "origin", str(bare)], check=True, capture_output=True)
        pushed = sp.run(
            ["git", "-C", self.repo, "push", "origin", "HEAD"], env={**os.environ, **e}, capture_output=True, text=True, check=False
        )
        assert pushed.returncode != 0
        assert not list((bare / "refs" / "heads").iterdir())
        assert (
            sp.run(["git", "-C", self.repo, "fetch", "origin"], env={**os.environ, **e}, capture_output=True, check=False).returncode == 0
        )
