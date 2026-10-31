"""Engine tests: the asks and the owner's answers."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
import subprocess
from pathlib import Path
from unittest import mock

import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import gitq, homes
from support.engine_case import BEAD, CAT_ENV, CLEAN, PLAN, WRITE, EngineTest, ask_rec, review, stop, verdict
from support.runs import manifest

from taskloop.adapters import (
    links,
)
from taskloop.app.land.checkout import Checkout
from taskloop.domain.checks import retry


class EngineAsksTest(EngineTest):
    def test_a_lock_that_stays_fails_after_5_min_and_no_process_is_probed(self):
        cmd, n = self.counting_check(self.LOCK[2])
        proj = self.wt / "client" / "Temp"
        proj.mkdir(parents=True)
        lockfile = proj / "UnityLockfile"
        lockfile.write_text("")
        eng = self.checks_engine(checks=[{"id": "unity", "cmd": cmd, "group": "tests", "retry": 1}])
        real, argv0 = subprocess.run, []
        with mock.patch.object(eng.checker, "sleep") as sleep, mock.patch.object(
                subprocess, "run", side_effect=lambda a, *k, **kw: (argv0.append(a[0]), real(a, *k, **kw))[1]):
            res = eng.run_checks({"checks": [], "files": []}, "s")
        self.assertNotIn("lsof", argv0)
        self.assertEqual((res[0].status, sum(c[0][0] for c in sleep.call_args_list if c[0][0] >= 15)),
                         ("failed", 300))
        self.assertIn("still locked after 300 s of waiting", res[0].tail)
        self.assertNotIn("holder", res[0].tail)
        self.assertEqual(n.read_text(), str(1 + len(retry.lock_waits())))

    def test_writer_question_is_an_owner_decision(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [dict(WRITE, question="Keep the old save format?")]})
        self.assertEqual(rc, 2)
        self.assertIn("Keep the old save format?", self.blocked[0])
        self.assertNotIn("reviewer", [c[0] for c in s.calls])

    def test_a_writer_question_an_accepted_requirement_decides_is_a_fix_round_citing_it(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [dict(WRITE, question="Undo or change R10?",
                                                                decided=self.R10), WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        writes = [p for (c, p) in zip(s.calls, s.prompts, strict=False) if c[0] == "worker"]
        self.assertEqual(len(writes), 2)
        self.assertIn(self.R10, writes[1])
        self.assertIn("decided", writes[0])

    def test_a_writer_that_keeps_asking_what_a_requirement_decides_uses_up_its_rounds(self):
        ask = dict(WRITE, question="Undo or change R10?", decided=self.R10)
        rc, _s = self.run_engine({"plan": [PLAN, PLAN], "write": [ask] * 6}, max_rounds=2, max_replans=1)
        self.assertEqual(rc, 2)
        self.assertNotIn("owner decision needed", self.blocked[0])

    D5F58_OWNER = ("(a). Accepted R10 stands: undo the general rule change (a lifer must not stand idle while something "
                   "is available) and fix the two-person home test another way.")

    def test_a_question_naming_two_requirements_the_brief_quotes_is_still_an_ask(self):
        owner = [{"author": "Denis Tomilin", "text": "Accepted: R3 keep saves forever; R7 drop them after a week."}]
        with self.store.stub(comments=owner):
            rc, _ = self.run_engine({"plan": [dict(PLAN, irreversible="push_shared", question="R3 and R7 conflict here: which wins?")]})
        self.assertEqual(rc, 2)
        self.assertEqual(self.ask()["kind"], "decision")

    def test_a_question_whether_a_requirement_should_change_still_asks_the_owner(self):
        # the engine never answers from the brief by itself: only the step's own decided field skips the owner
        owner = [{"author": "Denis Tomilin", "text": self.D5F58_OWNER}]
        for q in ("Should R10 be relaxed for a sole candidate?", "R10 vs criterion 3: which wins?"):
            with self.store.stub(comments=owner):
                rc, s = self.run_engine({"plan": [dict(PLAN, irreversible="push_shared", question=q)]})
            self.assertEqual(rc, 2, q)
            self.assertEqual(self.ask()["kind"], "decision")
            self.assertEqual([c[0] for c in s.calls], ["planner"])
            (homes.config_dir() / "asks" / "t-1.json").unlink()

    def test_a_missing_requirement_is_still_a_decision_ask(self):
        self.asks_the_owner("No requirement says what the empty filter shows: nothing, or everything?")

    def test_blocked_work_is_committed_on_the_task_branch(self):
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [review(question="A or B?")]})
        self.assertEqual(rc, 2)
        self.assertEqual(gitq.git("status", "--porcelain", cwd=str(self.wt)), "")
        self.assertIn("wip (t-1)", gitq.git("log", "-1", "--format=%s", "task/t-1", cwd=str(self.wt)))

    def ask_rec(self, **over):
        return ask_rec(**over)

    def test_a_live_claim_says_another_run_of_the_bead_holds_it_and_where_its_log_is(self):
        # lifesim-gfr.31.1: a restarted session relaunched the bead; TAKEN read like a stale claim of its own session
        log = manifest(homes.config_dir(), "t-1-20261021-063408", "t-1").log
        log.write_text("")
        ok, why, _ = self.admit({"status": "in_progress", "assignee": "tl-61ba34e7"})
        self.assertFalse(ok)
        self.assertIn("another run of t-1 is still running as tl-61ba34e7", why)
        self.assertIn(str(log), why)

    def test_admit_reopens_when_a_comment_answers_the_open_ask(self):
        ask = self.ask_rec(id="t-1-1")
        ok, _, up = self.admit({"status": "blocked"}, [self.BLOCKED, {"author": "denis", "text": "Rerun.",
                                                                      "created_at": "2026-10-20T23:25:00Z"}], ask)
        self.assertTrue(ok)
        self.assertIn(("update", "t-1", "--status", "open", "--assignee", ""), up)

    def test_admit_reopens_a_bead_whose_ask_has_an_answer_filed_on_it_with_no_comment_after_the_block(self):
        """tl-gy4 (sims qs, lifesim-hclf.32-2): answered on the ask, status open, no comment after 'Blocked:': run-task and --fresh
        (both go through this gate) said 'waiting for the answer'. Only a bead comment after the block got past it."""
        said = {"action": "rerun", "text": "run again", "t": 1.0, "by": "denis"}
        for status in ("open", "parked"):
            ask = self.ask_rec(id="t-1-2", status=status, answer=said)
            ok, why, up = self.admit({"status": "blocked"}, [self.BLOCKED], ask)
            self.assertTrue(ok, why)
            self.assertIn(("update", "t-1", "--status", "open", "--assignee", ""), up)
        ask = self.ask_rec(id="t-1-2")  # no answer filed
        ok, why, _ = self.admit({"status": "blocked"}, [self.BLOCKED], ask)
        self.assertFalse(ok)
        self.assertIn("waiting for the answer", why)
        later = {"author": "denis", "text": "Parked.", "created_at": "2026-10-21T00:05:00Z"}
        ask = self.ask_rec(id="t-1-2", status="answered", answer=said, consumed=2.0)  # consumed, then a person spoke
        ok, why, _ = self.admit({"status": "blocked"}, [self.BLOCKED, later], ask)
        self.assertFalse(ok)
        self.assertIn("commented after", why)

    def test_reclaim_leaves_blocked_what_a_person_parked_or_an_unanswered_ask_holds(self):
        later = {"author": "denis", "text": "Parked until People is designed.", "created_at": "2026-10-21T00:05:00Z"}
        ok, why, up = self.admit({"status": "blocked"}, [self.BLOCKED, later])
        self.assertFalse(ok)
        self.assertIn("commented after", why)
        ask = self.ask_rec(id="t-1-1")
        ok, why, up = self.admit({"status": "blocked"}, [self.BLOCKED], ask)
        self.assertFalse(ok)
        self.assertIn("t-1-1", why)
        ok, why, up = self.admit({"status": "blocked"}, [])
        self.assertFalse(ok)  # blocked by a person, not by the engine
        ok, why, up = self.admit({"status": "blocked", "dependencies": [
            {"id": "t-0", "title": "design", "status": "open", "type": "blocks"}]}, [self.BLOCKED])
        self.assertFalse(ok)
        self.assertIn("t-0", why)
        self.assertEqual(up, [])

    def test_a_resumed_round_holds_the_failing_block_and_the_brief_path_not_the_brief(self):
        rc, s = self.two_writes(ctx_k=40)
        self.assertEqual(rc, 0, self.blocked)
        first, again = s.prompts[1], s.prompts[2]
        self.assertEqual(s.calls[2][1], "ref-write")  # resumed
        self.assertIn(self.MARK, first)
        self.assertNotIn(self.MARK, again)
        self.assertIn("These checks fail", again)
        self.assertIn(
            "The brief is unchanged; it is in {}; re-read it if unsure".format(Path(self.wt) / ".task" / "t-1" / "brief.md"), again
        )
        self.assertIn(self.MARK, (Path(self.wt) / ".task" / "t-1" / "brief.md").read_text())
        self.assertLess(len(again), len(first) - 800)

    def test_a_fresh_round_holds_the_whole_brief(self):
        _rc, s = self.two_writes(ctx_k=40)
        self.assertEqual(s.calls[1][1], None)
        self.assertIn(self.MARK, s.prompts[1])
        self.assertIn("<plan>", s.prompts[1])

    def test_a_session_over_the_threshold_gives_way_to_a_fresh_writer_with_brief_and_done_so_far(self):
        rc, s = self.two_writes(ctx_k=160)  # claude: 150
        self.assertEqual(rc, 0, self.blocked)
        again = s.prompts[2]
        self.assertIsNone(s.calls[2][1])  # a new session
        for part in (self.MARK, "<plan>", "These checks fail", "Done so far", "f.txt", "wrote f"):
            self.assertIn(part, again)
        self.assertIn("fresh writer: session at 160k", self.eng.log_path.read_text())
        a, b = self.eng.write_rounds
        self.assertEqual((a["resumed"], a["context_k"], b["resumed"], b["fresh"]), ("no", 160, "no", "session at 160k"))
        self.assertEqual(b["prompt_chars"], len(again))

    def test_a_session_under_the_threshold_is_resumed_and_the_trace_has_its_size(self):
        _rc, s = self.two_writes(ctx_k=149)
        self.assertEqual(s.calls[2][1], "ref-write")
        a, b = self.eng.write_rounds
        self.assertEqual((b["resumed"], b["context_k"], b["fresh"]), ("yes", 149, ""))
        self.assertLess(b["prompt_chars"], a["prompt_chars"])

    def test_a_bead_parked_on_a_dropped_v1_ask_asks_again_with_a_v3_ask(self):
        p = homes.config_dir() / "asks" / "t-1.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"v": 1, "id": "t-1-4", "bead": "t-1", "status": "open", "kind": "verify", "question": "old?"}))
        self.assertEqual(self.asks().orphans(), ["t-1"])
        rc, s = self.run_engine({"plan": [dict(PLAN, irreversible="push_shared", question="Old format or new?")]})
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in s.calls], ["planner"])  # one planner step, not a second asking of the dropped one
        a = self.ask()
        self.assertEqual((a["v"], a["id"], a["status"]), (3, "t-1-1", "open"))
        self.assertEqual(self.asks().orphans(), [])

    def test_a_decision_ask_takes_the_bead_out_of_the_pick_queue(self):
        with self.store.stub(show=dict(BEAD, labels=["auto", "lane:sim"])):
            rc, _ = self.run_engine(
                {"plan": [dict(PLAN, irreversible="push_shared", question="Build dreams now or park?")]}, pick_label="auto"
            )
        self.assertEqual(rc, 2)
        self.assertIn(("label", "remove", "t-1", "auto"), self.bd_calls)
        self.assertIn(("label", "add", "t-1", "needs-info"), self.bd_calls)
        ask_comment = next(c[3] for c in self.bd_calls if c[:2] == ("comments", "add") and "Ask (engine)" in c[3])
        self.assertIn("needs-info", ask_comment)

    def test_the_label_swap_does_not_answer_the_ask(self):
        with self.store.stub(show=dict(BEAD, labels=["auto"])):
            self.run_engine({"plan": [dict(PLAN, irreversible="push_shared", question="Build dreams now or park?")]}, pick_label="auto")
        with self.store.stub(show=dict(BEAD, labels=["needs-info"])):
            _rc, s = self.run_engine({}, pick_label="auto")
        self.assertEqual(s.calls, [])
        self.assertEqual(self.ask()["status"], "open")

    def test_an_ask_names_its_repo(self):
        self.run_engine({"plan": [dict(PLAN, irreversible="push_shared", question="Old format or new?")]})
        self.assertEqual(Path(self.ask()["repo"]).resolve(), self.wt.resolve())

    def test_an_open_ask_with_an_unchanged_bead_waits_without_any_ai_step(self):
        self.run_engine({"plan": [dict(PLAN, irreversible="push_shared", question="Old format or new?")]})
        blocks = len(self.blocked)
        rc, s = self.run_engine({})
        self.assertEqual(rc, 2)
        self.assertEqual(s.calls, [])
        self.assertEqual(len(self.blocked), blocks)  # the bead stays blocked as it was; nothing re-asked
        self.assertIn("for the owner's answer", self.eng.log_path.read_text())
        self.assertEqual(self.ask()["status"], "open")

    def test_an_ask_with_an_answer_filed_on_it_starts_the_run_and_is_consumed(self):
        """tl-gy4 (lifesim-hclf.32-2): answered at 19:00, status still open, the bead unchanged: run-task said 'waiting for the answer'."""
        self.run_engine({"plan": [dict(PLAN, irreversible="push_shared", question="Old format or new?")]})
        self.assertEqual(self.ask()["status"], "open")
        self.file_answer("text", "Old format.")
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertGreaterEqual(len(s.calls), 1)  # it ran, it did not wait
        a = self.ask()
        self.assertEqual((a["status"], a["answer"]["text"], a["consumed"] is not None), ("answered", "Old format.", True))
        self.assertIn("Old format.", s.prompts[0])  # the planner read the answer
        self.assertIn("owner's answer is filed on it", self.eng.log_path.read_text())

    def test_a_parked_ask_still_waits_for_the_owner(self):
        self.run_engine({"plan": [dict(PLAN, irreversible="push_shared", question="Old format or new?")]})
        a = self.ask()
        a["status"] = "parked"
        (homes.config_dir() / "asks" / ("{}.json".format(a["bead"]))).write_text(json.dumps(a))
        rc, s = self.run_engine({})
        self.assertEqual((rc, s.calls), (2, []))
        self.assertEqual(self.ask()["status"], "parked")

    def test_an_owner_comment_answers_the_ask_and_the_bead_goes_on(self):
        self.run_engine({"plan": [dict(PLAN, irreversible="push_shared", question="Old format or new?")]})
        with self.store.stub(comments=[{"author": "denis", "text": "Old format."}]):
            rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        self.assertEqual(s.calls[0][0], "planner")
        self.assertEqual(self.ask()["status"], "answered")

    def test_an_over_budget_ask_offers_a_rerun_and_the_cap_ask_offers_one_more(self):
        self.run_engine({"plan": [PLAN], "write": [WRITE]}, budget_usd=0.6)
        a0 = self.ask()
        self.assertEqual((a0["kind"], [o["label"] for o in a0["options"]]), ("budget", ["Run again", "Split the bead"]))
        self.assertTrue(all(o["consequence"] for o in a0["options"]))
        self.assertEqual(a0["options"][0]["action"], "rerun")  # what the next run reads

    def test_a_wrong_item_with_no_fix_round_left_goes_to_the_owner_naming_the_defect(self):
        answer = {"items": [verdict(1, "wrong", why="the guid is also in Old.cs.meta"), verdict(2, "settled", "Boot.cs:14"),
                            verdict(3, "settled", "evidence/menu.png")]}
        answers = {"plan": [PLAN], "write": [WRITE], "review": [dict(CLEAN, unchecked=self.GAPS)], "verify": [answer]}
        rc, s = self.run_engine(answers, max_fix_rounds=0)
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in s.calls].count("worker"), 1)
        a = self.ask()
        self.assertEqual(a["kind"], "decision")
        self.assertIn("the guid is also in Old.cs.meta", a["why"])

    def test_owner_question_blocks_with_the_question(self):
        rc, _ = self.run_engine({"plan": [dict(PLAN, irreversible="push_shared", question="Which format, A or B?")]})
        self.assertEqual(rc, 2)
        self.assertIn("Which format, A or B?", self.blocked[0])
        self.assertFalse(self.closed)

    def test_a_task_with_an_unopened_link_is_sent_back_then_asks_when_the_writer_cannot_fix_it(self):
        def fake(url):
            return (False, "HTTP 403")
        with mock.patch.object(links, "check", fake), mock.patch.object(Checkout, "task_diff", return_value=self.RESEARCH_DIFF):
            rc, s = self.run_engine({"plan": [PLAN] * 3, "write": [WRITE] * 8, "review": [CLEAN] * 8},
                                    max_rounds=2, max_replans=0)
        self.assertEqual(rc, 2, self.blocked)
        self.assertNotIn("engine error", " ".join(self.blocked))
        self.assertGreaterEqual([c[0] for c in s.calls].count("worker"), 2)  # a fix round went to the writer
        self.assertIn("did not open from the engine's host", self.eng.log_path.read_text() + " ".join(self.blocked) +
                      " ".join(str(c) for c in self.bd_calls))

    def test_secrets_stop_leaves_the_bead_open_with_no_ask(self):
        trip = stop("secrets", "w1", say="stopped: credential path", denied=[CAT_ENV])
        rc, _ = self.run_engine({"plan": [PLAN], "write": [trip, trip]})
        self.assertEqual(rc, 2)
        self.assertIsNone(self.ask())  # tl-7y6.2.2: a refused credential read is a machine fault, never an owner ask
        self.assertEqual(self.blocked, [])
        self.assertIn("cat .env", self.said())

    def test_a_rejected_request_is_an_infrastructure_failure_that_leaves_the_bead_open_with_no_ask(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [self.bad_request()]})
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker"])  # no retry of a request that is malformed
        self.assertIsNone(self.ask())
        self.assertEqual(self.blocked, [])  # no `status blocked`, no "Blocked:" comment
        self.assertFalse(any(c[:1] == ("update",) and "blocked" in c for c in self.bd_calls))
        self.assertTrue(any(c[:1] == ("update",) and "open" in c and "--assignee" in c for c in self.bd_calls))
        r = self.eng.result()
        self.assertEqual(r.outcome, "failed")
        self.assertTrue(r.why.startswith("failed: infrastructure: bad_request: codex rejected the request"), r.why)
        self.assertLessEqual(len(r.why.split("bad_request: ", 1)[1]), 200)
        self.assertIn("infrastructure", self.eng.log_path.read_text())

    def test_the_third_identical_fault_on_one_bead_raises_exactly_one_ask(self):
        for n in range(2):
            self.run_engine({"plan": [PLAN], "write": [self.bad_request()]})
            self.assertEqual((self.eng.result().outcome, self.blocked, self.ask()), ("failed", [], None), n)
        self.run_engine({"plan": [PLAN], "write": [self.bad_request()]})
        r = self.eng.result()
        self.assertEqual((r.outcome, r.kind, r.asked), ("parked", "ask_stuck", True))
        self.assertEqual(self.ask()["kind"], "stuck")
        self.assertEqual(len(self.blocked), 1)

    def test_an_owner_reason_without_denied_is_a_fault_quoting_say(self):
        bad = stop("worker_failed", say="HTTP 500: upstream error")
        rc, _ = self.run_engine({"plan": [bad, bad]})
        self.assertEqual(rc, 2)
        self.assertIsNone(self.ask())
        self.assertEqual(self.blocked, [])
        self.assertIn("HTTP 500", self.said())

    def test_the_third_amend_is_an_owner_ask_and_an_answer_allows_one_more(self):
        self.stopped_run()                                              # plan 1
        for k in (2, 3):                                                # amend 1, amend 2 (across runs)
            self.stopped_run(bead=dict(BEAD, description=f"v{k}"))
        self.assertEqual(self.checkpoint()["planned"], 3)
        with self.store.stub(show=dict(BEAD, description="v4")):
            rc, s = self.run_engine({})
        self.assertEqual(rc, 2)
        self.assertEqual(s.calls, [])
        a = self.ask()
        self.assertEqual(a["kind"], "stuck")
        self.assertIn("re-planned 3 times", a["why"])
        for word in ("split", "allow one more", "1. plan", "2. amend", "bead changed"):
            self.assertIn(word, self.card().lower())
        self.assertTrue(self.card().startswith("The plan was redone 3 times"), self.card())
        self.file_answer("rerun")
        with self.store.stub(show=dict(BEAD, description="v5")):
            rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(s.calls[0][0], "planner")
        self.assertEqual(self.eng.extra, 1)
