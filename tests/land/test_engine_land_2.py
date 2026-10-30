"""Engine tests: the land, the push, the rebase and the conflict fix."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
import os
import threading
from pathlib import Path
from unittest import mock

import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import gitq, procsim
from support.engine_case import CLEAN, HAS_F, PLAN, POSIX_CHECK, STILL_OPEN, WRITE, EngineTest, verdict
from support.logs import records
from support.waits import until

from taskloop.adapters import (
    ident,
    landlock,
)


class EngineLand2Test(EngineTest):
    def test_waiting_for_the_land_lock_ends_the_open_node_first_and_is_logged(self):
        if os.name == "nt":
            self.skipTest("POSIX flock")
        eng = self.checks_engine()
        path = landlock.land_lock_path(gitq.git("remote", "get-url", "origin", cwd=eng.wt) or str(eng.wt))
        eng.steps.begin("review", "review")
        got, go = [], threading.Event()

        def holder():
            with landlock.os_lock(path, "other-bead"):
                got.append(1)
                go.wait(60)
        t = threading.Thread(target=holder)
        t.start()
        self.assertTrue(until(lambda: got), "the holder never took the lock")
        # The holder lets go only once the engine has logged that it waits (a fixed delay raced a loaded machine: the holder could let
        # go before the engine asked, and no wait was ever recorded).
        threading.Thread(target=lambda: until(lambda: records(eng, "wait_start")) and go.set()).start()
        with eng.lander.lock():
            pass
        t.join()
        (start,), (w,) = records(eng, "wait_start"), records(eng, "wait_end")
        self.assertEqual(
            (start["what"], start["holder"], start["id"] == w["id"], w["in_budget"]), ("land_lock", "other-bead", True, False)
        )  # tl-y35
        kinds = [r["kind"] for r in records(eng)]
        self.assertLess(kinds.index("step_end"), kinds.index("wait_start"))  # the open step ended before the wait began
        self.assertLess(kinds.index("wait_end"), kinds.index("lock"))
        self.assertLess(kinds.index("lock"), kinds.index("unlock"))
        self.assertGreaterEqual(w["secs"], 0)

    def test_a_free_land_lock_logs_no_wait(self):
        eng = self.checks_engine()
        with eng.lander.lock():
            pass
        self.assertEqual(self.wait_records(eng), [])

    def test_an_unchecked_requirement_stops_the_land_with_a_verify_ask(self):
        r = dict(CLEAN, unchecked=[{"what": "the cited spec link did not open", "kind": "link"}])
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [r], "verify": [STILL_OPEN]})
        self.assertEqual(rc, 2)
        a = self.ask()
        self.assertEqual(a["class"], "external_fact")
        self.assertIn("the cited spec link did not open", a["detail"]["text"])
        self.assertEqual(gitq.git("show", "origin/main:f.txt", cwd=str(self.wt)), "")

    def test_the_gate_named_as_unchecked_lands_without_an_ask(self):
        # lifesim-5ban.3: 'the full gate and diff coverage, reserved for the engine' stopped the land; the gate runs there
        gate = "true"
        r = dict(CLEAN, unchecked=[{"what": f"the full `{gate}` gate and diff coverage", "kind": "requirement"}])
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [r]}, gate=gate)
        self.assertEqual(rc, 0, self.blocked)
        self.assertIsNone(self.ask())
        self.assertIn(f"runs the gate (`{gate}`) once, at land", s.prompts[2])
        self.assertIn("never an unchecked item", s.prompts[2])
        self.assertIn("write no case for it", s.prompts[0])

    def test_a_repo_check_that_passed_this_round_named_as_unchecked_lands_without_an_ask(self):
        unit = procsim.fake("print-1", procsim.exits(0, "1"))
        r = dict(CLEAN, unchecked=[{"what": f"{unit} on the whole tree", "kind": "case"}])
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [r]},
                                checks=[{"id": "unit", "cmd": unit, "group": "tests"}])
        self.assertEqual(rc, 0, self.blocked)
        self.assertIsNone(self.ask())

    @POSIX_CHECK
    def test_a_case_named_as_unchecked_once_the_last_stage_ran_every_case_lands_without_an_ask(self):
        # lifesim-gfr.31.1: 'there is no nographics.out in evidence yet' reached the owner after the case writing it passed
        plan = dict(
            PLAN,
            cases=[{"criterion": "f.txt exists", "check": procsim.fake("has-f case", procsim.has_f)}],
        )
        r = dict(CLEAN, unchecked=[{"what": "I could not run the case 'f.txt exists': there is no evidence.out yet",
                                    "kind": "case"}])
        rc, s = self.run_engine({"plan": [plan], "write": [WRITE], "review": [r]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertIsNone(self.ask())
        self.assertIn("unchecked item dropped", self.eng.log_path.read_text())
        self.assertIn("one at a time", s.prompts[2])
        self.assertIn("a case is never an unchecked item", s.prompts[2])
        self.assertIn('"kind": "adhoc"', s.prompts[0])

    def test_a_case_item_with_no_case_in_the_plan_still_stops_the_land(self):
        r = dict(CLEAN, unchecked=[{"what": "the filter that selects nothing", "kind": "case"}])
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [r], "verify": [STILL_OPEN]})
        self.assertEqual(rc, 2)
        self.assertEqual((self.ask()["kind"], self.ask()["class"]), ("decision", "external_fact"))

    def test_a_stage_check_that_passed_named_as_unchecked_lands_without_an_ask(self):
        r = dict(CLEAN, unchecked=[{"what": f"`{HAS_F}` on the final tree", "kind": "requirement"}])
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [r]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertIsNone(self.ask())

    def test_an_answered_verify_ask_goes_straight_to_land(self):
        with self.store.stub(comments=self.verify_then_answer("confirm")):
            rc, s = self.run_engine({})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(s.calls, [])
        self.assertEqual(gitq.git("show", "origin/main:f.txt", cwd=str(self.wt)), "d2")

    def test_a_verify_answer_with_a_yes_and_evidence_goes_straight_to_land(self):
        text = "Right. The log shows the link opens and returns the spec."
        with self.store.stub(comments=self.verify_then_answer("confirm", text)):
            rc, s = self.run_engine({})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(s.calls, [])

    def test_a_verify_answer_the_planner_finds_needs_nothing_more_lands(self):
        with self.store.stub(comments=self.verify_then_answer("text", "Link is fine, checked.")):
            rc, s = self.run_engine({"plan": [dict(PLAN, stages=[], summary="nothing left")]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["planner"])
        self.assertEqual(gitq.git("show", "origin/main:f.txt", cwd=str(self.wt)), "d2")
        self.assertEqual(self.eng.plan_summary, "do it")  # the commit is titled after the work, not the empty plan

    def test_a_verify_answer_on_the_dashboard_lands_it(self):
        r = dict(CLEAN, unchecked=[{"what": "the cited spec link did not open", "kind": "link"}])
        self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [r], "verify": [STILL_OPEN]})
        self.file_answer("confirm")
        with self.store.stub(comments=[]):
            rc, s = self.run_engine({})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(s.calls, [])

    def test_an_earlier_stage_unchecked_item_a_later_review_clears_lands_without_an_ask(self):
        # lifesim-gfr.31.1: stage 1 could not run the last stage's case; stage 2 ran it green, its review was clean,
        # and the land still stopped on the stale stage-1 item
        r1 = dict(CLEAN, unchecked=[{"what": "the -nographics run, the last stage's job", "kind": "case"}])
        rc, s = self.run_engine({"plan": [self.TWO], "write": [WRITE, WRITE], "review": [r1, CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertIsNone(self.ask())
        self.assertIn("the -nographics run, the last stage's job", s.prompts[4])  # re-judged by the later review

    def test_an_earlier_stage_unchecked_item_a_later_review_keeps_stops_the_land(self):
        item = {"what": "the cited spec link did not open", "kind": "link"}
        rc, _ = self.run_engine({"plan": [self.TWO], "write": [WRITE, WRITE],
                                 "review": [dict(CLEAN, unchecked=[item]), dict(CLEAN, unchecked=[item])],
                                 "verify": [STILL_OPEN]})
        self.assertEqual(rc, 2)
        self.assertEqual((self.ask()["kind"], self.ask()["class"]), ("decision", "external_fact"))
        self.assertEqual(self.ask()["detail"]["text"].count("the cited spec link did not open"), 1)

    def test_an_unchecked_minor_item_lands_and_labels_the_bead_for_a_look(self):
        r = dict(CLEAN, unchecked=[{"what": "the tooltip wording on a phone", "kind": "other"}])
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [r]})
        self.assertEqual(rc, 0)
        self.assertIn(("label", "add", "t-1", "needs-owner-check"), [c[:4] for c in self.bd_calls])

    def test_unchecked_items_the_verifier_settles_land_without_an_ask(self):
        # lifesim-d5f.46, lifesim-fld.26.15: the supervisor settled each in a minute with read-only commands
        settled = {"items": [verdict(1, "settled", "rg -c 'guid: 3f2a' Assets → 1 match; fileFormatVersion: 2 as the siblings"),
                             verdict(2, "settled", "Boot.cs:14 `Wire();`"),
                             verdict(3, "settled", "evidence/menu.png shows the menu at 390px")]}
        rc, s = self.verified(settled)
        self.assertEqual(rc, 0, self.blocked)
        self.assertIsNone(self.ask())
        self.assertEqual(s.calls[3], ("reviewer", None, "openai"))  # read-only, another family than the writer
        brief = s.prompts[3]
        for item in self.GAPS:
            self.assertIn(item["what"], brief)
        self.assertIn(str(self.eng.evidence_dir), brief)
        self.assertIn("f.txt", brief)  # the diff summary
        self.assertIn("Add f", brief)  # the task
        for word in ("sandbox", "escalat", "git"):
            self.assertNotIn(word, brief.lower())
        said = [c[3] for c in self.bd_calls if c[:2] == ("comments", "add")]
        verify = next(c for c in said if c.startswith("Verify (engine)"))
        self.assertIn("Boot.cs:14 `Wire();`", verify)
        self.assertIn("settled", verify)
        reflect = next(c for c in said if c.startswith("Reflect (engine)"))
        self.assertIn("self-verified=3 settled, 0 wrong, 0 open", reflect)
        trace = json.loads((ident.config_dir() / "traces.jsonl").read_text().splitlines()[-1])
        self.assertEqual([v["verdict"] for v in trace["verified"]], ["settled"] * 3)
        self.assertEqual(trace["verified"][1]["evidence"], "Boot.cs:14 `Wire();`")
        self.assertEqual(trace["verified"][1]["what"], "Boot() calls the new Wire()")

    def test_an_item_the_verifier_finds_wrong_goes_to_a_fix_round_then_lands(self):
        answer = {"items": [verdict(1, "wrong", why="the .meta guid 3f2a is also in Old.cs.meta: make it unique"),
                            verdict(2, "settled", "Boot.cs:14"), verdict(3, "settled", "evidence/menu.png")]}
        rc, s = self.verified(answer, write=[WRITE, WRITE], review=[dict(CLEAN, unchecked=self.GAPS), CLEAN])
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer", "reviewer", "worker", "reviewer"])
        self.assertIn("also in Old.cs.meta: make it unique", s.prompts[4])
        self.assertEqual(self.eng.fixes, 1)
        self.assertIsNone(self.ask())
        verify = next(c[3] for c in self.bd_calls if c[:2] == ("comments", "add") and c[3].startswith("Verify (engine)"))
        self.assertIn("wrong", verify)

    def test_close_reason_says_what_landed_and_a_refused_close_is_a_warning(self):
        with self.store.stub(bd_fn=lambda *argv: mock.Mock(returncode=1 if argv[0] == "close" else 0, stdout="", stderr="refused")):
            _rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertIn("to main: do it", self.closed[0])
        self.assertGreater(len(self.closed[0]), 40)
        log = Path(sorted((Path(os.environ["XDG_CONFIG_HOME"]) / "task-loop" / "engine").glob("t-1-*.jsonl"))[-1])
        self.assertIn("bd refused to close", log.read_text())

    def test_a_done_answer_whose_text_says_unknown_argument_lands_normally(self):
        said = "the CLI printed: error: unknown argument; schema note: \"code\":\"invalid_json_schema\""
        rc, _ = self.run_engine({"plan": [PLAN], "write": [dict(WRITE, text=said, say=said)], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertTrue(self.closed and self.closed[0].startswith("merged "))
