"""Lifecycle telemetry: a stable fingerprint and started_because on every trace row, whatever ended the run, plus
the structured timing records the lifecycle report reads (gate, vendor error, kill, check cache)."""

import json
import os
import time
from unittest import mock

import pytest
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import engine_case as te
from support import homes, procsim
from support.engine_case import stop
from support.plans import CLEAN, PLAN, WRITE

from taskloop.adapters import delegate as dl
from taskloop.app.plan.planner import Planner
from taskloop.app.run import engine
from taskloop.app.slots import config as wslots_config
from taskloop.domain.lifecycle import matchers as lifecycle
from tlkernel.env import snapshot
from tlkernel.ids import BeadId
from tlkernel.kinds import Kind
from tltestkit import fake_route
from tltestkit.case import Case

ROOT = te.ROOT
from support.dashes import make_dash  # noqa: E402
from support.spawn import port_git, real_spawner  # noqa: E402
from support.who import who  # noqa: E402

DASH = make_dash()


class Fingerprint(Case):
    def test_volatile_ids_paths_and_numbers_do_not_change_a_fingerprint(self):
        a = lifecycle.fingerprint("failed: bead tl-19i on /Users/me/repo/src/file.py exit 1 after 2.8 h: `boom`")
        b = lifecycle.fingerprint("FAILED: bead lifesim-d5f.46 on /home/other/tree/a/b.py exit 127 after 14 h: `boom`")
        assert a == b
        assert "<bead>" in a
        assert "<path>" in a
        assert "quoted" in a
        assert a != lifecycle.fingerprint("failed: bead tl-19i on /Users/me/repo/src/file.py exit 1 after 2.8 h: `bang`")  # another quote

    def test_a_session_ref_a_sha_and_a_uuid_are_volatile_too(self):
        one = lifecycle.fingerprint("thread ref-write failed at 1234abc after ses_123 on 123e4567-e89b-12d3-a456-426614174000")
        two = lifecycle.fingerprint("thread ref-review failed at deadbeef after ses_999 on 00000000-0000-0000-0000-000000000000")
        assert one == two

    def test_distinct_failures_keep_distinct_fingerprints(self):
        assert lifecycle.fingerprint("missing recipe: just unity-tests") != lifecycle.fingerprint("compile error in Assets/Player.cs")
        assert lifecycle.fingerprint("no lane for write") != lifecycle.fingerprint("review sent it back: unmet acceptance")

    def test_letter_only_bead_ids_are_volatile(self):
        a = lifecycle.fingerprint("failed: bead tl-fsj cannot resume")
        b = lifecycle.fingerprint("failed: bead tl-xyz cannot resume")
        assert a == b
        assert "<bead>" in a
        assert "tl-fsj" not in a

    def test_relative_and_windows_paths_are_volatile(self):
        a = lifecycle.fingerprint("compile error in Assets/Player.cs")
        b = lifecycle.fingerprint(r"compile error in Assets\Enemy.cs")
        c = lifecycle.fingerprint("compile error in /repo/Assets/Other.cs")
        assert a == b
        assert a == c
        assert "<path>" in a

    def test_digits_in_paths_and_session_refs_are_not_beads(self):
        one = lifecycle.fingerprint("compile error in Assets/Player2.cs from thread-123")
        two = lifecycle.fingerprint("compile error in Assets/Player.cs from thread-abc")
        assert one == two
        assert "<path>" in one
        assert "<session>" in one
        assert "<bead>" not in one

    def test_whole_sessions_and_paths_precede_embedded_hex_and_uuid_replacement(self):
        one = lifecycle.fingerprint(
            "failed in thread-1234abc from /repo/thread-deadbeef/Assets/Player.cs")
        two = lifecycle.fingerprint(
            "failed in thread-9999fff from C:\\repo\\thread-cafebabe\\Assets\\Enemy.cs")
        uuid_one = lifecycle.fingerprint(
            "failed in thread-123e4567-e89b-12d3-a456-426614174000 from /repo/"
            "123e4567-e89b-12d3-a456-426614174000/Assets/Player.cs")
        uuid_two = lifecycle.fingerprint(
            "failed in thread-00000000-0000-0000-0000-000000000000 from C:\\repo\\"
            "00000000-0000-0000-0000-000000000000\\Assets\\Enemy.cs")
        assert one == two
        assert uuid_one == uuid_two
        assert one == uuid_one
        for text in (one, uuid_one):
            assert "<session>" in text
            assert "<path>" in text
            assert "<sha>" not in text
            assert "<id>" not in text
            assert "<bead>" not in text
        assert lifecycle.fingerprint("missing recipe: just unity-tests") != lifecycle.fingerprint("compile error in Assets/Player.cs")

    def test_descriptive_hyphenated_words_stay_readable(self):
        text = lifecycle.fingerprint("read-only sub-task refused")
        assert "read-only" in text
        assert "sub-task" in text

    def test_empty_text_and_long_text(self):
        assert lifecycle.fingerprint("") == ""
        assert lifecycle.fingerprint("   \n ") == ""
        head = "a" * 112
        assert lifecycle.fingerprint(head + " one") != lifecycle.fingerprint(head + " two")
        assert len(lifecycle.fingerprint(head + " one")) <= 121

    def test_run_fingerprint_is_empty_only_for_a_success(self):
        assert lifecycle.run_fingerprint("landed", "why ever") == ""
        assert lifecycle.run_fingerprint("done", "") == ""
        assert lifecycle.run_fingerprint("blocked", "ticket: no criteria") == "ticket: no criteria"
        assert lifecycle.run_fingerprint("failed", "") == "unknown"

    def test_started_because_is_always_one_of_the_known_values(self):
        for good in lifecycle.STARTED_BECAUSE:
            assert lifecycle.normalize_started_because(good, "old") == good
        assert lifecycle.normalize_started_because("", "") == "first"
        assert lifecycle.normalize_started_because("unknown", "old") == "retry"
        assert lifecycle.normalize_started_because("  ANSWER ", "") == "answer"


