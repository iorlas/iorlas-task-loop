"""Engine tests, part 2: the small classes after EngineTest (failure brief, outcome, delegate launcher, stored briefs, confirms, validate). Split from test_engine."""
import atexit
import hashlib
import io
import functools
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import contextlib
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
import applog  # noqa: E402
import delegate_link as dl  # noqa: E402,F401
from clock import FakeClock  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
from support.builders import make_engine  # noqa: E402
import engine  # noqa: E402
import seams  # noqa: E402
from support.fakes import FakeBeadStore  # noqa: E402
from support.waits import until  # noqa: E402
from support import fake_route  # noqa: E402
import lane_policy as lp  # noqa: E402,F401
import netgate  # noqa: E402,F401
from checks import lint  # noqa: E402,F401
from core import procs  # noqa: E402,F401
import tl  # noqa: E402
from lanes import call as lcall  # noqa: E402,F401
from lanes import route as lroute  # noqa: E402,F401
import test_engine as T  # noqa: E402
from test_engine import BRIEFS, CLEAN, PLAN, WRITE, finding, full, review, sh, shown, stop, stored_brief, verdict  # noqa: E402


class FailureBriefAndDurations(unittest.TestCase):
    FIX = Path(__file__).parent / "fixtures" / "checks"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {"HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / "cfg"),
                                                "APPDATA": str(self.home / "cfg")})
        self.env.start()
        self.run_dir = self.home / "run"
        (self.run_dir / "checks").mkdir(parents=True)
        for f in self.FIX.glob("*.log"):
            (self.run_dir / "checks" / f.name).write_text(f.read_text())

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_analyzer_noise_is_dropped_and_the_real_error_comes_first(self):
        out = engine.failure_brief([dict(cmd="c", exit=1, log="checks/unity-analyzers.log")], self.run_dir, lines=2)
        self.assertIn("error MA0051", out)
        self.assertNotIn("UAC0005", out)

    def test_zero_errors_line_is_not_a_hit(self):
        out = engine.failure_brief([dict(cmd="c", exit=1, log="checks/unity-analyzers.log")], self.run_dir)
        self.assertEqual(out.count("0 Error(s)"), 1)  # only as the log's last line, never ranked as an error

    def test_a_timeout_says_so_and_keeps_the_logs_last_line(self):
        out = engine.failure_brief([dict(cmd="just check", exit=124, secs=600, log="checks/timeout.log")], self.run_dir)
        self.assertIn("timed out after 600 s", out)
        self.assertIn("(timed out after 600 s: the engine stopped it", out)
        killed = engine.failure_brief([dict(cmd="just check", exit=-9, secs=30, log="checks/timeout.log")], self.run_dir)
        self.assertIn("timed out after 30 s", killed)

    def test_a_missing_log_says_none_and_a_long_cmd_is_cut(self):
        out = engine.failure_brief([dict(cmd="x" * 500, exit=1, tail="boom: error")], self.run_dir)
        self.assertIn("log: none", out)
        self.assertNotIn("x" * 301, out)

    def test_the_last_traceback_frame_is_kept(self):
        (self.run_dir / "tb.log").write_text(
            'Traceback (most recent call last):\n  File "a.py", line 1, in <module>\n    f()\n'
            '  File "b.py", line 9, in f\n    g()\nValueError: bad\n')
        out = engine.failure_brief([dict(cmd="c", exit=1, log="tb.log")], self.run_dir)
        self.assertIn('File "b.py", line 9, in f\n    g()', out)

    def _runs(self, *items):
        d = self.home / "cfg" / "task-loop" / "runs" / ("r%d" % len(list((self.home / "cfg" / "task-loop").glob("runs/*"))))
        d.mkdir(parents=True)
        (d / "engine-checks.json").write_text(json.dumps(list(items)))

    def _secs(self):
        e = mock.Mock(log_path=self.home / "none" / "t-1.jsonl", bead="t")
        return engine.Engine.check_secs(e, self.home / "cfg" / "task-loop")

    def test_durations_come_from_all_runs_and_a_quick_failure_does_not_hide_a_slow_pass(self):
        self._runs({"cmd": "just  unity-analyzers", "exit": 0, "secs": 140})
        self._runs({"cmd": "just unity-analyzers", "exit": 1, "secs": 9})
        self._runs({"cmd": "just lint", "exit": 1, "secs": 40}, {"cmd": "just lint", "exit": 1, "secs": 7})
        cache = self.home / "cfg" / "task-loop" / "check-cache"
        cache.mkdir()
        (cache / "b.json").write_text(json.dumps({"k": {"just fmt": {"cmd": "just fmt", "exit": 0, "secs": 3}}}))
        secs = self._secs()
        self.assertEqual(secs["just unity-analyzers"], 140)
        self.assertEqual(secs["just lint"], 40)  # nothing passed: the longest run
        self.assertEqual(secs["just fmt"], 3)
        e = mock.Mock(cfg={"writer_check_max_s": 60})
        self.assertTrue(engine.Engine.engine_only(e, "just unity-analyzers", secs))
        self.assertFalse(engine.Engine.engine_only(e, "just lint", secs))

    def test_check_build_and_dotnet_commands_without_history_are_engine_only(self):
        e = mock.Mock(cfg={"writer_check_max_s": 60})
        for cmd in ("just check", "dotnet test", "dotnet build", "just build"):
            self.assertTrue(engine.Engine.engine_only(e, cmd, {}), cmd)


