"""Engine tests: the run, its resume, stop, budget and log."""
import signal as sig
import sys
from pathlib import Path
from typing import Any, ClassVar

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import procsim
from support.checks import ck
from support.engine_case import (
    BEAD,
    CAP_PARKS,
    CAT_ENV,
    CLEAN,
    FALSE,
    PLAN,
    WRITE,
    EngineTest,
    full,
    no_repo,
    review,
    sh,
    stop,
    verdict,
)

# isort: split
import hashlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from unittest import mock

from support import fake_route
from support.briefs import bead_diff, bead_snapshot, brief_digest, linked_text
from support.builders import cfg_with
from support.checkpoints import stored_ck
from support.fakes import as_bead, as_comment, must_bead
from support.logs import records
from support.spawn import real_spawner

from taskloop.adapters import (
    context_size,
    gitrepo,
    ident,
)
from taskloop.adapters import delegate as dl
from taskloop.app.land.checkout import Checkout
from taskloop.app.plan.planner import Planner
from taskloop.app.release import seams
from taskloop.app.run import (
    engine,
    entry,
    outcomes,
)
from taskloop.app.slots.lease import Lease
from taskloop.app.wire import slots as wslots
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.enums import Result, WaitWhat
from taskloop.contracts.env import snapshot
from taskloop.contracts.ids import BeadId
from taskloop.contracts.kinds import Kind
from taskloop.contracts.run import RunReport
from taskloop.domain.checks import matchers as check_matchers
from taskloop.domain.checks import retry
from taskloop.domain.lanes.matchers import read_only_command
from taskloop.domain.plan.matchers import AcceptanceText
from taskloop.domain.prompts.common import RULES_MAX
from taskloop.domain.write.matchers import count_tests


