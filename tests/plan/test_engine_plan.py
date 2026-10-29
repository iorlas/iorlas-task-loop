"""Engine tests: the plan and the replan."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support.engine_case import BEAD, CAP_PARKS, CLEAN, FALSE, HAS_F, PLAN, WRITE, EngineTest, review, sh, stop

# isort: split
import json
from pathlib import Path
from unittest import mock

from support import fake_route, procsim
from support.builders import cfg_with
from support.logs import records

from taskloop.adapters import ident
from taskloop.app.plan.planner import Planner
from taskloop.app.run import engine
from taskloop.contracts import answers
from taskloop.contracts.argv import checks_to_wire
from taskloop.contracts.config import EngineConfig
from taskloop.domain import outcome as oc
from taskloop.domain.checks import lint
from taskloop.domain.checks.names import log_var
from taskloop.domain.prompts import plan as pp
from taskloop.domain.prompts import review as rp
from taskloop.domain.prompts import write as wp
from taskloop.domain.prompts.common import RULES_MAX
from taskloop.domain.prompts.plan import REPLAN_CAP


class EnginePlanTest(EngineTest):
    def test_no_prompt_points_outside_the_worktree_the_brief_plan_and_replan_are_inline(self):
        # delegate 0.23 keeps Claude's file tools in the worktree: a path to the run dir is a file no step can read
        rc, s = self.run_engine({"plan": [PLAN, PLAN], "write": [WRITE, WRITE, WRITE],
                                 "review": [review(unmet=["a"]), CLEAN]}, max_rounds=1)
        self.assertEqual(rc, 0)
        run = str(self.eng.run_dir)
        for role, p in zip([c[0] for c in s.calls], s.prompts, strict=False):
            self.assertNotIn(run, p, role)
        self.assertIn("add f", s.prompts[0] + s.prompts[1])        # the plan, inline in the write
        self.assertIn("the review still sends it back", s.prompts[3])  # the replan's reason, inline

    def test_the_planner_puts_proof_files_under_evidence(self):
        _rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertIn(str(self.eng.evidence_dir), s.prompts[0])
        self.assertIn("screenshots", s.prompts[0])

    def test_a_plan_check_that_re_runs_a_configured_check_is_found(self):
        cfg = cfg_with(checks=[{"id": "unity-tests", "cmd": "just unity-tests", "group": "tests"}])
        plan = dict(PLAN, risks=[{"what": "x", "check": "env CI=1 just unity-tests"},
                                 {"what": "y", "check": "just unity-tests-extra"}])
        self.assertEqual([i for _, i in lint.rerun_checks(plan, cfg)], ["unity-tests"])
        self.assertEqual(log_var("unity-tests"), "TL_CHECK_LOG_UNITY_TESTS")

    def test_a_plan_with_just_unity_in_acceptance_is_sent_back_once(self):
        bad = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=["just unity-tests"])])
        procsim.fake("pass-check", procsim.exits(0))
        _rc, s = self.run_engine({"plan": [bad, PLAN], "write": [WRITE], "review": [CLEAN]},
                                checks=[{"id": "unity-tests", "cmd": "pass-check", "group": "tests"}])
        self.assertEqual([c[0] for c in s.calls], ["planner", "planner", "worker", "reviewer"])
        self.assertIn("runs `just unity-tests`", s.prompts[1])

    def test_a_worker_edit_to_the_plan_file_is_undone_before_the_next_step(self):
        real = fake_route.Script.reply

        def tamper(this, role, prompt, schema, cwd, *a, **kw):
            if role == "worker":
                (self.eng.run_dir / "plan.json").write_text('{"tampered": true}')
            if role == "reviewer":
                this.seen_plan = (self.eng.run_dir / "plan.json").read_text()
            return real(this, role, prompt, schema, cwd, *a, **kw)
        with mock.patch.object(fake_route.Script, "reply", tamper):
            rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        self.assertNotIn("tampered", s.seen_plan)
        self.assertIn("add f", s.seen_plan)

    def test_rounds_used_up_replan_once_then_stuck(self):
        rc, s = self.run_engine({"plan": [PLAN, PLAN], "write": [WRITE, WRITE],
                                 "review": [review(unmet=["x"]), review(unmet=["x"])]}, max_rounds=1, max_replans=1)
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in s.calls].count("planner"), 2)
        self.assertIn("stuck", self.blocked[0])

    def test_a_check_the_writer_flags_as_wrong_replans_at_once(self):
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[FALSE])])
        flag = dict(WRITE, bad_checks=[{"cmd": FALSE, "why": "it exits 1 whatever the code does"}])
        rc, s = self.run_engine({"plan": [plan, PLAN], "write": [flag, WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "planner", "worker", "reviewer"])
        self.assertIn("exits 1 whatever the code does", (self.eng.run_dir / "replan.md").read_text())

    BEAD_CHECK = "bd list --label lane:live --json"

    def test_a_check_that_reads_the_tracker_is_sent_back_to_the_planner_once(self):
        # lifesim-fld.26.12: a stage check ran `bd list` for a follow-up bead; writers cannot run bd, so no code passed it
        bad = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[HAS_F, self.BEAD_CHECK])])
        rc, s = self.run_engine({"plan": [bad, PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        self.assertEqual([c[0] for c in s.calls], ["planner", "planner", "worker", "reviewer"])
        self.assertIn("read the issue tracker", s.prompts[1])
        self.assertIn(self.BEAD_CHECK, s.prompts[1])
        self.assertIn("leftovers", s.prompts[1])

    def test_a_plan_still_reading_the_tracker_after_one_rewrite_fails(self):
        bad = dict(PLAN, cases=[{"criterion": "a follow-up exists", "check": "cat .beads/issues.jsonl"}])
        _rc, s = self.run_engine({"plan": [bad, bad]})
        self.assertEqual([c[0] for c in s.calls], ["planner", "planner"])
        self.assertEqual(self.blocked, [])
        self.assertIn("read the issue tracker", self.said())

    def test_follow_up_work_in_the_plan_is_filed_by_the_engine(self):
        lo = {"title": "Track hard-to-undo moves", "why": "the plan wants it filed"}
        rc, _s = self.run_engine({"plan": [dict(PLAN, leftovers=[lo])], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        self.assertEqual(sum(1 for c in self.bd_calls if c[:2] == ("create", lo["title"])), 1)
        self.assertIn("never reads the tracker", pp.PLAN_PROMPT)

    D5F58_Q = ("One older test stays red, and I need your call on it. Rule R10 says a lifer never idles while something "
               "is available, but that test says never repeat within the hour, no exceptions. Options: A) the test allows "
               "a sole-candidate repeat, B) raise min_score, C) change the seed. My recommendation is A.")

    def test_a_planner_question_an_accepted_requirement_decides_is_planned_again_citing_it(self):
        rc, s = self.run_engine({"plan": [dict(PLAN, irreversible="push_shared", question=self.D5F58_Q, decided=self.R10), PLAN],
                                 "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertIsNone(self.ask())
        self.assertEqual([c[0] for c in s.calls], ["planner", "planner", "worker", "reviewer"])
        self.assertIn(self.R10, s.prompts[1])
        self.assertIn("never the requirement", s.prompts[1])
        self.assertIn("decided", s.prompts[0])
        causes = [json.loads(ln)["cause"] for ln in self.eng.log_path.read_text().splitlines() if '"transition"' in ln]
        self.assertIn("planner_decided", causes)

    def test_a_planner_that_asks_again_after_the_requirement_is_quoted_reaches_the_owner(self):
        ask = dict(PLAN, irreversible="push_shared", question=self.D5F58_Q, decided=self.R10)
        rc, s = self.run_engine({"plan": [ask, ask]})
        self.assertEqual(rc, 2)
        self.assertEqual(self.ask()["kind"], "decision")
        self.assertEqual([c[0] for c in s.calls], ["planner", "planner"])

    def test_follow_up_work_a_replan_names_again_is_not_filed_twice(self):
        lo = {"title": "Track hard-to-undo moves", "why": "the plan wants it filed"}
        with self.stop_at("reviewer", 2):
            self.run_engine({"plan": [dict(self.TWO, leftovers=[lo])], "write": [WRITE, WRITE], "review": [CLEAN]})
        with self.store.stub(show=dict(BEAD, description="Stage two: keep it small.")):
            rc, s = self.run_engine({"plan": [dict(self.TWO, stages=self.TWO["stages"][1:], leftovers=[lo])],
                                     "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        self.assertEqual(s.calls[0][0], "planner")  # the changed bead re-planned, naming the same follow-up
        self.assertEqual(sum(1 for c in self.bd_calls if c[:2] == ("create", lo["title"])), 1)

    def test_a_replan_keeps_the_stages_already_accepted(self):
        one_left = dict(self.TWO, stages=[dict(self.TWO["stages"][1], goal="stage two, again")])
        rc, s = self.run_engine({"plan": [self.TWO, one_left], "write": [WRITE] * 4,
                                 "review": [CLEAN, review(unmet=["a"]), review(unmet=["b"]), CLEAN]}, max_rounds=2)
        self.assertEqual(rc, 0)
        roles = [c[0] for c in s.calls]
        self.assertEqual(roles, ["planner", "worker", "reviewer", "worker", "reviewer", "worker", "reviewer",
                                 "planner", "worker", "reviewer"])
        replan = s.prompts[7]
        self.assertIn("already accepted", replan)
        self.assertIn("stage one", replan)
        self.assertIn("stage two, again", s.prompts[8])

    def test_a_changed_bead_keeps_accepted_stages_and_replans_the_rest(self):
        with self.stop_at("reviewer", 2):
            self.run_engine({"plan": [self.TWO], "write": [WRITE, WRITE], "review": [CLEAN]})
        bead = dict(BEAD, description="Add the file f, and say hi.")
        one_left = dict(self.TWO, stages=[self.TWO["stages"][1]])
        with self.store.stub(show=bead):
            rc, s = self.run_engine({"plan": [one_left], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer"])
        self.assertIn("already accepted", s.prompts[0])

    def test_a_failed_run_then_a_rerun_with_no_bead_edits_resumes_without_a_plan(self):
        # lifesim 2026-10-20: the engine's own close lines changed the brief, so every rerun re-planned
        with self.stop_at("reviewer", 3):
            self.run_engine({"plan": [self.TWO], "write": [WRITE, WRITE, WRITE],
                             "review": [CLEAN, review(unmet=["more"])]})
        own = [{"author": "tl-sess1234", "text": "Blocked: failed: stopped (SIGTERM)", "created_at": "2026-10-20T21:11:48Z"},
               {"author": "tl-sess1234", "text": "Reflect (engine): outcome=failed; minutes=83", "created_at": "2026-10-20T21:11:49Z"}]
        labelled = dict(BEAD, labels=["needs-owner-check"])  # the engine's own label
        with self.store.stub(comments=own), self.store.stub(show=labelled):
            rc, s = self.run_engine({"write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["worker", "reviewer"])
        self.assertNotIn("outcome=failed", s.prompts[0])  # tl-7y6.6.2: no engine record in the brief, so none in the prompt

    def test_the_last_stage_note_reaches_a_resumed_writer(self):
        two = dict(PLAN, stages=[dict(PLAN["stages"][0], goal="first"), dict(PLAN["stages"][0], goal="second")])
        rc, s = self.run_engine({"plan": [two], "write": [WRITE, WRITE], "review": [CLEAN, CLEAN]},
                                j_extra={"write": [{"family": "claude"}] * 2}, worker_rules="a.txt")
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(s.calls[3][1], "ref-write")
        self.assertIn("acceptance cases run on this last stage", s.prompts[3])
        self.assertIn("new_cases", s.prompts[3])
        self.assertNotIn("acceptance cases run on this last stage", s.prompts[1])
        self.assertNotIn("a.txt", s.prompts[3])  # tl-7y6.6.1: the rules are in the first prompt only; a resume never says Read <rules>
        self.assertNotIn("Read ", s.prompts[3])
        self.assertNotIn("worker_rules", s.prompts[3])

    def test_replans_count_across_runs(self):
        with self.stop_at("reviewer", 3):  # stage 1 sent back twice -> replan; stopped in the new plan's review
            self.run_engine({"plan": [PLAN, PLAN], "write": [WRITE] * 3,
                             "review": [review(unmet=["a"]), review(unmet=["b"])]}, max_rounds=2, max_replans=1)
        self.assertEqual(self.checkpoint()["replans"], 1)
        rc, s = self.run_engine({"write": [WRITE] * 2, "review": [review(unmet=["c"]), review(unmet=["d"])]},
                                max_rounds=2, max_replans=1)
        self.assertEqual(rc, 2)
        self.assertIn("re-plan", self.blocked[-1])
        self.assertNotIn("planner", [c[0] for c in s.calls])

    def test_acceptance_cases_run_on_the_last_stage_only(self):
        seen, case = self.counter("case")
        plan = dict(self.TWO, cases=[{"criterion": "f.txt exists", "check": case}])
        rc, s = self.run_engine({"plan": [plan], "write": [WRITE, WRITE], "review": [CLEAN, CLEAN]})
        self.assertEqual(rc, 0)
        self.assertEqual(seen.read_text(), "1")  # stage 2 of 2, not stage 1
        self.assertIn("f.txt exists", s.prompts[0] + s.prompts[3])

    def test_a_fix_round_runs_the_acceptance_cases_again(self):
        seen, case = self.counter("case")
        plan = dict(PLAN, cases=[{"criterion": "f.txt exists", "check": case}])
        gate = procsim.fake("red-on-d2", lambda cwd, env: (1 if procsim.f_txt(cwd) == "d2" else 0, ""))
        rc, _s = self.run_engine({"plan": [plan], "write": [WRITE, WRITE], "review": [CLEAN, CLEAN]}, gate=gate)
        self.assertEqual(rc, 0)
        self.assertEqual(seen.read_text(), "11")

    def test_a_planner_question_is_a_decision_ask_on_the_bead(self):
        rc, _ = self.run_engine({"plan": [dict(PLAN, irreversible="push_shared", question="Old format or new?")]})
        self.assertEqual(rc, 2)
        a = self.ask()
        self.assertEqual((a["kind"], a["class"], a["status"]), ("decision", "open_question", "open"))
        self.assertEqual(a["decision"], "Old format or new?")
        self.assertEqual(a["detail"]["text"], "Old format or new?")
        self.assertTrue(any(c[:2] == ("comments", "add") and "{} (decision)".format(a["id"]) in c[3] for c in self.bd_calls))

    def test_a_used_up_replan_is_a_stuck_ask(self):
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [review(unmet=["a"])]},
                                max_rounds=1, max_replans=0)
        self.assertEqual(rc, 2)
        self.assertEqual(self.ask()["kind"], "stuck")

    def test_a_decision_ask_carries_the_options_the_planner_gave(self):
        rc, _ = self.run_engine({"plan": [dict(PLAN, irreversible="push_shared", question="Build now or park?", options=self.CHOICES)]})
        self.assertEqual(rc, 2)
        self.assertEqual(
            [(o["label"], o["text"], o["cost"], o["recommended"], o["action"]) for o in self.ask()["options"]],
            [
                ("Keep parked", "B: keep it parked", "none", True, "text"),
                ("Build it", "A: build the slice now", "about 4 stages", False, "text"),
            ],
        )

    def test_the_decision_schemas_require_options(self):
        for node in ("plan", "write", "review"):
            sch = answers.schema_for(node)
            self.assertIn("options", sch["required"])
            self.assertEqual(sch["properties"]["options"]["items"]["required"], ["label", "cost", "answer", "recommended"])
            self.assertIn("options: with a question, 2-4 answers", {"plan": pp.PLAN_PROMPT, "write": wp.WRITE_PROMPT,
                                                                     "review": rp.REVIEW_PROMPT}[node])
        ok = {"label": "A", "cost": "c", "answer": "a", "recommended": True}
        self.assertEqual(answers.check("plan", False, checks_to_wire(dict(PLAN, options=[ok]))), [])
        bare = {k: v for k, v in checks_to_wire(PLAN).items() if k != "options"}
        self.assertEqual(answers.check("plan", False, bare), ["PlanAnswer.options: missing"])
        self.assertEqual(answers.check("plan", False, checks_to_wire(dict(PLAN, options=[{"label": "A"}]))),
                         ["PlanAnswer.options[0].cost: missing"])

    def test_a_verify_answer_with_a_yes_and_a_change_plans_it(self):
        more = dict(PLAN, stages=[dict(PLAN["stages"][0], goal="test Y")])
        with self.store.stub(comments=self.verify_then_answer("text", "right, but add a test for Y")):
            rc, s = self.run_engine({"plan": [more], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer"])

    def test_a_verify_answer_asking_for_more_work_plans_it_keeping_the_accepted_stages(self):
        # lifesim-fld.26.15: 'add a test that ..., then land' went straight to land without the test
        text = "add a test that f.txt is not empty, then land"
        more = dict(PLAN, stages=[dict(PLAN["stages"][0], goal="test f.txt")])
        with self.store.stub(comments=self.verify_then_answer("text", text)):
            rc, s = self.run_engine({"plan": [more], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer"])
        self.assertIn(text, s.prompts[0])
        self.assertIn("- add f\n", s.prompts[0])  # the accepted stage, not planned again
        self.assertEqual(self.eng.replans, 0)

    def test_a_bead_without_acceptance_criteria_is_a_ticket_and_never_planned(self):
        with self.store.stub(show={"id": "t-1", "title": "Add f", "metadata": {}, "description": "Add f."}):
            rc, s = self.run_engine({"plan": [PLAN]})
        self.assertEqual(rc, 2)
        self.assertEqual(s.calls, [])
        self.assertEqual(self.ask()["kind"], "ticket")

    def test_a_plan_of_more_than_three_stages_is_a_split_ticket(self):
        four = dict(PLAN, stages=[dict(PLAN["stages"][0], goal=f"part {k}") for k in range(4)])
        rc, s = self.run_engine({"plan": [four]})
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in s.calls], ["planner"])
        a = self.ask()
        self.assertEqual(a["kind"], "ticket")
        self.assertIn("part 3", self.card())

    def test_fail_on_a_plan_tries_once_more_then_fails_the_task(self):
        bad = stop("worker_failed", say="the worker exited 1")
        rc, s = self.run_engine({"plan": [bad, bad]})
        self.assertEqual(rc, 2)
        self.assertEqual(len(s.calls), 2)
        self.assertEqual(self.blocked, [])
        self.assertIn("the worker exited 1", self.said())

    def test_the_same_fault_on_a_second_bead_trips_the_storm_once(self):
        self.run_engine({"plan": [PLAN], "write": [self.bad_request()]})
        first = self.eng.result()
        self.assertEqual((first["outcome"], first["kind"], first["storm"]), ("failed", "fault_bad_request", ""))
        self.run_engine({"plan": [PLAN], "write": [self.bad_request()]}, bead="t-2")
        second = self.eng.result()
        self.assertTrue(second["storm"].startswith("STOPPED: storm FAULT_BAD_REQUEST"), second["storm"])
        self.assertIn("t-1,t-2", second["storm"])
        self.run_engine({"plan": [PLAN], "write": [self.bad_request()]}, bead="t-3")
        self.assertEqual(self.eng.result()["storm"], "")  # the record is live: no second banner
        self.assertEqual((self.blocked, self.ask()), ([], None))
        self.assertEqual(len(list((ident.config_dir() / "storm").glob("*.json"))), 1)

    def test_a_changed_bead_amends_the_old_plan_it_does_not_plan_again(self):
        self.stopped_run(plan=self.TWO, answers={"plan": [self.TWO], "write": [WRITE]})
        with self.store.stub(show=dict(BEAD, description="Also say hi.")), \
                self.store.stub(comments=[{"author": "denis", "text": "Keep it small."}]):
            rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        p = s.prompts[0]
        self.assertIn("<old_plan>", p)
        self.assertIn("stage one", p)
        self.assertIn("smallest change", p)
        self.assertIn("do not re-explore code the old plan already names", p)
        self.assertIn("description changed:", p)
        self.assertIn("+Also say hi.", p)
        self.assertIn("new comment:\nKeep it small.", p)
        self.assertEqual(self.eng.plan_log[-1]["mode"], "amend")

    def test_a_comment_alone_is_not_an_amend_and_costs_no_replan(self):
        self.stopped_run(plan=self.TWO, answers={"plan": [self.TWO], "write": [WRITE]})
        with self.store.stub(show=BEAD), \
                self.store.stub(comments=[{"author": "denis", "text": "Fresh start: use the other slot."}]):
            rc, s = self.run_engine({"write": [WRITE, WRITE], "review": [CLEAN, CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertNotIn("planner", [c[0] for c in s.calls])
        self.assertNotIn("an edit with no ask", self.eng.log_path.read_text())
        self.assertIn("nothing the plan reads", self.eng.log_path.read_text())

    def only_engine_written(self, name):
        noise, _ = self.engine_noise(name)
        self.assertTrue(len(noise) > 1, "the fixture has engine comments")
        self.stopped_run()
        with self.store.stub(show=dict(BEAD, notes="Engine paused: paused: no lane for write")), \
                self.store.stub(comments=noise):
            rc, s = self.run_engine({"write": [WRITE, WRITE], "review": [CLEAN, CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        log = self.eng.log_path.read_text()
        self.assertNotIn("planner", [c[0] for c in s.calls])
        self.assertNotIn("an edit with no ask", log)
        self.assertNotIn("amending its plan", log)
        self.assertEqual(self.eng.planned, 1)  # the first plan only: nothing charged
        self.assertIsNone(self.ask())

    def test_o67g_engine_comments_and_notes_cost_no_replan(self):
        self.only_engine_written(CAP_PARKS[0])

    def test_yxbb2_engine_comments_and_notes_cost_no_replan(self):
        self.only_engine_written(CAP_PARKS[1])

    def test_d5f40_engine_comments_and_notes_cost_no_replan(self):
        self.only_engine_written(CAP_PARKS[2])

    def test_an_owner_answer_to_an_ask_amends_the_plan_with_the_answer(self):
        ask = dict(WRITE, question="Which format?")
        rc, _ = self.run_engine({"plan": [PLAN], "write": [ask]})
        self.assertEqual(rc, 2)
        self.assertEqual(self.ask()["kind"], "decision")
        with self.store.stub(comments=[{"author": "denis", "text": "Use the new format."}]):
            rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(s.calls[0][0], "planner")
        self.assertIn("<old_plan>", s.prompts[0])
        self.assertIn("Use the new format.", s.prompts[0])
        self.assertIn("the owner answered ask t-1-1", self.eng.plan_log[-1]["why"])

    def test_a_bead_that_changed_in_nothing_the_plan_reads_keeps_its_plan_and_calls_no_planner(self):
        self.stopped_run()
        with self.store.stub(show=dict(BEAD, labels=["urgent"])):
            rc, s = self.run_engine({"write": [WRITE, WRITE], "review": [CLEAN, CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertNotIn("planner", [c[0] for c in s.calls])
        self.assertIn("keeping the plan, no planner run", self.eng.log_path.read_text())

    def test_a_branch_changed_since_the_checkpoint_amends_instead_of_planning_again(self):
        self.stopped_run()
        sh("git", "checkout", "-q", "task/t-1", cwd=self.wt)  # a parked slot is left detached at the base
        (self.wt / "g.txt").write_text("someone edited it\n")
        sh("git", "add", "-A", cwd=self.wt)
        sh("git", "commit", "-qm", "by hand", cwd=self.wt)
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertIn("<old_plan>", s.prompts[0])
        self.assertIn("The branch changed outside the engine", s.prompts[0])
        self.assertIn("by hand", s.prompts[0])

    def test_an_in_run_replan_amends_with_the_old_plan_and_the_failure_tail(self):
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[FALSE])])
        flag = dict(WRITE, bad_checks=[{"cmd": FALSE, "why": "it exits 1 whatever the code does"}])
        rc, s = self.run_engine({"plan": [plan, PLAN], "write": [flag, WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        again = s.prompts[2]
        self.assertIn("<old_plan>", again)
        self.assertIn(json.dumps(FALSE)[1:-1], again)  # the plan is quoted as JSON: a Windows path has doubled backslashes
        self.assertIn("it exits 1 whatever the code does", again)
        self.assertEqual([e["mode"] for e in self.eng.plan_log], ["plan", "amend"])

    def test_the_stage_level_cap_is_the_replan_cap_ask_and_allow_one_more_works_on_it(self):
        rc, _s = self.run_engine({"plan": [PLAN, PLAN], "write": [WRITE, WRITE],
                                 "review": [review(unmet=["x"]), review(unmet=["x"])]}, max_rounds=1, max_replans=1)
        self.assertEqual(rc, 2)
        a = self.ask()
        self.assertTrue(a["why"].startswith(REPLAN_CAP), a["why"])
        self.assertIn("stage 1 stuck after 1 rounds", a["why"])
        self.assertIn("allow one more", self.card().lower())
        self.file_answer("rerun")
        rc, _s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, max_rounds=1, max_replans=1)
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(self.eng.extra, 1)

    def cap_answered_rerun(self):
        """Run to the stage-level cap (max_replans=1), answer 'allow one more run' with a typed word."""
        rc, _s = self.run_engine({"plan": [PLAN, PLAN], "write": [WRITE, WRITE],
                                 "review": [review(unmet=["x"]), review(unmet=["x"])]}, max_rounds=1, max_replans=1)
        self.assertEqual(rc, 2)
        self.file_answer("rerun", "Allow one more run. The amends were supervisor comments, not requirement changes")

    def test_tl_9un_12_supervisor_comments_after_a_cap_answer_never_ask_at_the_replan_cap(self):
        self.cap_answered_rerun()
        before = len(self.blocked)
        for n in range(3):  # more comment-only amends than the cap allows
            with self.stop_at("reviewer", 1), self.store.stub(comments=[{"author": "supervisor", "text": f"Keep it small {n}."}]):
                self.run_engine({"plan": [PLAN], "write": [WRITE]}, max_rounds=1, max_replans=1)
            self.assertNotIn("re-planned", " ".join(self.blocked[before:]))
        amends = [e for e in self.eng.plan_log if "comments only" in e["why"]]
        self.assertTrue(amends and not any(e["counted"] for e in amends), self.eng.plan_log)
        self.assertLessEqual(self.eng.planned, 1 + 1 + self.eng.extra)  # the planner's total stays inside the cap

    def test_tl_9un_12_a_requirement_change_still_counts_against_the_replan_cap(self):
        self.cap_answered_rerun()
        with self.store.stub(show=dict(BEAD, description="Also say hi.")):
            self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, max_rounds=1, max_replans=1)
        self.assertTrue(self.eng.plan_log[-1]["counted"], self.eng.plan_log)

    def test_max_replans_is_read_from_the_config(self):
        self.stopped_run()
        with self.store.stub(show=dict(BEAD, description="v2")):
            rc, s = self.run_engine({}, max_replans=0)
        self.assertEqual(rc, 2)
        self.assertEqual(s.calls, [])
        self.assertIn("re-planned 1 times", self.ask()["why"])
        self.assertEqual(EngineConfig().max_replans, 2)

    def test_the_plan_is_in_the_checkpoint_the_moment_the_planner_answers(self):
        # d5f.38: a SIGTERM after the planner answered lost a finished plan before the checkpoint
        with mock.patch.object(
            Planner, "add_leftovers", side_effect=engine.Blocked("failed: stopped (SIGTERM)", kind=oc.Kind.PAUSE_KILLED)
        ):
            rc, _ = self.run_engine({"plan": [PLAN]})
        self.assertEqual(rc, 2)
        ck = self.checkpoint()
        self.assertEqual((ck["plan"]["summary"], ck["planned"], ck["step"]), ("do it", 1, "write"))
        rc, s = self.run_engine({"write": [WRITE, WRITE], "review": [CLEAN, CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertNotIn("planner", [c[0] for c in s.calls])

    def test_a_stop_during_the_checks_send_back_resumes_with_the_first_plan(self):
        cat = procsim.fake("cat <(echo x)", procsim.exits(1, "cat: '<(echo': No such file or directory"))
        bad = dict(PLAN, summary="first", stages=[dict(PLAN["stages"][0], checks=[cat])])
        with self.stop_at("planner", 2):
            rc, _ = self.run_engine({"plan": [bad, PLAN]})
        self.assertEqual(rc, 2)
        ck = self.checkpoint()
        self.assertEqual((ck["plan"]["summary"], ck["planned"], ck["planner_ref"]), ("first", 1, "ref-plan"))
        rc, s = self.run_engine({"write": [WRITE], "review": [CLEAN]})
        self.assertNotIn("planner", [c[0] for c in s.calls])
        self.assertEqual(s.calls[0][0], "worker")

    def test_the_decided_path_planner_call_counts_toward_the_cap(self):
        q = dict(PLAN, irreversible="push_shared", question="Which?", decided="the accepted requirement says A")
        rc, _s = self.run_engine({"plan": [q, PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(self.eng.planned, 2)

    def test_a_plan_with_a_question_or_too_many_stages_is_not_checkpointed_early(self):
        self.run_engine({"plan": [dict(PLAN, irreversible="push_shared", question="Old format or new?")]})
        self.assertNoCheckpoint()

    def test_checks_that_cannot_run_go_back_to_the_same_planner_thread_once_and_do_not_count(self):
        bad = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=["no-such-program-x f.txt", "echo a && echo b"])])
        rc, s = self.run_engine({"plan": [bad, PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["planner", "planner", "worker", "reviewer"])
        self.assertIsNone(s.calls[0][1])
        self.assertEqual(s.calls[1][1], "ref-plan")  # --resume of the planner thread
        self.assertIn("is not an executable here", s.prompts[1])
        self.assertIn("literal argument in an argv, not a shell operator", s.prompts[1])
        self.assertIn('["just", "name"]', s.prompts[1])
        self.assertIn("plan_sent_back", [r["cause"] for r in records(self.eng, "transition")])
        self.assertEqual(self.eng.planned, 1)
        self.assertLess(len(s.prompts[1]), 3000)

    def test_the_planner_is_told_to_read_less_and_inlines_short_worker_rules(self):
        base = Path(self.tmp.name, "base-cfg")
        sh("git", "clone", "-q", str(Path(self.tmp.name, "o.git")), str(base), cwd=self.tmp.name)
        (base / "docs" / "agents").mkdir(parents=True)
        (base / "docs" / "agents" / "codex.md").write_text("RULES-MARK: unity runs on the host\n")
        (base / "docs" / "agents" / "big.md").write_text("x" * 7000)
        sh("git", "add", "-A", cwd=base)
        sh("git", "commit", "-qm", "rules", cwd=base)
        sh("git", "push", "-q", "origin", "HEAD:main", cwd=base)
        _rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, worker_rules="docs/agents/codex.md")
        p = s.prompts[0]
        self.assertIn("RULES-MARK", p)
        self.assertNotIn("Read {}".format(self.wt / "docs/agents/codex.md"), p)
        self.assertIn("rg -n", p)
        self.assertIn("line ranges", p)
        self.assertIn("about 12 tool calls", p)
        self.assertNotIn("Read the code it names", p)
        self.assertLess(len(p.encode("utf-8")), 12 * 1024)
        _rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, worker_rules="docs/agents/big.md")
        self.assertNotIn("Read {}".format(self.wt / "docs/agents/big.md"), s.prompts[0])  # tl-7y6.6.1: a hard 3 KB cap, no path to read
        self.assertIn("x" * RULES_MAX, s.prompts[0])
        self.assertNotIn("x" * (RULES_MAX + 1), s.prompts[0])
        self.assertLess(len(s.prompts[0].encode("utf-8")), 12 * 1024)