class Outcome(unittest.TestCase):
    """What run-task tells the loop (tl loop): landed, parked, paused, failed or taken, as one JSON record."""
    setUp, tearDown, fake_bd, run_engine, said = T.EngineTest.setUp, T.EngineTest.tearDown, T.EngineTest.fake_bd, T.EngineTest.run_engine, T.EngineTest.said

    def test_an_owner_ask_is_parked(self):
        self.run_engine({"plan": [dict(PLAN, irreversible="push_shared", question="Old format or new?")]})
        r = self.eng.result()
        self.assertEqual((r["outcome"], r["asked"]), ("parked", True))

    def test_a_lane_out_for_long_is_paused_with_the_time_the_lane_is_back(self):
        due = time.time() + 3 * 3600
        self.run_engine({"plan": [PLAN], "write": [stop("rate_limited", at=due, say="out")]})
        r = self.eng.result()
        self.assertEqual(r["outcome"], "paused")
        self.assertAlmostEqual(r["retry_after"], due, delta=1)

    def test_a_logged_out_worker_is_paused_with_no_time(self):
        out = stop("logged_out", family="claude", say="Failed to authenticate")
        self.run_engine({"plan": [out]})
        r = self.eng.result()
        self.assertEqual((r["outcome"], r["retry_after"], r["asked"]), ("paused", 0, False))

    def test_an_engine_error_is_failed(self):
        with mock.patch.object(engine.Engine, "plan", side_effect=RuntimeError("boom")):
            self.run_engine({})
        r = self.eng.result()
        self.assertEqual(r["outcome"], "failed")
        self.assertIn("boom", r["why"])

    def main(self, outcome_file, **kw):
        a = mock.Mock(id="t-1", worktree=str(Path(self.tmp.name, "slot")), slot=None, dry_run=False, fresh=False,
                      quiet=True, outcome_file=str(outcome_file))
        Path(a.worktree).mkdir(exist_ok=True)
        out = io.StringIO()
        with mock.patch.object(tl, "repo_root", return_value=str(self.wt)), redirect_stdout(out), \
                mock.patch.object(signal, "signal"):
            rc = engine.main(a)
        last = json.loads(out.getvalue().strip().splitlines()[-1])
        return rc, json.loads(Path(outcome_file).read_text()), last

    def test_run_task_writes_the_outcome_file_and_ends_with_it_as_a_json_line(self):
        f = Path(self.tmp.name, "out.json")
        made = mock.Mock()
        made.return_value.run.return_value = 0
        made.return_value.result.return_value = {"outcome": "landed", "bead": "t-1"}
        with mock.patch.object(engine, "reclaim", return_value=(True, "")), \
                mock.patch.object(tl, "cmd_claim", return_value=0), mock.patch.object(engine, "Engine", made):
            rc, rec, last = self.main(f)
        self.assertEqual((rc, rec["outcome"], last["outcome"]), (0, "landed", "landed"))

    def test_a_hand_run_pause_prints_the_exact_resume_time_and_ends_with_the_outcome(self):
        due = time.time() + 1800
        made = mock.Mock()
        made.return_value.run.return_value = 2
        made.return_value.result.return_value = {"outcome": "paused", "bead": "t-1", "retry_after": due,
                                                 "why": "paused: no lane for write until 09:36"}
        a = mock.Mock(id="t-1", worktree=str(Path(self.tmp.name, "slot")), slot=None, dry_run=False, fresh=False,
                      quiet=True, outcome_file=None)
        Path(a.worktree).mkdir(exist_ok=True)
        out = io.StringIO()
        with mock.patch.object(engine, "reclaim", return_value=(True, "")), mock.patch.object(tl, "cmd_claim", return_value=0), \
                mock.patch.object(engine, "Engine", made), mock.patch.object(tl, "repo_root", return_value=str(self.wt)), \
                redirect_stdout(out), mock.patch.object(signal, "signal"):
            engine.main(a)
        lines = out.getvalue().strip().splitlines()
        self.assertEqual(json.loads(lines[-1])["retry_after"], due)  # the loop reads the last line: still the outcome
        self.assertTrue(any("PAUSED t-1: the lane is back at %s; rerun then: tl run-task t-1"
                            % time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(due)) in ln for ln in lines), lines)

    def test_a_pause_with_no_time_says_so(self):
        self.assertIn("no time", engine.pause_line({"outcome": "paused", "bead": "t-1", "retry_after": 0}))
        self.assertEqual(engine.pause_line({"outcome": "landed", "bead": "t-1"}), "")

    def test_a_refused_claim_is_taken_and_keeps_exit_1(self):
        f = Path(self.tmp.name, "out.json")
        with mock.patch.object(engine, "reclaim", return_value=(False, "claimed by denis")):
            rc, rec, last = self.main(f)
        self.assertEqual((rc, rec["outcome"]), (1, "taken"))
        self.assertIn("denis", rec["why"])


