"""Lifecycle telemetry: a stable fingerprint and started_because on every trace row, whatever ended the run, plus
the structured timing records the lifecycle report reads (gate, vendor error, kill, check cache)."""

import json
import os
import sys
import threading
import time
import unittest
from unittest import mock

import test_engine as te
import delegate_link as dl
from support import fake_route
from test_engine import CLEAN, PLAN, PY, WRITE, stop

import engine
import lifecycle
import tl

ROOT = te.ROOT
sys.path.insert(0, str(ROOT / "skills" / "task-loop" / "dash"))
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
from support.builders import make_engine  # noqa: E402
import server  # noqa: E402


class FakeCheckProc:
    """A check process with a real output pipe and a scripted stop, for deterministic idle-path tests."""
    pid, args = 4242, ["fake-check"]

    def __init__(self):
        read_fd, self.write_fd = os.pipe()
        self.stdout = os.fdopen(read_fd, "rb", buffering=0)
        self.returncode = None
        self.shutdown_sent = False

    def emit(self, text):
        os.write(self.write_fd, text.encode())

    def stop(self, text):
        if self.shutdown_sent:
            return
        self.shutdown_sent = True
        os.write(self.write_fd, text.encode())
        os.close(self.write_fd)
        self.returncode = 0

    def communicate(self, timeout=None):
        return b"", 0

    def wait(self, timeout=None):
        return 0


class Fingerprint(unittest.TestCase):
    def test_volatile_ids_paths_numbers_and_quotes_do_not_change_a_fingerprint(self):
        a = lifecycle.fingerprint("failed: bead tl-19i on /Users/me/repo/src/file.py exit 1 after 2.8 h: `boom`")
        b = lifecycle.fingerprint("FAILED: bead lifesim-d5f.46 on /home/other/tree/a/b.py exit 127 after 14 h: `bang`")
        self.assertEqual(a, b)
        self.assertIn("<bead>", a)
        self.assertIn("<path>", a)
        self.assertIn("<quoted>", a)

    def test_a_session_ref_a_sha_and_a_uuid_are_volatile_too(self):
        one = lifecycle.fingerprint("thread ref-write failed at 1234abc after ses_123 on 123e4567-e89b-12d3-a456-426614174000")
        two = lifecycle.fingerprint("thread ref-review failed at deadbeef after ses_999 on 00000000-0000-0000-0000-000000000000")
        self.assertEqual(one, two)

    def test_distinct_failures_keep_distinct_fingerprints(self):
        self.assertNotEqual(lifecycle.fingerprint("missing recipe: just unity-tests"),
                            lifecycle.fingerprint("compile error in Assets/Player.cs"))
        self.assertNotEqual(lifecycle.fingerprint("no lane for write"),
                            lifecycle.fingerprint("review sent it back: unmet acceptance"))

    def test_letter_only_bead_ids_are_volatile(self):
        a = lifecycle.fingerprint("failed: bead tl-fsj cannot resume")
        b = lifecycle.fingerprint("failed: bead tl-xyz cannot resume")
        self.assertEqual(a, b)
        self.assertIn("<bead>", a)
        self.assertNotIn("tl-fsj", a)

    def test_relative_and_windows_paths_are_volatile(self):
        a = lifecycle.fingerprint("compile error in Assets/Player.cs")
        b = lifecycle.fingerprint(r"compile error in Assets\Enemy.cs")
        c = lifecycle.fingerprint("compile error in /repo/Assets/Other.cs")
        self.assertEqual(a, b)
        self.assertEqual(a, c)
        self.assertIn("<path>", a)

    def test_digits_in_paths_and_session_refs_are_not_beads(self):
        one = lifecycle.fingerprint("compile error in Assets/Player2.cs from thread-123")
        two = lifecycle.fingerprint("compile error in Assets/Player.cs from thread-abc")
        self.assertEqual(one, two)
        self.assertIn("<path>", one)
        self.assertIn("<session>", one)
        self.assertNotIn("<bead>", one)

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
        self.assertEqual(one, two)
        self.assertEqual(uuid_one, uuid_two)
        self.assertEqual(one, uuid_one)
        for text in (one, uuid_one):
            self.assertIn("<session>", text)
            self.assertIn("<path>", text)
            self.assertNotIn("<sha>", text)
            self.assertNotIn("<id>", text)
            self.assertNotIn("<bead>", text)
        self.assertNotEqual(lifecycle.fingerprint("missing recipe: just unity-tests"),
                            lifecycle.fingerprint("compile error in Assets/Player.cs"))

    def test_descriptive_hyphenated_words_stay_readable(self):
        text = lifecycle.fingerprint("read-only sub-task refused")
        self.assertIn("read-only", text)
        self.assertIn("sub-task", text)

    def test_empty_text_and_long_text(self):
        self.assertEqual(lifecycle.fingerprint(""), "")
        self.assertEqual(lifecycle.fingerprint("   \n "), "")
        head = "a" * 112
        self.assertNotEqual(lifecycle.fingerprint(head + " one"), lifecycle.fingerprint(head + " two"))
        self.assertLessEqual(len(lifecycle.fingerprint(head + " one")), 121)

    def test_run_fingerprint_is_empty_only_for_a_success(self):
        self.assertEqual(lifecycle.run_fingerprint("landed", "why ever"), "")
        self.assertEqual(lifecycle.run_fingerprint("done", ""), "")
        self.assertEqual(lifecycle.run_fingerprint("blocked", "ticket: no criteria"), "ticket: no criteria")
        self.assertEqual(lifecycle.run_fingerprint("failed", ""), "unknown")

    def test_started_because_is_always_one_of_the_known_values(self):
        for good in lifecycle.STARTED_BECAUSE:
            self.assertEqual(lifecycle.normalize_started_because(good, "old"), good)
        self.assertEqual(lifecycle.normalize_started_because("", ""), "first")
        self.assertEqual(lifecycle.normalize_started_because("unknown", "old"), "retry")
        self.assertEqual(lifecycle.normalize_started_because("  ANSWER ", ""), "answer")