class EngineRunTest(EngineTest):
    @no_repo
    def test_brief_is_a_digest_without_engine_comments(self):
        bead = {"id": "t-1", "title": "Add f", "metadata": {}, "description": "Add the file f.",
                "acceptance_criteria": "f.txt exists", "notes": "owner: keep it short",
                "dependencies": [{"id": "t-0", "title": "The epic", "description": "x" * 3000}]}
        comments = [{"author": "tl-a", "text": "Plan (engine): " + "p" * 6000},
                    {"author": "tl-a", "text": "Review (engine, stage 1/1): " + "r" * 2000},
                    {"author": "tl-a", "text": "Reflect (engine): outcome=failed; minutes=26"},
                    {"author": "tl-a", "text": "Blocked: failed: stopped (SIGTERM)"},
                    {"author": "denis", "text": "Use the old format, not the new one."}]
        brief = brief_digest(must_bead(bead), [as_comment(c) for c in comments])
        for kept in ("Add the file f.", "f.txt exists", "owner: keep it short", "Use the old format", "t-0 The epic"):
            self.assertIn(kept, brief)
        for dropped in ("p" * 50, "r" * 50, "x" * 50, "minutes=26", "Blocked: failed: stopped", "Last engine run"):  # tl-7y6.6.2
            self.assertNotIn(dropped, brief)
        self.assertLess(len(brief.encode()), 5000)

    def test_engine_files_live_outside_the_worktree_and_stale_ones_are_cleared(self):
        td = self.wt / ".task" / "t-1"
        (td / "evidence").mkdir(parents=True)
        (td / "evidence" / "seen-red.log").write_text("red then green\n")
        (td / "rechecks.json").write_text('{"exit": 124}')  # a writer's sandbox run from an earlier run
        (td / "verify-9.json").write_text("{}")
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(p.name for p in td.iterdir()), ["artifacts", "brief.md", "evidence"])
        self.assertIn("Add f", (td / "brief.md").read_text())  # the copy a resumed writer is pointed to
        self.assertTrue((td / "evidence" / "seen-red.log").exists())
        run = self.eng.run_dir
        self.assertFalse(str(run).startswith(str(self.wt)))
        for f in ("brief.md", "plan.json", "engine-checks.json"):
            self.assertTrue((run / f).exists(), f)
        self.assertIn("Add f", s.prompts[0])  # the brief's text itself: a worker may not read outside its worktree

    def test_a_command_repeated_in_one_block_runs_once(self):
        cmd, n = self.counting_check("ok", ok_after=1)
        eng = self.checks_engine(checks=[{"id": "unit", "cmd": cmd, "group": "tests"}])
        res = eng.run_checks({"checks": ck([cmd, "  " + cmd + "  "]), "files": []}, "s")
        self.assertEqual([c.exit for c in res], [0, 0])  # the two spellings are one adhoc check; it takes the repo check's result
        self.assertEqual([bool(c.reused) for c in res], [False, True])
        self.assertEqual(n.read_text(), "1")

    def test_a_wait_is_not_counted_in_the_budget(self):
        eng = self.checks_engine(budget_min=5)
        eng.t0 -= 8 * 60  # eight minutes wall
        self.assertRaises(engine.Blocked, eng.waits.budget_check)
        eng.waits.add(600, WaitWhat.UNITY_SLOT)  # capped at the 8 min there are: inside the budget
        eng.waits.budget_check()
        eng.t0 -= 16 * 60
        with self.assertRaises(engine.Blocked) as e:
            eng.waits.budget_check()
        self.assertIn("8 min waiting for shared resources not counted", str(e.exception))

    COMPILE: ClassVar[Any] = ["Assets/Foo.cs(180,32): error CS0246: The type or namespace name 'X' could not be found",
               "Assets/Foo.cs(1,1): error CS1002: ; expected",
               "  File \"a.py\", line 1\nSyntaxError: invalid syntax"]

    ECHO = "an editor holds client/; compiling in it"  # lifesim unity-check's normal path (justfile:342)

    @no_repo
    def test_failure_kind_sorts_compile_errors_and_locks(self):
        for line in self.COMPILE:
            self.assertEqual(check_matchers.failure_kind(line), "deterministic", line)
        for line in self.LOCK:
            self.assertEqual(check_matchers.failure_kind(line), "lock", line)
        for line in ("AssertionError: 1 != 2", "Curl error 42", "Connection reset by peer", "", self.ECHO,
                     "error NU1301: Unable to load the service index",
                     "error MSB3021: Unable to copy file",
                     "CSC : error CS0006: Metadata file 'X.dll' could not be found",
                     "CSC : error CS2001: Source file 'A.cs' could not be found",
                     "ModuleNotFoundError: No module named 'foo'", "No such file or directory"):
            self.assertEqual(check_matchers.failure_kind(line), "flaky", line)

    @no_repo
    def test_the_normal_editor_echo_with_a_real_compile_error_is_compile_not_lock(self):
        self.assertEqual(check_matchers.failure_kind(self.ECHO + "\nAssets/A.cs(1,1): error CS1002: ; expected"), "deterministic")

    @no_repo
    def test_lock_waits_are_15_30_60_and_add_up_to_5_min(self):
        w = retry.lock_waits()
        self.assertEqual(w[:4], [15, 30, 60, 60])
        self.assertEqual(sum(w), 300)

    def test_a_compile_error_is_not_retried(self):
        cmd, n = self.counting_check(self.COMPILE[1])
        eng = self.checks_engine(checks=[{"id": "an", "cmd": cmd, "group": "tests", "retry": 3}])
        res = eng.run_checks({"checks": [], "files": []}, "s")
        self.assertEqual((res[0].status, res[0].tries, n.read_text()), ("failed", 1, "1"))

    def test_an_unclassified_failure_keeps_the_retry(self):
        n = Path(self.tmp.name) / "runs-differ"

        def differ(cwd, env):
            k = (int(n.read_text()) if n.exists() else 0) + 1
            n.write_text(str(k))
            return 1, f"AssertionError: {k} != 2"
        eng = self.checks_engine(checks=[{"id": "u", "cmd": procsim.fake("differ", differ), "group": "tests", "retry": 2}])
        res = eng.run_checks({"checks": [], "files": []}, "s")
        self.assertEqual((res[0].tries, n.read_text()), (3, "3"))  # each failure says something else: the retry may change the answer

    def test_a_retry_that_failed_the_same_way_twice_is_not_a_third_run(self):
        cmd, n = self.counting_check("AssertionError: 1 != 2")
        eng = self.checks_engine(checks=[{"id": "u", "cmd": cmd, "group": "tests", "retry": 5}])
        res = eng.run_checks({"checks": [], "files": []}, "s")
        self.assertEqual((res[0].tries, n.read_text()), (2, "2"))

    def test_tests_added_and_removed_come_from_the_diff(self):
        diff = ("+++ b/tests/test_a.py\n+def test_one():\n+    pass\n+def test_two():\n-def test_old():\n"
                "+++ b/T.cs\n+    [Fact]\n+    [Test]\n")
        self.assertEqual(count_tests(diff, EngineConfig().test_pattern), (4, 1))

    def test_gherkin_scenarios_count_in_feature_files_only(self):  # lifesim-fld.26.10: four scenarios read as 0
        diff = ("+++ b/specs/Build.feature\n+  Scenario: a wall is painted\n+    Given a room\n"
                "+  Scenario Outline: <tint> paint\n-  Scenario: an old one\n"
                "+++ b/docs/notes.md\n+Scenario: prose, not a test\n"
                "+++ b/T.cs\n+    [Test]\n")
        self.assertEqual(count_tests(diff, EngineConfig().test_pattern), (3, 1))

    def test_sigterm_still_closes(self):
        if not hasattr(sig, "SIGTERM") or os.name == "nt":
            self.skipTest("POSIX signal")
        with mock.patch.object(Planner, "plan", side_effect=lambda *a, **k: os.kill(os.getpid(), sig.SIGTERM)):
            old = sig.getsignal(sig.SIGTERM)
            sig.signal(
                sig.SIGTERM, lambda *_: (_ for _ in ()).throw(engine.Blocked("failed: stopped (SIGTERM)", kind=Kind.PAUSE_KILLED))
            )
            try:
                rc, _ = self.run_engine({})
            finally:
                sig.signal(sig.SIGTERM, old)
        self.assertEqual(rc, 2)
        self.assertIn("stopped (SIGTERM)", self.said())

    def test_sigterm_between_the_run_and_its_close_still_closes(self):  # it escaped with no trace (M2 review)
        if not hasattr(sig, "SIGTERM") or os.name == "nt":
            self.skipTest("POSIX signal")
        with self.stoppable(), mock.patch.object(Lease, "stop",
                                                 side_effect=lambda *a: os.kill(os.getpid(), sig.SIGTERM)):
            rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        runs = [json.loads(ln) for ln in (ident.config_dir() / "traces.jsonl").read_text().splitlines()]
        self.assertEqual([r["outcome"] for r in runs], ["landed"])

    def test_a_stop_before_the_engine_ran_still_closes_with_a_trace(self):
        with mock.patch.object(engine.Engine, "stop_pending", True, create=True):
            rc, s = self.run_engine({"plan": [PLAN]})
        self.assertEqual((rc, s.calls), (2, []))
        self.assertIn("stopped (SIGTERM)", self.said())
        runs = [json.loads(ln) for ln in (ident.config_dir() / "traces.jsonl").read_text().splitlines()]
        self.assertEqual(runs[-1]["why"], "failed: stopped (SIGTERM)")

    def run_bead_stopped_in(self, where):
        """entry.run_bead with a SIGTERM sent inside `where` (claim or report): the stop waits, the run still reports."""
        if not hasattr(sig, "SIGTERM") or os.name == "nt":
            self.skipTest("POSIX signal")
        said = []

        def claim(*argv):
            if where == "claim" and argv[:1] == ("update",) and "--claim" in argv:
                os.kill(os.getpid(), sig.SIGTERM)
            return mock.Mock(returncode=0, stdout="", stderr="")

        def say(text):
            said.append(text)
            if where == "report" and text.startswith("{"):
                os.kill(os.getpid(), sig.SIGTERM)
        a = mock.Mock(id="t-1", slot=None, dry_run=False, fresh=False, quiet=True, outcome_file=None)
        made = mock.Mock()
        made.return_value.run.return_value = 2
        made.return_value.result.return_value = RunReport(outcome=Result.FAILED, bead=BeadId("t-1"), why="failed: stopped (SIGTERM)")
        made.return_value.stop_pending = False
        with self.stoppable(), mock.patch.object(entry, "Engine", made), \
                mock.patch.object(entry, "reclaim", return_value=(True, "")), \
                self.store.stub(bd_fn=claim), mock.patch.object(entry, "say", side_effect=say):
            rc = entry.run_bead(a, str(self.wt), {}, str(self.wt), self.store, env=snapshot(), spawner=real_spawner())
        return rc, made, said

    def test_a_stop_during_the_claim_waits_and_the_engine_closes_it(self):
        rc, made, said = self.run_bead_stopped_in("claim")
        self.assertEqual(rc, 2)
        self.assertTrue(made.return_value.stop_pending)
        made.return_value.run.assert_called_once()
        self.assertTrue(any(t.startswith("{") for t in said))

    def test_a_stop_during_the_outcome_line_waits_for_it(self):
        rc, _made, said = self.run_bead_stopped_in("report")
        self.assertEqual(rc, 2)
        self.assertTrue(any(t.startswith("{") for t in said))

    def test_the_heartbeat_keeps_the_slot_bead_the_loop_names(self):
        hb = Lease(self.store, "t-1", "sl-1")  # pyrefly: ignore[bad-argument-type]
        with mock.patch.object(hb.stopped, "wait", side_effect=[False, True]):
            hb.run()
        self.assertEqual([c for c in self.bd_calls if c[0] == "heartbeat"], [("heartbeat", "t-1"), ("heartbeat", "sl-1")])

    def test_leftovers_are_filed_once_across_a_resume(self):
        lo = {"title": "Rename x", "why": "found in passing"}
        with self.stop_at("reviewer", 2):
            self.run_engine({"plan": [self.TWO], "write": [WRITE, WRITE], "review": [dict(CLEAN, leftovers=[lo])]})
        self.run_engine({"write": [WRITE], "review": [CLEAN]})
        self.assertEqual(sum(1 for c in self.bd_calls if c[:2] == ("create", "Rename x")), 1)

    def test_a_run_killed_before_its_close_still_resumes_its_own_dirty_tree(self):
        with self.stop_at("reviewer", 2):
            self.run_engine({"plan": [self.TWO], "write": [WRITE, WRITE], "review": [CLEAN]})
        ck = stored_ck()  # as if kill -9: no close, no wip commit
        assert ck is not None
        sh("git", "checkout", "-q", "task/t-1", cwd=self.wt)  # (a parked slot is left detached at the base: back on the bead's branch)
        sh("git", "reset", "-q", "--soft", "HEAD~1", cwd=self.wt)
        self.eng.stores.checkpoints.of("t-1").write(
            ck.replace(closed=False, head=gitrepo.git("rev-parse", "HEAD", cwd=str(self.wt)))
        )
        rc, s = self.run_engine({"write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        self.assertEqual([c[0] for c in s.calls], ["worker", "reviewer"])

    def test_reclaim_releases_a_dead_engine_claim(self):
        ok, _, up = self.reclaim({"status": "in_progress", "assignee": "tl-61ba34e7",
                                  "lease_expires_at": "2020-01-01T00:00:00Z"})
        self.assertTrue(ok)
        self.assertIn(("update", "t-1", "--if-assignee", "tl-61ba34e7", "--assignee", ""), up)  # conditional on the claim just read

    def test_reclaim_refuses_a_live_claim_and_a_persons_claim(self):
        ok, why, up = self.reclaim({"status": "in_progress", "assignee": "tl-61ba34e7",
                                    "lease_expires_at": "2999-01-01T00:00:00Z"})
        self.assertFalse(ok)
        self.assertIn("tl-61ba34e7", why)
        ok, why, up = self.reclaim({"status": "in_progress", "assignee": "denis"})
        self.assertFalse(ok)
        self.assertEqual(up, [])

    def test_the_engines_output_survives_another_writer_truncating_its_log(self):
        # lifesim-gfr.31.1: a second `run-task ... > log` truncated the live run's log; the live engine kept writing at
        # its old offset and the log began with TAKEN and a run of NUL bytes
        if os.name == "nt":
            self.skipTest("POSIX file status flags")
        log = Path(self.tmp.name, "run.log")
        with open(log, "w") as f:
            f.write("CLAIMED t-1\n" * 50)
            f.flush()
            entry.append_output(f)
            with open(log, "w") as other:
                other.write("TAKEN\n")
            f.write("[07:00] review\n")
        self.assertEqual(log.read_bytes(), b"TAKEN\n[07:00] review\n")

    def test_reclaim_reopens_a_bead_the_engine_blocked_on_a_failed_run(self):
        ok, _, up = self.reclaim({"status": "blocked", "assignee": "tl-61ba34e7"}, [self.BLOCKED])
        self.assertTrue(ok)
        self.assertIn(("update", "t-1", "--status", "open", "--if-assignee", "tl-61ba34e7", "--assignee", ""), up)

    ERRORS = "build-errors"  # a procsim fake (registered in the test): 36 compiler errors, red while f.txt reads d2

    @staticmethod
    def build_errors(cwd, env):
        out = "".join(f"src/F.cs({i % 18},1): error CS{i % 18:04d}: analyzer says no\n" for i in range(36)) + "Build FAILED"
        return (1 if procsim.f_txt(cwd) == "d2" else 0), out

    def test_a_fix_brief_carries_every_error_line_and_the_log_path_not_a_400_char_cut(self):
        procsim.fake(self.ERRORS, self.build_errors)
        rc, s = self.run_engine({"plan": [self.plan_with(self.ERRORS)], "write": [WRITE, WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        fix = s.prompts[2]
        for i in range(18):
            self.assertEqual(fix.count(f"src/F.cs({i},1): error CS{int(i):04d}: analyzer says no"), 1, i)
        self.assertIn("Build FAILED", fix)
        self.assertRegex(fix, r"log: \S+checks[\\/]\d\d-.*\.r1\.log")
        self.assertGreater(len(fix[fix.index("These checks fail"):]), 500)

    def test_the_threshold_defaults_by_the_session_family(self):
        _rc, s = self.two_writes(family="openai", ctx_k=90)  # codex: 100, claude would go on to 150
        self.assertEqual(s.calls[2][1], "ref-write")
        _rc, s = self.two_writes(family="openai", ctx_k=110)
        self.assertIsNone(s.calls[2][1])
        self.assertIn("fresh writer: session at 110k", self.eng.log_path.read_text())

    def test_write_fresh_above_k_is_the_repos_to_set(self):
        _rc, s = self.two_writes(ctx_k=60, write_fresh_above_k=50)
        self.assertIsNone(s.calls[2][1])
        _rc, s = self.two_writes(ctx_k=500, write_fresh_above_k=0)  # 0: never
        self.assertEqual(s.calls[2][1], "ref-write")

    def test_a_missing_or_empty_transcript_resumes_as_before(self):
        for path in ("", "/nonexistent/s.jsonl"):
            extra = {"transcript": path}
            with self.store.stub(show=dict(BEAD, description=self.MARK)):
                _rc, s = self.run_engine({"plan": [self.plan_with(self.RED_ONCE)], "write": [WRITE, WRITE], "review": [CLEAN]},
                                        j_extra={"write": [extra, extra]})
            self.assertEqual(s.calls[2][1], "ref-write", path)
            self.assertNotIn(self.MARK, s.prompts[2])
            self.assertIsNone(self.eng.write_rounds[0]["context_k"])
        empty = Path(self.tmp.name, "empty.jsonl")
        empty.write_text("")
        self.assertIsNone(context_size.context_tokens(str(empty)))

    def test_round_three_after_a_fresh_start_resumes_the_fresh_session(self):
        big, small = Path(self.tmp.name, "big.jsonl"), Path(self.tmp.name, "small.jsonl")
        for f, k in ((big, 160), (small, 40)):
            f.write_text(json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": k * 1000}}}) + "\n")
        red = procsim.fake("green-on-d4", lambda cwd, env: (0 if procsim.f_txt(cwd) == "d4" else 1, ""))
        ex = [{"family": "claude", "transcript": str(f)} for f in (big, small, small)]
        with self.store.stub(show=dict(BEAD, description=self.MARK)):
            rc, s = self.run_engine({"plan": [self.plan_with(red)], "write": [WRITE] * 3, "review": [CLEAN]}, j_extra={"write": ex})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[1] for c in s.calls[1:4]], [None, None, "ref-write"])  # fresh at 160k, then resumed
        self.assertIn(self.MARK, s.prompts[2])
        self.assertNotIn(self.MARK, s.prompts[3])

    def test_a_resumed_write_gets_the_engines_brief_back_in_the_worktree(self):
        brief = Path(self.wt) / ".task" / "t-1" / "brief.md"

        def tamper(cwd, env):
            t = procsim.f_txt(cwd)
            if t == "d2":
                brief.write_text("tampered")
            return (0 if t == "d3" else 1), ""
        red = procsim.fake("tamper-until-d3", tamper)
        with self.store.stub(show=dict(BEAD, description=self.MARK)):
            rc, s = self.run_engine({"plan": [self.plan_with(red)], "write": [WRITE, WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertIn(self.MARK, s.prompts[1])
        self.assertIn(self.MARK, brief.read_text())  # tampered after write 1, restored before write 2

    def test_fix_rounds_are_limited_then_the_bead_is_stuck(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE] * 3, "review": [CLEAN] * 3}, gate=FALSE)
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in s.calls].count("worker"), 3)  # the stage, then 2 fix rounds
        self.assertIn("2 fix rounds", self.blocked[0])

    def test_a_wait_is_logged_as_its_own_segment(self):
        eng = self.checks_engine()
        eng.t0 -= 600
        eng.waits.add(120, WaitWhat.LANE)
        (start,), (w,) = records(eng, "wait_start"), self.wait_records(eng)
        self.assertEqual((start["what"], start["id"] == w["id"], w["secs"], w["in_budget"]), ("lane", True, 120, False))

    def test_screenshots_in_evidence_are_kept_outside_the_worktree_and_named_on_the_bead(self):
        real = fake_route.Script.reply

        def shoot(this, role, prompt, schema, cwd, *a, **kw):
            if role == "worker":
                ev = Path(cwd, ".task", "t-1", "evidence")
                ev.mkdir(parents=True, exist_ok=True)
                (ev / "traits.png").write_bytes(b"\x89PNG fake")
            return real(this, role, prompt, schema, cwd, *a, **kw)
        with mock.patch.object(fake_route.Script, "reply", shoot):
            rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        kept = self.eng.run_dir / "evidence" / "traits.png"
        self.assertTrue(kept.exists())
        self.assertTrue(any(c[:2] == ("comments", "add") and str(kept) in c[3] for c in self.bd_calls))

    def test_no_pick_label_configured_touches_no_labels(self):
        with self.store.stub(show=dict(BEAD, labels=["auto"])):
            self.run_engine({"plan": [dict(PLAN, irreversible="push_shared", question="Build dreams now or park?")]})
        self.assertFalse(any(c[:1] == ("label",) for c in self.bd_calls))

    def test_a_machine_pause_is_no_ask(self):
        out = stop("logged_out", family="claude", say="Failed to authenticate: OAuth session expired")
        self.run_engine({"plan": [out]})
        self.assertIsNone(self.ask())

    def test_a_decision_without_options_is_made_up_to_two(self):
        self.run_engine({"plan": [dict(PLAN, irreversible="push_shared", question="Old format or new?")]})
        self.assertEqual(
            [(o["label"], o["recommended"]) for o in self.ask()["options"]], [("Answer in words", True), ("Split the bead", False)]
        )

    def test_run_breakdown_lists_where_the_minutes_went(self):
        log = Path(tempfile.mkdtemp()) / "run.jsonl"
        log.write_text(
            "\n".join(
                json.dumps({"v": 2, "kind": "step_end", "t": 1.0, "id": "n1", "step": st, "outcome": "done", "secs": sec}) + "\n"
                for st, sec in (("checks", 6000), ("checks", 3800), ("write", 900), ("plan", 20))
            )
        )
        self.assertEqual([(b.step, b.minutes, b.rounds) for b in outcomes.run_breakdown(log)], [("checks", 163.0, 2), ("write", 15.0, 1)])

    def test_a_settled_item_without_quoted_evidence_or_an_unanswered_one_stays_open(self):
        answer = {"items": [verdict(1, "settled", "  "), verdict(2, "settled", "Boot.cs:14"), verdict(7, "settled", "x")]}
        rc, _ = self.verified(answer)
        self.assertEqual(rc, 2)
        q = self.card()
        self.assertIn(".meta", q)
        self.assertIn("the menu reads well on a phone", q)
        self.assertNotIn("Boot() calls", q)

    def test_a_verify_fix_round_that_pauses_verifies_its_items_again_on_resume_never_lands_them(self):
        answer = {"items": [verdict(1, "wrong", why="the guid is also in Old.cs.meta"), verdict(2, "settled", "Boot.cs:14"),
                            verdict(3, "open", why="taste")]}
        busy = stop("rate_limited", at=time.time() + 7200, say="lane out")
        rc, _ = self.verified(answer, write=[WRITE, busy])
        self.assertEqual(rc, 2)
        self.assertTrue(self.blocked == [] and self.ask() is None)  # paused: the bead stays open, nothing asked
        rc, s = self.run_engine({"verify": [{"items": [verdict(1, "settled", "rg guid → 1 match"),
                                                       verdict(2, "settled", "evidence/menu.png")]}]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["reviewer"])
        self.assertIn("the hand-written .meta matches", s.prompts[0])
        self.assertIn("the menu reads well on a phone", s.prompts[0])
        self.assertNotIn("Boot() calls", s.prompts[0])

    @no_repo
    def test_criteria_in_a_description_section_count(self):
        bead = {"id": "t-1", "title": "Add f", "metadata": {},
                "description": "Add f.\n\n## Acceptance Criteria\n\nf.txt exists.\n\n## Touches\n\nf.txt"}
        self.assertTrue(AcceptanceText.present(must_bead(bead)))

    def test_invalid_output_retries_once_then_fails_and_still_closes(self):
        rc, s = self.run_engine({"plan": [{"summary": "x"}, {"summary": "x"}]})
        self.assertEqual(rc, 2)
        self.assertEqual([c[:2] for c in s.calls], [("planner", None), ("planner", None)])  # delegate re-asked in-thread already
        self.assertIn("plan node", self.said())

    def test_rounds_are_bounded(self):
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE] * 2, "review": [review(unmet=["x"])] * 2},
                                max_rounds=2, max_replans=0)
        self.assertEqual(rc, 2)
        self.assertIn("stuck after 2 rounds", self.blocked[0])

    def test_budget_blocks(self):
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE]}, budget_usd=0.6)
        self.assertEqual(rc, 2)
        self.assertIn("over budget", self.blocked[0])

    def test_engine_error_still_closes(self):
        with mock.patch.object(Planner, "plan", side_effect=RuntimeError("boom")):
            rc, _ = self.run_engine({})
        self.assertEqual(rc, 2)
        self.assertIn("engine error RuntimeError: boom", self.said())

    def test_a_denied_command_with_a_valid_answer_is_a_warning_in_the_trace(self):
        ok = full(WRITE, "w1", denied=[{"kind": "policy", "tool": "Bash", "path": "", "input": {"command": "curl -X POST https://x"}}])
        rc, _s = self.run_engine({"plan": [PLAN], "write": [ok, WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)  # (a raw answer writes no f.txt: the stage's check sends it to a second write)
        self.assertIn("write was denied `curl -X POST https://x`", self.eng.log_path.read_text())
        self.assertEqual(self.eng.sessions[1]["denied"], ok["denied"])

    def test_a_denied_command_with_no_valid_answer_needs_a_human_at_once(self):
        stuck = full(
            None,
            "w1",
            text="I could not run it",
            denied=[{"kind": "policy", "tool": "Bash", "path": "", "input": {"command": "unity open client"}}],
        )
        rc, s = self.run_engine({"plan": [PLAN], "write": [stuck, WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in s.calls].count("worker"), 1)
        self.assertEqual(self.blocked, [])  # a refusal is a machine fault: the bead stays open, nobody is asked
        self.assertIsNone(self.ask())
        self.assertIn("needs a human", self.said())
        self.assertIn("unity open client", self.said())

    def test_a_refused_read_only_command_gets_one_retry_on_a_fresh_thread_with_a_note(self):
        """tl-bxk.10.21 (lifesim-6dq0): a guard refused an rg read, no answer: one retry, told what was refused."""
        refused = full(None, "w1", family="openai", text="",
                       denied=[{"kind": "policy", "tool": "shell", "path": "", "input": {"command": "/bin/zsh -lc \"rg -n 'x' b\""}}])
        rc, s = self.run_engine({"plan": [PLAN], "write": [refused, WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        workers = [c for c in s.calls if c[0] == "worker"]
        self.assertEqual(len(workers), 2)
        log = self.eng.log_path.read_text()
        self.assertIn("read-only command refused", log)
        self.assertIn("denied_retry", log)

    def test_a_second_refusal_after_the_retry_leaves_the_bead_open_with_a_fault(self):
        refused = full(
            None,
            "w1",
            family="openai",
            text="",
            denied=[{"kind": "policy", "tool": "Bash", "path": "", "input": {"command": "rg -n foo src"}}],
        )
        rc, s = self.run_engine(
            {
                "plan": [PLAN],
                "write": [refused, full(None, "w2", family="openai", text="", denied=refused["denied"]), WRITE],
                "review": [CLEAN],
            }
        )
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in s.calls].count("worker"), 2)
        self.assertEqual(self.blocked, [])
        self.assertIn("needs a human", self.said())

    def test_a_refused_command_that_writes_or_a_secrets_stop_is_not_retried(self):
        for denied0, reason in (
            ([{"tool": "Bash", "input": {"command": "rm -rf build"}}], ""),
            ([{"tool": "shell", "input": {"command": "cat > f"}}], ""),
            ([{"tool": "shell", "input": {"command": "rg -n x ."}}], "secrets"),
            ([{"tool": "Bash", "input": {"command": "rg -n x ."}}, {"tool": "Bash", "input": {"command": "curl x"}}], ""),
        ):
            denied = [dict(x, kind="policy", path="") for x in denied0]
            stuck = stop("secrets", "w1", denied=denied) if reason else full(None, "w1", text="no", denied=denied)
            for f in (ident.config_dir() / "asks" / "t-1.json", ident.config_dir() / "checkpoints" / "t-1.json"):
                f.unlink() if f.exists() else None  # each case starts as a new bead: an open ask would make the run wait
            # a secrets stop gets the one new thread told to use apply_patch (lane_policy), then the fault; the rest is not retried
            rc, s = self.run_engine({"plan": [PLAN], "write": [stuck, stuck if reason else WRITE], "review": [CLEAN]})
            self.assertEqual((rc, [c[0] for c in s.calls].count("worker")), (2, 2 if reason else 1), denied)

    @no_repo
    def test_read_only_commands_are_told_from_the_rest(self):
        for c in ("rg -n foo src", "git log --oneline -5", "git diff main...HEAD -- a", "find . -name '*.cs'",
                  "sed -n '1,5p' f", "git branch", "rg -o x f", "sort -u f", "sort -n -r f", "rg -n --glob '!**/.env*' '^<<<<<<<' .",
                  "/bin/zsh -lc \"rg -n 'x' b\""):
            self.assertTrue(read_only_command(c), c)
        for c in (
            "ls\nrm x",
            "ls & rm x",
            "sort -o f x",
            "sort --output=f x",
            "git diff --output=f",
            "git log --output=f",
            "rg --pre sh x",
            "git grep -O sh x",
            "git diff --ext-diff",
            "sed -n '1w out' f",
            "sed -n '1e cmd' f",
            "sh -c 'rm x' ls",
            "git -c core.pager=sh log",
            "rm -rf x",
            "cat > f",
            "git commit -m x",
            "git branch -D x",
            "find . -delete",
            "find . -exec rm {} ;",
            "sed -i s/a/b/ f",
            "curl x",
            "rg x | xargs rm",
            "head -n 5 a | rg x",
            "head a && rg x",
            "ls || rm x",
            "cat $(ls)",
            "head -n 5 a; rm b",
            "git checkout x",
            "cat <<EOF",
            "echo `id`",
            "",
            None,
        ):
            self.assertFalse(read_only_command(c), c)

    def test_a_link_is_opened_twice_at_most(self):
        self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        eng, opened = self.eng, []
        eng.link_fn = lambda url: (opened.append(url), (False, "HTTP 404"))[1]
        with mock.patch.object(Checkout, "task_diff", return_value=self.RESEARCH_DIFF):
            for _ in range(4):
                eng.link_check.link_judged({"findings": []})
        self.assertEqual(len(opened), 6)  # three links, two rounds each; later reviews keep the verdict

    def test_a_second_denied_write_in_a_bead_needs_a_human_with_every_denied_command(self):
        first = full(WRITE, "w1", denied=[{"kind": "policy", "tool": "Bash", "path": "", "input": {"command": "git checkout x && pick"}}])
        second = full(
            WRITE,
            "w2",
            family="openai",
            denied=[{"kind": "policy", "tool": "shell", "path": "", "input": {"command": "git restore x; pick"}}],
        )
        rc, s = self.run_engine({"plan": [PLAN], "write": [first, second, WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in s.calls].count("worker"), 2)
        self.assertIn("needs a human", self.said())
        for cmd in ("git checkout x && pick", "git restore x; pick"):
            self.assertIn(cmd, self.said())

    def test_denied_writes_count_across_runs_of_a_bead(self):
        first = full(WRITE, "w1", denied=[{"kind": "policy", "tool": "Bash", "path": "", "input": {"command": "curl -X POST x"}}])
        with self.stop_at("worker", 2):
            self.run_engine({"plan": [PLAN], "write": [first]})
        again = full(WRITE, "w1", denied=[{"kind": "policy", "tool": "Bash", "path": "", "input": {"command": "curl --data @f x"}}])
        rc, _ = self.run_engine({"write": [again, WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 2)
        self.assertIn("curl -X POST x", self.said())
        self.assertIn("curl --data @f x", self.said())

    def test_the_secrets_tripwire_stops_the_bead_for_a_human_at_once(self):
        # delegate 0.25: a Codex command on a credential path stops the worker: failed, the command in denied
        trip = stop("secrets", "w1", say="stopped: the command touches a credential file", denied=[CAT_ENV])
        rc, s = self.run_engine({"plan": [PLAN], "write": [trip, trip], "review": [CLEAN]})
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in s.calls].count("worker"), 2)  # one new thread told to use apply_patch, then the fault
        self.assertEqual(self.blocked, [])
        self.assertIn("needs a human", self.said())
        self.assertIn("cat .env", self.said())
        self.assertIsNone(self.ask())  # tl-7y6.2.2: the tripwire is a machine fault, not an owner ask

    def test_fail_on_a_resumed_write_retries_once_as_a_new_thread(self):
        refused = stop("worker_failed", "ref-write", say="the resumed thread failed")
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, refused, WRITE], "review": [review(unmet=["more"]), CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        workers = [c for c in s.calls if c[0] == "worker"]
        self.assertEqual(len(workers), 3)
        self.assertIsNotNone(workers[1][1])  # the second write resumed the writer's thread
        self.assertIsNone(workers[2][1])     # the fail made it start a new one

    def test_no_answer_object_counts_as_fail(self):
        real = fake_route.Script.__call__
        seen = []

        def crash(this, cmd, **kw):
            if cmd[3] == "planner" and not seen:
                seen.append(cmd)
                return subprocess.CompletedProcess(cmd, 1, "", "route.py exit 1, no answer object")
            return real(this, cmd, **kw)
        with mock.patch.object(fake_route.Script, "__call__", crash):
            rc, _s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)  # delegate died once: again after a rest, then it went on

    def test_a_stop_is_a_pause_with_the_bead_open_and_never_a_fault(self):
        with self.stop_at("worker", 1):
            self.run_engine({"plan": [PLAN], "write": [WRITE]})
        r = self.eng.result()
        self.assertEqual((r.outcome, r.kind), ("paused", "pause_killed"))
        self.assertEqual((self.blocked, self.ask()), ([], None))
        self.assertFalse(any(c[:3] == ("label", "add", "t-1") for c in self.bd_calls))
        self.assertTrue(any(c[:1] == ("update",) and "open" in c for c in self.bd_calls))

    def test_the_trace_records_reason_context_and_the_lanes(self):
        rc, _ = self.run_engine({"plan": [PLAN], "write": [stop("rate_limited", at=time.time() + 30), WRITE],
                                 "review": [CLEAN]})
        self.assertEqual(rc, 0)
        self.assertEqual(self.eng.sessions[1]["reason"], "rate_limited")
        self.assertEqual(self.eng.sessions[-1]["context"]["instructions"], ["/repo/AGENTS.md"])
        trace = [json.loads(ln) for ln in (ident.config_dir() / "traces.jsonl").read_text().splitlines()][-1]
        self.assertEqual(trace["lanes"], {})

    def test_a_delegate_of_another_contract_blocks_before_any_step(self):
        c = wslots.load_cfg(str(self.wt))
        refusal = dl.Refusal("skew_delegate_older", "delegate speaks contract 2")
        script = fake_route.Script({})
        with (
            mock.patch.object(dl, "resolve", return_value=refusal),
            mock.patch.object(seams.DelegateRoute, "runner", lambda self, *a, **k: script),
        ):
            rc = engine.Engine(BeadId("t-1"), str(self.wt), c, store=self.store, env=snapshot(), spawner=real_spawner()).run()
        self.assertEqual(rc, 2)
        self.assertEqual(script.calls, [])
        self.assertIn("contract 3", self.said())
        self.assertIn("update", self.said())

    @no_repo
    def test_the_brief_hash_ignores_engine_comments_and_notes_lines(self):
        def h(bead, cs):
            return hashlib.sha1(brief_digest(must_bead(bead), [as_comment(c) for c in cs], owner_only=True).encode()).hexdigest()
        people = [{"author": "denis", "text": "Keep it small."}]
        base = h(BEAD, people)
        for name in CAP_PARKS:
            noise, _ = self.engine_noise(name)
            self.assertEqual(h(dict(BEAD, notes="Engine paused: x\nEngine failed: y"), people + noise), base)
        self.assertNotEqual(h(BEAD, [*people, {"author": "denis", "text": "A real remark."}]), base)
        self.assertNotEqual(h(dict(BEAD, description="Blocked: needs the design first"), people), base)  # the owner's own words stay
        self.assertNotEqual(h(BEAD, [*people, {"author": "denis", "text": "Parked over budget (226 of 180 min): scope change"}]), base)

    def test_a_lane_comment_after_a_block_does_not_hide_the_reopen(self):
        blocked = dict(BEAD, status="blocked", assignee="")
        cs = [
            {"author": "tl-x", "text": "Blocked: stuck", "created_at": "2026-10-25T10:00:00Z"},
            {"author": "tl-x", "text": "Lane (engine): the look step ran on the writer's own family", "created_at": "2026-10-25T10:01:00Z"},
        ]
        calls = []
        with self.store.stub(show=blocked), self.store.stub(comments=cs), \
                self.store.stub(bd_fn=lambda *a, **k: calls.append(a) or mock.Mock(returncode=0)):
            ok, why = entry.reclaim("t-1", str(self.wt), store=self.store)
        self.assertTrue(ok, why)

    def test_a_pause_is_a_comment_never_a_line_of_notes(self):
        calls = []
        late = stop("no_lane", at=time.time() + 3600, family="openai", lane="OPENAI", say="no lane. Hold the task; advice")
        with self.store.stub(bd_fn=lambda *a, **k: calls.append(a) or mock.Mock(returncode=0)):
            self.run_engine({"plan": [late]})
        self.assertFalse([c for c in calls if "--append-notes" in c], calls)
        self.assertTrue([c for c in calls if c[:3] == ("comments", "add", "t-1") and c[3].startswith("Engine paused:")], calls)

    def test_an_answer_that_does_not_allow_more_leaves_the_bead_blocked_with_the_answer_recorded(self):
        self.stopped_run()
        for k in (2, 3):
            self.stopped_run(bead=dict(BEAD, description=f"v{k}"))
        with self.store.stub(show=dict(BEAD, description="v4")):
            self.run_engine({})
        self.file_answer("split")
        with self.store.stub(show=dict(BEAD, description="v5")):
            rc, s = self.run_engine({})
        self.assertEqual(rc, 2)
        self.assertEqual(s.calls, [])
        self.assertEqual(self.eng.extra, 0)
        self.assertIn("re-planned 3 times", self.ask()["why"])
        self.assertIn("Answer: split", self.eng.log_path.read_text())

    def test_worker_rules_are_clipped_at_a_line_and_missing_ones_say_nothing(self):
        self.put_repo_file("r.md", "line\n" * 1000)
        eng = engine.Engine.__new__(engine.Engine)
        eng.cfg, eng.wt, eng.warn = cfg_with(worker_rules="r.md"), self.wt, mock.Mock()
        sh("git", "pull", "-q", "origin", "main", cwd=self.wt)
        text = eng.cases.rules_text()
        self.assertLessEqual(len(text.encode("utf-8")), RULES_MAX)
        self.assertTrue(text.endswith("line") and eng.warn.called)
        eng.cfg = cfg_with(worker_rules="nope.md")
        self.assertEqual(eng.cases.rules_text(), "")
        eng.cfg = cfg_with(worker_rules="")
        self.assertEqual(eng.cases.rules_text(), "")

    def test_the_brief_carries_what_linked_beads_decided(self):
        # lifesim-fld.25.17 asked which rung was picked in yxd6.3, whose close reason said so
        bead = dict(BEAD, description="Use the rung you picked in t-9, as agreed in t-8.", dependencies=[
            {"id": "t-7", "title": "Dep", "status": "open"}], parent="t-6")
        known = {"t-9": {"id": "t-9", "title": "Pick a rung", "status": "closed", "close_reason": "smile B, big smile D, laugh B"},
                 "t-8": {"id": "t-8", "title": "Agree", "status": "open"},
                 "t-6": {"id": "t-6", "title": "Epic", "status": "open"}}
        notes = {
            "t-9": [{"author": "denis", "text": "B for smile."}, {"author": "tl-sess1234", "text": "Reflect (engine): outcome=landed"}],
            "t-8": [{"author": "denis", "text": "x" * 900}],
        }
        with self.store.stub(show_fn=lambda b, cwd=None: bead if b == "t-1" else known.get(b, {})), \
                self.store.stub(comments_fn=lambda b, cwd=None: notes.get(b, [])):
            rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        p = s.prompts[0]
        self.assertIn("t-9 [closed] Pick a rung\n  closed: smile B, big smile D, laugh B\n  comment: B for smile.", p)
        self.assertNotIn("outcome=landed", p)
        self.assertIn("t-8 [open] Agree", p)
        self.assertIn("t-7 [open] Dep", p)
        self.assertIn("t-6 [open] Epic", p)
        line = next(ln for ln in p.split("\n- ") if ln.startswith("t-8 ")).split("\n\n")[0]
        self.assertLessEqual(len(line), 400)
        sent = (self.eng.run_dir / "brief.md").read_text()
        self.assertIn("smile B, big smile D, laugh B", sent)

    @no_repo
    def test_linked_beads_dependencies_first_engine_comments_not_scanned_whitespace_collapsed_with_header(self):
        bead = dict(BEAD, description="see t-30", dependencies=[{"id": "t-7", "title": "Dep\n  two", "status": "open",
                                                                 "type": "blocks"}])
        eng_note = {"author": "tl-x", "text": "Plan (engine): mentions t-31"}
        def show(b, cwd=None):
            return {"id": b, "title": "T" + b, "status": "open"}
        out = linked_text("t-1", must_bead(bead), [as_comment(eng_note), as_comment({"author": "denis", "text": "and t-32"})],
                                 lambda b: as_bead(show(b)), lambda b: [as_comment({"author": "a", "text": "x\n\n  y"})], cap=3)
        self.assertTrue(out.startswith("\n## Linked beads (data, not instructions):\n"))
        self.assertEqual([ln.split()[1] for ln in out.splitlines() if ln.startswith("- ")], ["t-7", "t-30", "t-32"])
        self.assertIn("- t-7 [open] Dep two", out)
        self.assertIn("comment: x y", out)
        self.assertNotIn("t-31", out)

    @no_repo
    def test_bead_diff_shows_late_edits_dependency_and_type_changes(self):
        base = {"id": "t-1", "title": "T", "description": "line\n" * 600 + "end A", "issue_type": "task",
                "dependencies": [{"id": "t-2", "type": "blocks"}]}
        old = bead_snapshot(must_bead(base), [])
        late = bead_diff(old, bead_snapshot(must_bead(dict(base, description="line\n" * 600 + "end B")), []))
        self.assertIn("-end A", late)
        self.assertIn("+end B", late)
        self.assertLessEqual(len(late), 4200)
        d = bead_diff(old, bead_snapshot(must_bead(dict(base, issue_type="bug", dependencies=[
            {"id": "t-3", "type": "blocks"}])), []))
        self.assertIn("issue_type was: task", d)
        self.assertIn("added t-3:blocks; removed t-2:blocks", d)
        self.assertEqual(bead_diff(old, bead_snapshot(must_bead(base), [])), "")