class DelegateLauncher(unittest.TestCase):
    setUp, tearDown, fake_bd, run_engine, said = T.EngineTest.setUp, T.EngineTest.tearDown, T.EngineTest.fake_bd, T.EngineTest.run_engine, T.EngineTest.said

    def test_same_family_review_is_recorded(self):
        same = full(CLEAN, "r", family="openai", flag="same_family")
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [same]})
        self.assertEqual(rc, 0)
        self.assertTrue(any(c[:2] == ("comments", "add") and "same family as the writer" in c[3] for c in self.bd_calls))

    def test_lane_out_waits_then_runs(self):
        out = stop("rate_limited", at=time.time() + 30, say="codex out")
        rc, s = self.run_engine({"plan": [PLAN], "write": [out, WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        self.assertEqual([c[0] for c in s.calls].count("worker"), 2)

    # lifesim-d5f.58 2026-10-21: a resumed Codex writer answered lane_out for an hour and the bead paused; delegate never
    # switches lanes on a resume, but a fresh call gets the role's next rung (Sonnet on the claude lane) at once
    OUT_LONG = stop("rate_limited", at=time.time() + 3600, say="cannot continue t now")
    FRESH = full(WRITE, "w2", fallback=True, first_lane="OPENAI_SUBSCRIPTION")  # delegate says the writer fell back off its first lane

    def test_a_resumed_write_whose_lane_is_out_goes_on_at_once_as_a_new_thread(self):
        with self.lanes(OPENAI_SUBSCRIPTION=True):
            rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, self.OUT_L, self.FRESH, self.FRESH],
                                     "review": [review(unmet=["more"]), review(unmet=["more"]), CLEAN]})
        self.assertEqual(rc, 0, self.blocked)  # no wait: the lane is out for an hour, past lane_wait_min
        workers = [(c, p) for c, p in zip(s.calls, s.prompts) if c[0] == "worker"]
        self.assertEqual([c[1] for c, _ in workers], [None, "ref-write", None, "w2"])  # Codex still out: resumed
        self.assertEqual([c[2] for c in s.calls if c[0] == "reviewer"], ["openai", "claude", "claude"])
        self.assertNotIn(engine.FRESH_WRITER_TEXT, workers[1][1])
        self.assertIn(engine.FRESH_WRITER_TEXT, workers[2][1])
        self.assertNotIn(engine.FRESH_WRITER_TEXT, workers[3][1])
        self.assertIn("lane_out", self.eng.log_path.read_text())

    # tl-bxk.10.5 2026-10-21: after a real outage the Sonnet thread stayed the writer for every later round of
    # lifesim-fld.27.7, d5f.33, 1eg2 and d5f.54 while Codex was usable again
    BACK = full(WRITE, "w3", family="openai", lane="OPENAI_SUBSCRIPTION", model="gpt")
    OUT_L = dict(OUT_LONG, lane="OPENAI_SUBSCRIPTION")

    def transitions(self):
        return [json.loads(ln) for ln in self.eng.log_path.read_text().splitlines() if '"transition"' in ln]

    def lanes(self, **out):
        """`route.py status --json` lanes: name -> {out}."""
        return mock.patch.object(lroute, "lane_status", return_value={k: {"out": v} for k, v in out.items()})

    def test_a_fallback_writer_is_asked_fresh_once_its_lane_is_back_and_codex_takes_over(self):
        with self.lanes(OPENAI_SUBSCRIPTION=False, CLAUDE_SUBSCRIPTION=False):
            rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, self.OUT_L, self.FRESH, self.BACK, WRITE],
                                     "review": [review(unmet=["more"])] * 3 + [CLEAN]}, max_rounds=5)
        self.assertEqual(rc, 0, self.blocked)
        workers = [(c, p) for c, p in zip(s.calls, s.prompts) if c[0] == "worker"]
        # round 3: Codex's lane is back, so delegate routes afresh; round 4 resumes Codex's new thread
        self.assertEqual([c[1] for c, _ in workers], [None, "ref-write", None, None, "w3"])
        self.assertIn(engine.FRESH_WRITER_TEXT, workers[3][1])
        self.assertNotIn(engine.FRESH_WRITER_TEXT, workers[4][1])
        self.assertEqual([c[2] for c in s.calls if c[0] == "reviewer"], ["openai", "claude", "openai", "openai"])
        self.assertTrue(any(t["cause"] == "fallback_retake" and t["to"] == "write" for t in self.transitions()))

    def test_a_fallback_writer_is_resumed_while_its_lane_is_still_out(self):
        with self.lanes(OPENAI_SUBSCRIPTION=True, CLAUDE_SUBSCRIPTION=False):
            rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, self.OUT_L, self.FRESH, self.FRESH],
                                     "review": [review(unmet=["more"])] * 2 + [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[1] for c in s.calls if c[0] == "worker"], [None, "ref-write", None, "w2"])
        self.assertFalse(any(t["cause"] == "fallback_retake" for t in self.transitions()))

    def test_a_lane_the_status_does_not_know_never_makes_a_fallback(self):
        with self.lanes(CLAUDE_SUBSCRIPTION=False):  # Codex is not configured on this machine at all
            rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, self.OUT_L, self.FRESH, self.FRESH],
                                     "review": [review(unmet=["more"])] * 2 + [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[1] for c in s.calls if c[0] == "worker"], [None, "ref-write", None, "w2"])

    def test_the_first_choice_writer_still_resumes_and_no_status_is_read(self):
        with mock.patch.object(lroute, "lane_status") as st:
            rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, WRITE, WRITE],
                                     "review": [review(unmet=["more"]), review(unmet=["more"]), CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[1] for c in s.calls if c[0] == "worker"], [None, "ref-write", "ref-write"])
        st.assert_not_called()

    def test_a_fallback_writer_is_retaken_in_the_next_run_once_its_lane_is_back(self):
        with self.lanes(OPENAI_SUBSCRIPTION=True):
            busy = stop("no_lane", family="claude")
            rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, self.OUT_L, self.FRESH, busy],
                                     "review": [review(unmet=["more"]), review(unmet=["more"])]})
        self.assertEqual(rc, 2)  # round 3 resumed the fallback (Codex still out) and paused
        ck = json.loads((tl.config_dir() / "checkpoints" / "t-1.json").read_text())
        self.assertEqual((ck["writer"], ck["fallback_lane"]), ("w2", "OPENAI_SUBSCRIPTION"))
        with self.lanes(OPENAI_SUBSCRIPTION=False):
            rc, s = self.run_engine({"write": [self.BACK], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(s.calls[0][:2], ("worker", None))
        self.assertIn(engine.FRESH_WRITER_TEXT, s.prompts[0])
        self.assertEqual(s.calls[1], ("reviewer", None, "openai"))

    # contract 3: an answer that picked a lane says whether it is a fallback (and from which first lane, when it can)
    SONNET_FB = dict(FRESH, rung=1, fallback=True, fallback_reason="ceiling", first_lane="OPENAI_SUBSCRIPTION")
    CODEX_FIRST = dict(BACK, rung=0, fallback=False, fallback_reason=None)
    no_checks = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[])])  # FRESH writes no f.txt

    def test_the_answer_a_fallback_answer_is_retaken_fresh_once_its_first_lane_is_back(self):
        with self.lanes(OPENAI_SUBSCRIPTION=False):
            rc, s = self.run_engine({"plan": [self.no_checks], "write": [self.SONNET_FB, self.CODEX_FIRST, self.CODEX_FIRST],
                                     "review": [review(unmet=["more"])] * 2 + [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[1] for c in s.calls if c[0] == "worker"], [None, None, "w3"])
        self.assertEqual([c[2] for c in s.calls if c[0] == "reviewer"], ["claude", "openai", "openai"])

    def test_the_answer_a_fallback_answer_is_resumed_while_its_first_lane_is_out(self):
        with self.lanes(OPENAI_SUBSCRIPTION=True):
            rc, s = self.run_engine({"plan": [self.no_checks], "write": [self.SONNET_FB, self.SONNET_FB],
                                     "review": [review(unmet=["more"]), CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[1] for c in s.calls if c[0] == "worker"], [None, "w2"])

    def test_the_answer_a_fallback_answer_with_no_lane_known_is_asked_fresh_next_round(self):
        anon = dict(self.SONNET_FB)
        anon.pop("first_lane")
        with mock.patch.object(lroute, "lane_status") as st:
            rc, s = self.run_engine({"plan": [self.no_checks], "write": [anon, self.CODEX_FIRST],
                                     "review": [review(unmet=["more"]), CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[1] for c in s.calls if c[0] == "worker"], [None, None])
        st.assert_not_called()

    def test_the_answer_a_first_choice_answer_is_resumed(self):
        with mock.patch.object(lroute, "lane_status") as st:
            rc, s = self.run_engine({"plan": [self.no_checks], "write": [self.CODEX_FIRST, self.CODEX_FIRST],
                                     "review": [review(unmet=["more"]), CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[1] for c in s.calls if c[0] == "worker"], [None, "w3"])
        st.assert_not_called()

    def test_lane_status_reads_route_status_json(self):
        out = json.dumps({"v": 1, "lanes": {"OPENAI_SUBSCRIPTION": {"out": True}}})
        with mock.patch.object(engine.subprocess, "run", return_value=mock.Mock(returncode=0, stdout=out + "\n")) as run:
            self.assertEqual(lroute.lane_status("/r/route.py"), {"OPENAI_SUBSCRIPTION": {"out": True}})
        self.assertEqual(run.call_args[0][0][1:], ["/r/route.py", "status", "--json"])
        with mock.patch.object(engine.subprocess, "run", side_effect=OSError("gone")):
            self.assertEqual(lroute.lane_status("/r/route.py"), {})

    # lifesim-5ar.6 2026-10-21: the resumed writer's lane_out came with no retry_after, so next was owner, and the bead
    # blocked "needs a human" after 114 min of work
    OUT_OWNER = stop("rate_limited", say="cannot say when OPENAI_SUBSCRIPTION frees")

    def test_a_resumed_write_whose_lane_is_out_with_no_time_goes_on_at_once_as_a_new_thread(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, self.OUT_OWNER, self.FRESH],
                                 "review": [review(unmet=["more"]), CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        workers = [(c, p) for c, p in zip(s.calls, s.prompts) if c[0] == "worker"]
        self.assertEqual([c[1] for c, _ in workers], [None, "ref-write", None])
        self.assertIn(engine.FRESH_WRITER_TEXT, workers[2][1])

    def test_a_new_thread_whose_lane_is_out_with_no_time_pauses_without_an_ask(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, self.OUT_OWNER, self.OUT_OWNER],
                                 "review": [review(unmet=["more"])]})
        self.assertEqual(rc, 2)
        # the resumed thread's lane is out: a new thread; that lane out too, with no time: the pause
        self.assertEqual([c[1] for c in s.calls if c[0] == "worker"], [None, "ref-write", None])
        self.assertEqual(self.blocked, [])
        self.assertTrue(any(c[:3] == ("comments", "add", "t-1") and any("paused: no lane for write" in x for x in c)
                            for c in self.bd_calls))
        self.assertNotIn("needs a human", self.eng.log_path.read_text())

    def test_a_resumed_write_told_busy_polls_and_goes_on(self):
        busy = stop("busy", "ref-write", say="state lock held")
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, busy, WRITE], "review": [review(unmet=["more"]), CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[1] for c in s.calls if c[0] == "worker"], [None, "ref-write", None])

    def test_the_writer_brief_has_no_sandbox_or_git_text(self):
        # delegate 0.29 owns what the worker is told about its sandbox, escalation and git (worker-run v2)
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        w = next(p for (c, p) in zip(s.calls, s.prompts) if c[0] == "worker")
        for gone in ("sandbox", "escalat", "permissions", "You have the host", "no commits", "no pushing"):
            self.assertNotIn(gone, w, gone)
        self.assertIn("Never run the gate", w)

    def test_network_down_waits_and_retries(self):
        down = stop("network", "ref-review", say="ENOTFOUND api.anthropic.com")
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [down, CLEAN]})
        self.assertEqual(rc, 0)
        self.assertEqual([c[0] for c in s.calls].count("reviewer"), 2)
        self.assertIn("network", self.eng.log_path.read_text())

    # lifesim 2026-10-20: woken from sleep, Codex ended its turn after 12 s with a vendor error and no tokens; delegate
    # 0.26 answered failed and the engine closed two beads as failed
    QUICK = stop("vendor_blip", "w1", say="codex failed before any work: workspace routing discovery failed")

    def test_a_failure_before_any_work_waits_and_retries(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [self.QUICK, self.QUICK, WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls].count("worker"), 3)
        log = self.eng.log_path.read_text()
        self.assertIn("vendor_blip", log)
        self.assertNotIn("did not match the required output schema", "".join(s.prompts))

    def test_a_failure_before_any_work_that_keeps_coming_pauses_the_bead_open(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [self.QUICK] * 4 + [stop("no_lane", say="every lane is out")]})
        self.assertEqual(rc, 2)
        self.assertEqual(self.blocked, [])  # paused, not failed: the bead stays open for the next run
        self.assertTrue(any(c[:1] == ("update",) and "open" in c for c in self.bd_calls))
        self.assertIn("workspace routing discovery failed", self.eng.log_path.read_text())
        self.assertEqual([c[0] for c in s.calls].count("worker"), 5)  # three polls, one other pick, then the pause

    # tl-bxk.10.22: the dashboard says which lane a run waits for and until when
    def test_a_wait_for_a_lane_records_the_lane_and_when_it_ends(self):
        out = stop("rate_limited", at=time.time() + 120, lane="OPENAI_SUBSCRIPTION")
        rc, s = self.run_engine({"plan": [PLAN], "write": [out, WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        waits = [json.loads(ln) for ln in self.eng.log_path.read_text().splitlines() if '"lane_wait"' in ln and '"transition"' in ln]
        self.assertEqual([w["lane"] for w in waits], ["OPENAI_SUBSCRIPTION"])
        self.assertGreater(waits[0]["until"], time.time() + 30)

    def test_a_failure_after_work_still_fails(self):
        worked = stop("worker_failed", tokens={"in": 90000, "cached": 0, "out": 4000}, say="codex: turn failed")
        rc, s = self.run_engine({"plan": [PLAN], "write": [worked, worked]})
        self.assertEqual(rc, 2)
        self.assertTrue(self.said().startswith("Engine failed:"), self.said())

    LOGIN_CLAUDE = "run `claude auth login`"

    def test_a_logged_out_worker_pauses_without_retry_and_leaves_the_bead_open(self):
        out = stop("logged_out", family="claude", say="Failed to authenticate: OAuth session expired", fix=self.LOGIN_CLAUDE)
        rc, s = self.run_engine({"plan": [out, out]})
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in s.calls], ["planner"])
        self.assertEqual(self.blocked, [])
        self.assertTrue(any(c[:1] == ("update",) and "open" in c for c in self.bd_calls))
        self.assertIn("claude auth login", self.eng.log_path.read_text())

    # contract 3: logged_out is lane / needs_owner: the lane waits for its owner, the step never retries it and never asks
    def test_a_logged_out_lane_pauses_with_the_login_fix_and_no_ask(self):
        out = stop("logged_out", family="claude", say="claude is not logged in", fix=self.LOGIN_CLAUDE)
        rc, s = self.run_engine({"plan": [PLAN], "write": [out, WRITE]})
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in s.calls].count("worker"), 1)
        self.assertEqual((self.blocked, (tl.config_dir() / "asks" / "t-1.json").exists()), ([], False))
        self.assertTrue(any(c[:3] == ("comments", "add", "t-1") and any("run `claude auth login`" in x for x in c)
                            for c in self.bd_calls))

    def test_a_resumed_write_on_a_logged_out_lane_pauses_without_an_ask(self):
        out = stop("logged_out", "ref-write", family="openai", say="codex login", fix="run `codex login`")
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, out], "review": [review(unmet=["more"])]})
        self.assertEqual(rc, 2)
        self.assertEqual(self.blocked, [])
        self.assertEqual([c[1] for c in s.calls if c[0] == "worker"], [None, "ref-write"])
        self.assertTrue(any(c[:3] == ("comments", "add", "t-1") and any("run `codex login`" in x for x in c)
                            for c in self.bd_calls))

    def test_every_lane_out_with_no_time_pauses_a_resumed_write_without_an_ask(self):
        none = stop("no_lane", say="every lane is out")
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, self.OUT_OWNER, none],
                                 "review": [review(unmet=["more"])]})
        self.assertEqual(rc, 2)
        self.assertEqual([c[1] for c in s.calls if c[0] == "worker"], [None, "ref-write", None])
        self.assertEqual(self.blocked, [])
        self.assertTrue(any(c[:3] == ("comments", "add", "t-1") and any("paused: no lane for write" in x for x in c)
                            for c in self.bd_calls))
        self.assertNotIn("needs a human", self.eng.log_path.read_text())

    def test_every_lane_out_with_a_time_pauses_until_it(self):
        due = time.time() + 3 * 3600
        none = stop("no_lane", at=due, say="every lane is out")
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, self.OUT_OWNER, none],
                                 "review": [review(unmet=["more"])]})
        self.assertEqual(rc, 2)
        self.assertEqual(self.blocked, [])
        self.assertAlmostEqual(self.eng.retry_after, due, delta=1)

    def test_close_with_an_empty_reason_still_closes(self):
        c = engine.load_cfg(str(self.wt))
        eng = engine.Engine("t-1", str(self.wt), c, store=self.store)
        eng.close("failed", "", "", "")
        self.assertTrue(self.blocked)

    def test_no_lane_pauses_the_bead_open(self):
        none = stop("no_lane", say="no adequate model")
        rc, _ = self.run_engine({"plan": [none]})
        self.assertEqual(rc, 2)
        self.assertEqual(self.blocked, [])  # a machine-wide wait is not the bead's fault: it stays open
        self.assertTrue(any(c[:3] == ("comments", "add", "t-1") and any("paused: no lane for plan" in x for x in c)
                            for c in self.bd_calls))

    def test_a_lane_out_for_long_pauses_at_once_and_frees_the_slot(self):
        later = stop("rate_limited", at=time.time() + 3 * 3600, say="codex out until 21:00")
        rc, s = self.run_engine({"plan": [PLAN], "write": [later]})
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in s.calls].count("worker"), 1)  # no hour of sleeping in the slot
        self.assertEqual(self.blocked, [])
        self.assertTrue(any(c[:3] == ("comments", "add", "t-1") and any("paused: no lane for write until" in x for x in c)
                            for c in self.bd_calls))

    def test_a_bead_branch_left_in_another_clean_slot_is_resumed_here(self):
        sh("git", "checkout", "-q", "-b", "task/t-1", cwd=self.wt)
        Path(self.wt, "g.txt").write_text("from slot s2\n")
        sh("git", "add", "-A", cwd=self.wt)
        sh("git", "commit", "-qm", "wip (t-1): paused", cwd=self.wt)
        sh("git", "checkout", "-q", "--detach", cwd=self.wt)
        other = Path(self.tmp.name, "s2")
        sh("git", "worktree", "add", "-q", str(other), "task/t-1", cwd=self.wt)
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(tl.git("show", "origin/main:g.txt", cwd=str(self.wt)), "from slot s2")
        self.assertEqual(tl.git("symbolic-ref", "-q", "HEAD", cwd=str(other)), "")  # s2 let go of the branch

    def test_a_bead_branch_with_uncommitted_work_in_another_slot_is_never_taken(self):
        sh("git", "branch", "task/t-1", cwd=self.wt)
        other = Path(self.tmp.name, "s2")
        sh("git", "worktree", "add", "-q", str(other), "task/t-1", cwd=self.wt)
        Path(other, "dirty.txt").write_text("someone's work\n")
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 2)
        self.assertIn(shown(other), self.said())
        self.assertTrue(Path(other, "dirty.txt").exists())

    def test_an_answer_of_another_contract_pauses(self):
        rc, _ = self.run_engine({"plan": [dict(full(PLAN), contract=4)]})
        self.assertEqual(rc, 2)
        self.assertIn("contract_violation", self.said())

    def test_no_delegate_blocks_with_the_install_command(self):
        c = engine.load_cfg(str(self.wt))
        with mock.patch.object(dl, "resolve", return_value=dl.Refusal("not_installed")):
            rc = engine.Engine("t-1", str(self.wt), c, store=self.store).run()
        self.assertEqual(rc, 2)
        self.assertIn("claude plugin update iorlas-delegate", self.said())