class TraceTelemetry(unittest.TestCase):
    setUp, tearDown, fake_bd, run_engine = (te.EngineTest.setUp, te.EngineTest.tearDown, te.EngineTest.fake_bd,
                                            te.EngineTest.run_engine)
    commit_base_cfg = te.EngineTest.commit_base_cfg

    def traces(self):
        path = tl.config_dir() / "traces.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()]

    def records(self, kind):
        return [json.loads(line) for line in self.eng.log_path.read_text().splitlines() if json.loads(line)["kind"] == kind]

    def assert_row(self, outcome=None, because="first"):
        row = self.traces()[-1]
        self.assertEqual(row["started_because"], because)
        self.assertIn(row["started_because"], lifecycle.STARTED_BECAUSE)
        self.assertIn("fingerprint", row)
        self.assertEqual(row["fingerprint"], lifecycle.run_fingerprint(row["outcome"], row["why"]))
        if outcome is not None:
            self.assertEqual(row["outcome"], outcome)
        if row["outcome"] in ("landed", "done"):
            self.assertEqual(row["fingerprint"], "")
        else:
            self.assertTrue(row["fingerprint"])
        for old in ("run", "bead", "repo_url", "worktree", "branch", "version", "started", "ended", "outcome", "why",
                    "cost", "stats", "sessions", "log", "prev_run", "ask"):
            self.assertIn(old, row)
        return row

    def test_a_landed_run_has_no_fingerprint_and_still_reads_in_the_dashboard(self):
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        row = self.assert_row("landed")
        run = server.run_timeline(str(self.eng.log_path))
        self.assertEqual(run["started_because"], row["started_because"])
        self.assertEqual(run["end"]["outcome"], "landed")

    def test_a_decision_ask_keeps_its_reason_and_fingerprint(self):
        rc, _ = self.run_engine({"plan": [dict(PLAN, irreversible="push_shared", question="Old format or new?")]})
        self.assertEqual(rc, 2)
        row = self.assert_row("blocked")
        self.assertIn("owner decision needed", row["why"])
        self.assertTrue(row["fingerprint"])

    def test_a_paused_run_has_a_vendor_error_record_and_a_fingerprint(self):
        due = time.time() + 3 * 3600
        rc, _ = self.run_engine({"plan": [PLAN], "write": [
            stop("rate_limited", at=due, say="out", lane="OPENAI_SUBSCRIPTION")]})
        self.assertEqual(rc, 2)
        self.assert_row("blocked")
        errors = self.records("vendor_error")
        self.assertTrue(errors)
        self.assertTrue(any(e.get("reason") == "rate_limited" for e in errors))
        for key in ("started_t", "ended_t", "first_error_t", "last_event_t", "kill_t", "error_observed"):
            self.assertIn(key, errors[0])
        self.assertFalse(errors[0]["error_observed"])
        self.assertIsNone(errors[0]["first_error_t"])

    def test_a_failed_run_has_a_fingerprint(self):
        rc, _ = self.run_engine({"plan": [stop("worker_failed", say="boom")] * 2})
        self.assertEqual(rc, 2)
        row = self.assert_row("failed")
        self.assertTrue(row["fingerprint"])

    def test_a_stop_mid_run_still_writes_started_because_and_fingerprint(self):
        with mock.patch.object(engine.Engine, "plan", side_effect=engine.Blocked("failed: stopped (SIGTERM)")):
            rc, _ = self.run_engine({})
        self.assertEqual(rc, 2)
        row = self.assert_row("failed")
        self.assertIn("stopped", row["why"])
        self.assertTrue(row["fingerprint"])

    def test_a_stop_before_the_engine_ran_still_writes_the_row(self):
        with mock.patch.object(engine.Engine, "stop_pending", True, create=True):
            rc, _ = self.run_engine({})
        self.assertEqual(rc, 2)
        self.assert_row("failed")

    def test_an_early_failure_before_the_reset_still_writes_the_row(self):
        with self.store.stub(show=None):
            rc, _ = self.run_engine({})
        self.assertEqual(rc, 2)
        self.assert_row("failed")

    def test_a_run_with_no_route_still_writes_the_row(self):
        rc, _ = self.run_engine({}, route="")
        self.assertEqual(rc, 2)
        self.assert_row("failed")

    def test_a_bead_without_criteria_still_writes_the_row(self):
        bead = {"id": "t-1", "title": "Add f", "metadata": {}}
        with self.store.stub(show=bead):
            rc, _ = self.run_engine({})
        self.assertEqual(rc, 2)
        row = self.assert_row("blocked")
        self.assertIn("ticket:", row["why"])

    def test_a_second_failure_after_another_run_is_a_retry_with_its_own_fingerprint(self):
        self.run_engine({}, route="")
        first = self.traces()[-1]
        time.sleep(1.05)  # a run's name is its start second
        rc, _ = self.run_engine({"plan": [stop("worker_failed", say="different cause")] * 2})
        self.assertEqual(rc, 2)
        row = self.assert_row("failed", because="retry")
        self.assertEqual(row["prev_run"], first["run"])
        self.assertNotEqual(row["fingerprint"], first["fingerprint"])

    def test_gate_and_check_cache_boundaries_leave_structured_records(self):
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]},
                                gate=PY + ' -c "pass"')
        self.assertEqual(rc, 0)
        (start,), (end,) = self.records("gate_start"), self.records("gate_end")
        self.assertEqual(end["exit"], 0)
        self.assertIn("secs", end)
        self.assertFalse(end["skipped"])
        self.assertTrue(start["cmd"] and start["tree"])
        cache = self.records("checks")
        self.assertTrue(cache)
        self.assertEqual(cache[-1]["hits"] + cache[-1]["misses"], len(cache[-1]["items"]))

    @unittest.skipIf(os.name == "nt", "the engine stops a process group; sleep and bash are POSIX")
    def test_a_timed_out_command_leaves_a_kill_record(self):
        eng = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)), verbose=False, store=self.store)
        rc, _ = eng.sh("sleep 5", timeout=0.05)
        self.assertEqual(rc, 124)
        kills = [json.loads(line) for line in eng.log_path.read_text().splitlines()
                 if json.loads(line)["kind"] == "kill"]
        self.assertTrue(kills)
        self.assertEqual(kills[-1]["exit"], 124)
        self.assertIn("secs", kills[-1])
        self.assertIn("observed_t", kills[-1])
        self.assertIn("started_t", kills[-1])

    def test_a_command_that_exits_124_by_itself_is_not_a_kill(self):
        eng = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)), verbose=False, store=self.store)
        rc, _ = eng.sh(PY + ' -c "import sys; sys.exit(124)"', timeout=10)
        self.assertEqual(rc, 124)
        kills = [json.loads(line) for line in eng.log_path.read_text().splitlines()
                 if json.loads(line)["kind"] == "kill"]
        self.assertEqual(kills, [])

    def test_a_keyboard_interrupt_after_kill_leaves_a_record(self):
        class FakeProc:
            pid, returncode, args = 999999, None, ["fake"]

            def communicate(self, timeout=None):
                raise KeyboardInterrupt()

            def wait(self, timeout=None):
                return 0

        eng = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)), verbose=False, store=self.store)
        with mock.patch.object(engine.subprocess, "Popen", return_value=FakeProc()), \
                mock.patch.object(engine.procs, "kill_tree") as kill:
            with self.assertRaises(KeyboardInterrupt):
                eng.sh("fake", timeout=5)
        self.assertTrue(kill.called)
        kills = [json.loads(line) for line in eng.log_path.read_text().splitlines()
                 if json.loads(line)["kind"] == "kill"]
        self.assertTrue(kills)
        self.assertEqual(kills[-1]["why"], "interrupted")
        self.assertIn("observed_t", kills[-1])

    def test_a_check_that_goes_silent_freezes_its_last_event_at_the_hang_boundary(self):
        eng = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)), verbose=False, store=self.store)
        code = (
            "import signal,sys,time\n"
            "def bye(*_):\n"
            "    sys.stderr.write('shutdown output after the hang\\n'); sys.stderr.flush()\n"
            "    time.sleep(0.2)\n"
            "    sys.exit(0)\n"
            "signal.signal(signal.SIGTERM, bye)\n"
            "sys.stderr.write('productive start\\n'); sys.stderr.flush()\n"
            "time.sleep(0.8)\n"
            "sys.stderr.write('productive end\\n'); sys.stderr.flush()\n"
            "time.sleep(10)\n"
        )
        rc, tail = eng.sh([sys.executable, "-c", code], timeout=10, idle=1)
        self.assertEqual(rc, 124)
        self.assertIn("productive end", tail)
        self.assertIn("shutdown output after the hang", tail)
        kills = [json.loads(line) for line in eng.log_path.read_text().splitlines()
                 if json.loads(line)["kind"] == "kill"]
        self.assertTrue(kills)
        kill = kills[-1]
        self.assertEqual(kill["why"], "hung")
        self.assertTrue(kill["hung"])
        self.assertIsNotNone(kill["last_event_t"])
        self.assertIsNotNone(kill["kill_t"])
        self.assertLessEqual(kill["last_event_t"], kill["kill_t"])
        self.assertGreaterEqual(kill["kill_t"] - kill["last_event_t"], 0.8)
        self.assertGreaterEqual(kill["last_event_t"] - kill["started_t"], 0.5)

    def test_hung_freeze_rechecks_activity_inside_the_lock(self):
        eng = make_engine(self.wt, verbose=False, store=self.store, attrs={"last_event_t": 100.0, "_event_frozen": False, "killed": False, "kill_why": ""})

        class LateActivityLock:
            def __enter__(self):
                eng.last_event_t = 100.9  # output arrives after a stale read, before the freeze
                return self

            def __exit__(self, *exc):
                return False

        eng._event_lock = LateActivityLock()
        self.assertFalse(eng._freeze_check("hung", idle=1.0, now=101.0))
        self.assertFalse(eng.killed)
        self.assertFalse(eng._event_frozen)
        self.assertEqual(eng.last_event_t, 100.9)
        self.assertTrue(eng._freeze_check("hung", idle=1.0, now=101.91))
        self.assertTrue(eng.killed)
        self.assertTrue(eng._event_frozen)
        self.assertEqual(eng.kill_why, "hung")

    def test_a_slow_activity_scan_is_timestamped_when_it_returns(self):
        eng = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)), verbose=False, store=self.store)
        p = FakeCheckProc()
        scan_returned = []

        def slow_activity(*_):
            if not scan_returned:
                time.sleep(1.0)
                scan_returned.append(time.time())
                return True
            return False

        def stop(proc):
            proc.stop("shutdown after slow scan\n")

        with mock.patch.object(engine.subprocess, "Popen", return_value=p), \
                mock.patch.object(engine.procs, "kill_tree", side_effect=stop), \
                mock.patch.object(engine.cs, "activity", side_effect=slow_activity):
            rc, _ = eng.sh("fake-check", timeout=10, idle=0.5)
        self.assertEqual(rc, 124)
        kills = [json.loads(line) for line in eng.log_path.read_text().splitlines()
                 if json.loads(line)["kind"] == "kill"]
        self.assertTrue(kills)
        kill = kills[-1]
        self.assertEqual(kill["why"], "hung")
        self.assertTrue(scan_returned)
        self.assertGreaterEqual(kill["last_event_t"], scan_returned[0])
        self.assertGreaterEqual(kill["kill_t"] - scan_returned[0], 0.4)

    def test_an_idle_timeout_freezes_last_event_before_shutdown_output(self):
        eng = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)), verbose=False, store=self.store)
        p = FakeCheckProc()
        p.emit("productive output\n")

        def stop(proc):
            proc.stop("shutdown output after timeout\n")

        with mock.patch.object(engine.subprocess, "Popen", return_value=p), \
                mock.patch.object(engine.procs, "kill_tree", side_effect=stop), \
                mock.patch.object(engine.cs, "activity", return_value=False):
            rc, tail = eng.sh("fake-check", timeout=0.4, idle=10)
        self.assertEqual(rc, 124)
        self.assertIn("shutdown output after timeout", tail)
        kills = [json.loads(line) for line in eng.log_path.read_text().splitlines()
                 if json.loads(line)["kind"] == "kill"]
        self.assertTrue(kills)
        kill = kills[-1]
        self.assertEqual(kill["why"], "timeout")
        self.assertIsNotNone(kill["last_event_t"])
        self.assertIsNotNone(kill["kill_t"])
        self.assertEqual(kill["observed_t"], kill["kill_t"])
        self.assertLess(kill["last_event_t"], kill["kill_t"])
        self.assertGreaterEqual(kill["kill_t"] - kill["last_event_t"], 0.2)

    def test_an_idle_interruption_freezes_last_event_before_shutdown_output(self):
        eng = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)), verbose=False, store=self.store)
        p = FakeCheckProc()
        p.emit("productive output\n")

        def stop(proc):
            proc.stop("shutdown output after interrupt\n")

        with mock.patch.object(engine.subprocess, "Popen", return_value=p), \
                mock.patch.object(engine.procs, "kill_tree", side_effect=stop), \
                mock.patch.object(engine.cs, "activity", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                eng.sh("fake-check", timeout=10, idle=10)
        self.assertTrue(p.shutdown_sent)
        kills = [json.loads(line) for line in eng.log_path.read_text().splitlines()
                 if json.loads(line)["kind"] == "kill"]
        self.assertTrue(kills)
        kill = kills[-1]
        self.assertEqual(kill["why"], "interrupted")
        self.assertIsNotNone(kill["last_event_t"])
        self.assertIsNotNone(kill["kill_t"])
        self.assertEqual(kill["observed_t"], kill["kill_t"])
        self.assertLess(kill["last_event_t"], kill["kill_t"])
        self.assertGreaterEqual(kill["kill_t"] - kill["last_event_t"], 0.2)

    def test_a_stopped_delegate_worker_that_survives_still_leaves_a_kill_record(self):
        eng = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)), verbose=False, store=self.store)

        class Survivor(fake_route.Script):  # the engine ended the call, and the worker outlived every signal
            def reply(this, *a, **kw):
                this.stop = {"alive": [4242], "why": "timeout 1 min"}
                raise dl.Stopped("timeout 1 min")
        with te.delegate_stack(Survivor({})):
            with self.assertRaises(engine.Blocked):
                eng._ai("plan", "title", "prompt")
        kills = [json.loads(line) for line in eng.log_path.read_text().splitlines()
                 if json.loads(line)["kind"] == "kill"]
        self.assertTrue(kills)
        self.assertEqual(kills[-1]["alive"], [4242])
        self.assertEqual(kills[-1]["why"], "timeout 1 min")

    def test_run_proc_reports_observed_error_and_kill_boundaries(self):
        log = self.wt / "observed.log"
        code = "import sys,time; sys.stderr.write('error: boom\\n'); sys.stderr.flush(); time.sleep(10)"
        stop, obs = {}, {}
        res, _ = engine.procs.run_proc([sys.executable, "-c", code], str(self.wt), 0.4, log, stop=stop, obs=obs)
        self.assertIsNone(res)
        self.assertIsNotNone(obs["first_error_t"])
        self.assertIsNotNone(obs["last_event_t"])
        self.assertIsNotNone(obs["kill_t"])
        self.assertGreaterEqual(obs["kill_t"] - obs["first_error_t"], 0.2)
        self.assertGreaterEqual(obs["ended_t"], obs["kill_t"])
        self.assertEqual(stop["why"], obs["why"])

    def test_shutdown_output_after_a_timeout_does_not_move_observed_boundaries(self):
        log = self.wt / "shutdown.log"
        code = (
            "import signal,sys,time\n"
            "def bye(*_):\n"
            "    sys.stderr.write('shutdown error: late\\n'); sys.stderr.flush(); sys.exit(0)\n"
            "signal.signal(signal.SIGTERM, bye)\n"
            "sys.stderr.write('error: boom\\n'); sys.stderr.flush()\n"
            "time.sleep(10)\n"
        )
        stop, obs = {}, {}
        res, _ = engine.procs.run_proc([sys.executable, "-c", code], str(self.wt), 0.4, log, stop=stop, obs=obs)
        self.assertIsNone(res)
        self.assertIn("shutdown error: late", log.read_text())
        self.assertIsNotNone(obs["first_error_t"])
        self.assertIsNotNone(obs["last_event_t"])
        self.assertIsNotNone(obs["kill_t"])
        self.assertLessEqual(obs["first_error_t"], obs["kill_t"])
        self.assertLessEqual(obs["last_event_t"], obs["kill_t"])

    def test_a_delegate_interruption_leaves_a_kill_record(self):
        class Interrupted(fake_route.Script):  # ctrl-C while the worker ran: the runner kept what it saw
            def reply(this, *a, **kw):
                this.stop.update(why="interrupted", alive=[4242])
                this.obs.update(started_t=100.0, ended_t=102.0, first_error_t=100.5, last_event_t=101.0,
                                kill_t=101.5, why="interrupted", alive=[4242])
                raise KeyboardInterrupt()

        eng = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)), verbose=False, store=self.store)
        with te.delegate_stack(Interrupted({})):
            with self.assertRaises(KeyboardInterrupt):
                eng._ai("plan", "title", "prompt")
        kills = [json.loads(line) for line in eng.log_path.read_text().splitlines()
                 if json.loads(line)["kind"] == "kill"]
        self.assertTrue(kills)
        self.assertEqual(kills[-1]["why"], "interrupted")
        self.assertEqual(kills[-1]["alive"], [4242])
        self.assertEqual(kills[-1]["kill_t"], 101.5)
        self.assertEqual(kills[-1]["last_event_t"], 101.0)


if __name__ == "__main__":
    unittest.main()