class TraceTelemetry(te.EngineTest):

    def traces(self):
        path = homes.config_dir() / "traces.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()]

    def records(self, kind):
        return [json.loads(line) for line in self.eng.log_path.read_text().splitlines() if json.loads(line)["kind"] == kind]

    def assert_row(self, outcome=None, because="first"):
        row = self.traces()[-1]
        assert row["started_because"] == because
        assert row["started_because"] in lifecycle.STARTED_BECAUSE
        assert "fingerprint" in row
        assert row["fingerprint"] == lifecycle.run_fingerprint(row["outcome"], row["why"])
        if outcome is not None:
            assert row["outcome"] == outcome
        if row["outcome"] in ("landed", "done"):
            assert row["fingerprint"] == ""
        else:
            assert row["fingerprint"]
        for old in ("run", "bead", "repo_url", "worktree", "branch", "version", "started", "ended", "outcome", "why",
                    "cost", "stats", "sessions", "log", "prev_run", "ask"):
            assert old in row
        return row

    def test_a_decision_ask_keeps_its_reason_and_fingerprint(self):
        rc, _ = self.run_engine({"plan": [dict(PLAN, irreversible="push_shared", question="Old format or new?")]})
        assert rc == 2
        row = self.assert_row("blocked")
        assert "owner decision needed" in row["why"]
        assert row["fingerprint"]

    def test_a_paused_run_has_a_vendor_error_record_and_a_fingerprint(self):
        due = time.time() + 3 * 3600
        rc, _ = self.run_engine({"plan": [PLAN], "write": [
            stop("rate_limited", at=due, say="out", lane="OPENAI_SUBSCRIPTION")]})
        assert rc == 2
        self.assert_row("blocked")
        errors = self.records("vendor_error")
        assert errors
        assert any(e.get("reason") == "rate_limited" for e in errors)
        for key in ("started_t", "ended_t", "first_error_t", "last_event_t", "kill_t", "error_observed"):
            assert key in errors[0]
        assert not errors[0]["error_observed"]
        assert errors[0]["first_error_t"] is None

    def test_a_failed_run_has_a_fingerprint(self):
        rc, _ = self.run_engine({"plan": [stop("worker_failed", say="boom")] * 2})
        assert rc == 2
        row = self.assert_row("failed")
        assert row["fingerprint"]

    def test_a_stop_mid_run_still_writes_started_because_and_fingerprint(self):
        with mock.patch.object(Planner, "plan", side_effect=engine.Blocked("failed: stopped (SIGTERM)", kind=Kind.PAUSE_KILLED)):
            rc, _ = self.run_engine({})
        assert rc == 2
        row = self.assert_row("failed")
        assert "stopped" in row["why"]
        assert row["fingerprint"]

    def test_a_stop_before_the_engine_ran_still_writes_the_row(self):
        with mock.patch.object(engine.Engine, "stop_pending", True, create=True):
            rc, _ = self.run_engine({})
        assert rc == 2
        self.assert_row("failed")

    def test_an_early_failure_before_the_reset_still_writes_the_row(self):
        with self.store.stub(show=None):
            rc, _ = self.run_engine({})
        assert rc == 2
        self.assert_row("failed")

    def test_a_run_with_no_route_still_writes_the_row(self):
        rc, _ = self.run_engine({}, route="")
        assert rc == 2
        self.assert_row("failed")

    def test_a_bead_without_criteria_still_writes_the_row(self):
        bead = {"id": "t-1", "title": "Add f", "metadata": {}}
        with self.store.stub(show=bead):
            rc, _ = self.run_engine({})
        assert rc == 2
        row = self.assert_row("blocked")
        assert "ticket:" in row["why"]

    def test_a_second_failure_after_another_run_is_a_retry_with_its_own_fingerprint(self):
        self.run_engine({}, route="")
        first = self.traces()[-1]
        rc, _ = self.run_engine({"plan": [stop("worker_failed", say="different cause")] * 2})
        assert rc == 2
        row = self.assert_row("failed", because="retry")
        assert row["prev_run"] == first["run"]
        assert row["fingerprint"] != first["fingerprint"]

    def test_gate_and_check_cache_boundaries_leave_structured_records(self):
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]},
                                gate="true")
        assert rc == 0
        (start,), (end,) = self.records("gate_start"), self.records("gate_end")
        assert end["exit"] == 0
        assert "exec_seconds" in end
        assert not end["skipped"]
        assert start["cmd"] and start["tree"]
        cache = self.records("checks")
        assert cache
        run = cache[-1]["run"]
        assert run["hits"] + run["misses"] == len(run["results"])

    @pytest.mark.skipif(os.name == "nt", reason="the engine stops a process group; sleep and bash are POSIX")
    def test_a_timed_out_command_leaves_a_kill_record(self):
        eng = engine.Engine(
            BeadId("t-1"),
            str(self.wt),
            wslots_config.load_cfg(str(self.wt), port_git()),
            verbose=False,
            store=self.store,
            env=snapshot(),
            spawner=real_spawner(),
            git=port_git(), who=who())
        procsim.fake("sleep 5", procsim.takes(5))
        rc, _ = eng.sh(["sleep", "5"], timeout=0.05)
        assert rc == 124
        kills = [json.loads(line) for line in eng.log_path.read_text().splitlines()
                 if json.loads(line)["kind"] == "kill"]
        assert kills
        assert kills[-1]["exit"] == 124
        assert "secs" in kills[-1]
        assert "observed_t" in kills[-1]
        assert "started_t" in kills[-1]

    def test_a_command_that_exits_124_by_itself_is_not_a_kill(self):
        eng = engine.Engine(
            BeadId("t-1"),
            str(self.wt),
            wslots_config.load_cfg(str(self.wt), port_git()),
            verbose=False,
            store=self.store,
            env=snapshot(),
            spawner=real_spawner(),
            git=port_git(), who=who())
        rc, _ = eng.sh([procsim.fake("exits-124", procsim.exits(124))], timeout=10)
        assert rc == 124
        kills = [json.loads(line) for line in eng.log_path.read_text().splitlines()
                 if json.loads(line)["kind"] == "kill"]
        assert kills == []


    def test_a_stopped_delegate_worker_that_survives_still_leaves_a_kill_record(self):
        eng = engine.Engine(
            BeadId("t-1"),
            str(self.wt),
            wslots_config.load_cfg(str(self.wt), port_git()),
            verbose=False,
            store=self.store,
            env=snapshot(),
            spawner=real_spawner(),
            git=port_git(), who=who())

        class Survivor(fake_route.Script):  # the engine ended the call, and the worker outlived every signal
            def reply(this, *a, **kw):
                this.stop = {"alive": [4242], "why": "timeout 1 min"}
                raise dl.Stopped("timeout 1 min")
        with te.delegate_stack(Survivor({})), pytest.raises(engine.Blocked):
            eng.ai("plan", "title", "prompt")
        kills = [json.loads(line) for line in eng.log_path.read_text().splitlines()
                 if json.loads(line)["kind"] == "kill"]
        assert kills
        assert kills[-1]["alive"] == [4242]
        assert kills[-1]["why"] == "timeout 1 min"

    def test_a_delegate_interruption_leaves_a_kill_record(self):
        class Interrupted(fake_route.Script):  # ctrl-C while the worker ran: the runner kept what it saw
            def reply(this, *a, **kw):
                this.stop.update(why="interrupted", alive=[4242])
                this.obs.update(started_t=100.0, ended_t=102.0, first_error_t=100.5, last_event_t=101.0,
                                kill_t=101.5, why="interrupted", alive=[4242])
                raise KeyboardInterrupt()

        eng = engine.Engine(
            BeadId("t-1"),
            str(self.wt),
            wslots_config.load_cfg(str(self.wt), port_git()),
            verbose=False,
            store=self.store,
            env=snapshot(),
            spawner=real_spawner(),
            git=port_git(), who=who())
        with te.delegate_stack(Interrupted({})), pytest.raises(KeyboardInterrupt):
            eng.ai("plan", "title", "prompt")
        kills = [json.loads(line) for line in eng.log_path.read_text().splitlines()
                 if json.loads(line)["kind"] == "kill"]
        assert kills
        assert kills[-1]["why"] == "interrupted"
        assert kills[-1]["alive"] == [4242]
        assert kills[-1]["kill_t"] == 101.5
        assert kills[-1]["last_event_t"] == 101.0