ENGINE_LINE = re.compile(r"^(?:- [^:\n]*: )?(?:(?:Lane|Verify|Resume|Look|Land|Plan|Review|Reflect|Ask|Evidence|Follow-up|Parked) \(engine|Blocked:"
                         r"|Engine (?:paused|failed):)")


class StoredBriefs(unittest.TestCase):
    """tl-7y6.6.2: a sample of the stored run briefs (tests/fixtures/briefs, from ~/.config/task-loop/runs/*/brief.md).
    The briefs were written before the fix and 252 of the 405 carried engine lines; each is read back into notes and comments and
    rebuilt through brief_digest, which must leave none of them in."""

    def test_the_sample_has_engine_lines_to_remove(self):
        names = sorted(p.stem for p in BRIEFS.glob("*.md"))
        self.assertGreaterEqual(len(names), 30)
        self.assertGreater(sum(any(ENGINE_LINE.match(l) for l in (BRIEFS / (n + ".md")).read_text().splitlines()) for n in names), 20)
        self.assertLessEqual(sum(p.stat().st_size for p in BRIEFS.glob("*.md")), 200 * 1024)

    def test_no_rebuilt_brief_contains_an_engine_prefixed_line_and_none_is_larger(self):
        for p in sorted(BRIEFS.glob("*.md")):
            notes, comments = stored_brief(p.stem)
            bead = {"id": "x", "title": "t", "notes": notes}
            out = engine.brief_digest(bead, [{"author": a, "text": t} for a, t in comments])
            bad = [l for l in out.splitlines() if ENGINE_LINE.match(l)]
            self.assertEqual(bad, [], p.name)
            old = p.read_text(encoding="utf-8")
            self.assertLessEqual(len(out), len(old) + 200, p.name)  # the sections rebuilt are never larger than as stored


class Confirms(unittest.TestCase):
    def test_a_plain_yes_is_a_confirmation_anything_else_is_work(self):
        for t in ("right", "Right.", "yes, land it", "ok", "LGTM", "correct", "looks good, ship it", "checked: fine"):
            self.assertTrue(engine.confirms(t), t)
        for t in ("", "wrong", "not right", "add a test that X, then land", "right, but rename f", "no",
                  "Link is fine, checked."):
            self.assertFalse(engine.confirms(t), t)

    def test_a_yes_then_only_evidence_or_reasons_confirms(self):
        # lifesim-gfr.31.1: 'Right. <evidence>' replanned and cost a write round
        for t in ("Right. The log shows X.", "Correct. The cache entry is written before the lock is released.",
                  "Yes, the log at /tmp/x shows 3 retries; the link opens.", "right: no errors in the log, it opens fine",
                  "Right.\nThe screenshot shows the menu at 60 fps, because the shader is cached."):
            self.assertTrue(engine.confirms(t), t)
        for t in ("right, but add a test for Y", "wrong: the menu still flickers", "Right. Fix the typo in the doc.",
                  "Yes, also rename f.", "Correct, though the log should name the file.", "Right, don't land yet",
                  "Yes. Please add a case for the empty filter.", "Right? The log shows X.", "Right, it is missing a test.",
                  "yes, change the default to 3", "Right, then remove the debug line."):
            self.assertFalse(engine.confirms(t), t)


class Validate(unittest.TestCase):
    def test_schema_subset(self):
        s = engine.SCHEMAS["review"]
        self.assertEqual(engine.validate(review(findings=[finding("high")]), s), [])
        self.assertTrue(engine.validate(review(findings=[dict(finding("high"), severity="maybe")]), s))
        self.assertTrue(engine.validate({"findings": []}, s))
        self.assertTrue(engine.validate(dict(CLEAN, unmet="x"), s))
        self.assertEqual(sorted(engine.SCHEMAS), ["look", "plan", "reflect", "review", "verify", "write"])
        v = engine.SCHEMAS["verify"]
        self.assertEqual(engine.validate({"items": [verdict(1, "settled", "a.cs:3")]}, v), [])
        self.assertTrue(engine.validate({"items": [verdict(1, "maybe")]}, v))

    def test_every_contract_sent_is_strict_mode_valid(self):
        """Codex (strict structured output) rejects an object whose `required` misses a property: 53 lifesim runs
        stopped on 'Missing source' / 'Missing accept_files' (2026-10-22)."""
        def walk(sch, path):
            if sch.get("type") == "object":
                self.assertIs(sch.get("additionalProperties"), False, path)
                self.assertEqual(sorted(sch.get("required", [])), sorted(sch.get("properties", {})), path)
                for k, v in sch.get("properties", {}).items():
                    walk(v, path + "." + k)
            if sch.get("type") == "array":
                walk(sch.get("items") or {}, path + "[]")
        for node in engine.SCHEMAS:
            for visual in (False, True):
                walk(engine.strict(engine.schema_for(node, visual)), "%s%s" % (node, " (visual)" if visual else ""))

    def test_a_strict_answer_with_null_optionals_validates_against_the_contract(self):
        s = engine.SCHEMAS["review"]
        sent = engine.strict(s)
        self.assertEqual(sent["properties"]["accept_files"]["type"], ["array", "null"])
        got = dict(CLEAN, accept_files=None, reject_files=None,
                   unchecked=[{"what": "x", "kind": "other", "source": None}])
        back = engine.unstrict(got, s)
        self.assertNotIn("accept_files", back)
        self.assertNotIn("source", back["unchecked"][0])
        self.assertEqual(engine.validate(back, s), [])
        self.assertEqual(engine.SCHEMAS["review"], s)  # the contract itself is untouched


if __name__ == "__main__":
    unittest.main()
