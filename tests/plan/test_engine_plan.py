"""Engine tests: the plan and the replan."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support.engine_case import CAP_PARKS, stop
from support.engine_land import EngineTest

from tltestkit.checks import typed
from tltestkit.plans import BEAD, CLEAN, FALSE, HAS_F, PLAN, WRITE, review
from tltestkit.shellkit import sh

# isort: split
import json
from pathlib import Path
from unittest import mock

from taskloop.app.run import engine
from tlgate.domain import planref
from tlgate.domain.names import log_var
from tlkernel import answers, plancheck
from tlkernel.config import EngineConfig
from tlkernel.ids import CheckId
from tlkernel.kinds import Kind
from tltestkit import fake_route, procsim
from tltestkit.cfgs import cfg_with
from tltestkit.logs import records
from tlwork.plan import prompts as pp
from tlwork.plan.planner import Planner
from tlwork.plan.prompts import REPLAN_CAP
from tlwork.plan.sendback import SendBack
from tlwork.prompts.common import RULES_MAX
from tlwork.write import prompts as wp
from tlwork.write import review_prompt as rp


class EnginePlanTest(EngineTest):
    def test_no_prompt_points_outside_the_worktree_the_brief_plan_and_replan_are_inline(self):
        # delegate 0.23 keeps Claude's file tools in the worktree: a path to the run dir is a file no step can read
        rc, s = self.run_engine({"plan": [PLAN, PLAN], "write": [WRITE, WRITE, WRITE],
                                 "review": [review(unmet=["a"]), CLEAN]}, max_rounds=1)
        assert rc == 0
        run = str(self.eng.run_dir)
        for role, p in zip([c[0] for c in s.calls], s.prompts, strict=False):
            assert run not in p, role
        assert "add f" in s.prompts[0] + s.prompts[1]        # the plan, inline in the write
        assert "the review still sends it back" in s.prompts[3]  # the replan's reason, inline

    def test_the_planner_puts_proof_files_under_evidence(self):
        _rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        assert str(self.eng.evidence_dir) in s.prompts[0]
        assert "screenshots" in s.prompts[0]

    def test_a_plan_check_that_re_runs_a_configured_check_is_found(self):
        cfg = cfg_with(checks=[{"id": "unity-tests", "cmd": "just unity-tests", "group": "tests"}])
        plan = typed(dict(PLAN, risks=[{"what": "x", "check": "env CI=1 just unity-tests"},
                                       {"what": "y", "check": "just unity-tests-extra"}]))
        got = planref.refusals(planref.plan_checks(plan), cfg)
        assert len(got) == 1
        assert "`unity-tests`" in got[0]
        assert log_var(CheckId("unity-tests")) == "TL_CHECK_LOG_UNITY_TESTS"

    def test_a_plan_with_just_unity_in_acceptance_is_sent_back_once(self):
        bad = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=["just unity-tests"])])
        procsim.fake("just unity-tests", procsim.exits(0))
        _rc, s = self.run_engine({"plan": [bad, PLAN], "write": [WRITE], "review": [CLEAN]},
                                checks=[{"id": "unity-tests", "cmd": "just unity-tests", "group": "tests"}])
        assert [c[0] for c in s.calls] == ["planner", "planner", "worker", "reviewer"]
        assert "runs the registered check `unity-tests`" in s.prompts[1]

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
        assert rc == 0
        assert "tampered" not in s.seen_plan
        assert "add f" in s.seen_plan

    def test_rounds_used_up_replan_once_then_stuck(self):
        rc, s = self.run_engine({"plan": [PLAN, PLAN], "write": [WRITE, WRITE],
                                 "review": [review(unmet=["x"]), review(unmet=["x"])]}, max_rounds=1, max_replans=1)
        assert rc == 2
        assert [c[0] for c in s.calls].count("planner") == 2
        assert "stuck" in self.blocked[0]

    def test_a_check_the_writer_flags_as_wrong_replans_at_once(self):
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[FALSE])])
        flag = dict(WRITE, bad_checks=[{"cmd": FALSE, "why": "it exits 1 whatever the code does"}])
        rc, s = self.run_engine({"plan": [plan, PLAN], "write": [flag, WRITE], "review": [CLEAN]})
        assert rc == 0
        assert [c[0] for c in s.calls] == ["planner", "worker", "planner", "worker", "reviewer"]
        assert "exits 1 whatever the code does" in (self.eng.run_dir / "replan.md").read_text()

    BEAD_CHECK = "bd list --label lane:live --json"

    def test_a_check_that_reads_the_tracker_is_sent_back_to_the_planner_once(self):
        # lifesim-fld.26.12: a stage check ran `bd list` for a follow-up bead; writers cannot run bd, so no code passed it
        bad = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[HAS_F, self.BEAD_CHECK])])
        rc, s = self.run_engine({"plan": [bad, PLAN], "write": [WRITE], "review": [CLEAN]})
        assert rc == 0
        assert [c[0] for c in s.calls] == ["planner", "planner", "worker", "reviewer"]
        assert "read the issue tracker" in s.prompts[1]
        assert self.BEAD_CHECK in s.prompts[1]
        assert "leftovers" in s.prompts[1]

    def test_a_plan_still_reading_the_tracker_after_one_rewrite_fails(self):
        bad = dict(PLAN, cases=[{"criterion": "a follow-up exists", "check": "cat .beads/issues.jsonl"}])
        _rc, s = self.run_engine({"plan": [bad, bad]})
        assert [c[0] for c in s.calls] == ["planner", "planner"]
        assert self.blocked == []
        assert "read the issue tracker" in self.said()

    def test_follow_up_work_in_the_plan_is_filed_by_the_engine(self):
        lo = {"title": "Track hard-to-undo moves", "why": "the plan wants it filed"}
        rc, _s = self.run_engine({"plan": [dict(PLAN, leftovers=[lo])], "write": [WRITE], "review": [CLEAN]})
        assert rc == 0
        assert sum(1 for c in self.bd_calls if c[:2] == ("create", lo["title"])) == 1
        assert "never reads the tracker" in pp.PLAN_PROMPT

    D5F58_Q = ("One older test stays red, and I need your call on it. Rule R10 says a lifer never idles while something "
               "is available, but that test says never repeat within the hour, no exceptions. Options: A) the test allows "
               "a sole-candidate repeat, B) raise min_score, C) change the seed. My recommendation is A.")

    def test_a_planner_question_an_accepted_requirement_decides_is_planned_again_citing_it(self):
        rc, s = self.run_engine({"plan": [dict(PLAN, irreversible="push_shared", question=self.D5F58_Q, decided=self.R10), PLAN],
                                 "write": [WRITE], "review": [CLEAN]})
        assert rc == 0, self.blocked
        assert self.ask() is None
        assert [c[0] for c in s.calls] == ["planner", "planner", "worker", "reviewer"]
        assert self.R10 in s.prompts[1]
        assert "never the requirement" in s.prompts[1]
        assert "decided" in s.prompts[0]
        causes = [json.loads(ln)["cause"] for ln in self.eng.log_path.read_text().splitlines() if '"transition"' in ln]
        assert "planner_decided" in causes

    def test_a_planner_that_asks_again_after_the_requirement_is_quoted_reaches_the_owner(self):
        ask = dict(PLAN, irreversible="push_shared", question=self.D5F58_Q, decided=self.R10)
        rc, s = self.run_engine({"plan": [ask, ask]})
        assert rc == 2
        assert self.ask()["kind"] == "decision"
        assert [c[0] for c in s.calls] == ["planner", "planner"]

    def test_follow_up_work_a_replan_names_again_is_not_filed_twice(self):
        lo = {"title": "Track hard-to-undo moves", "why": "the plan wants it filed"}
        with self.stop_at("reviewer", 2):
            self.run_engine({"plan": [dict(self.TWO, leftovers=[lo])], "write": [WRITE, WRITE], "review": [CLEAN]})
        with self.store.stub(show=dict(BEAD, description="Stage two: keep it small.")):
            rc, s = self.run_engine({"plan": [dict(self.TWO, stages=self.TWO["stages"][1:], leftovers=[lo])],
                                     "write": [WRITE], "review": [CLEAN]})
        assert rc == 0
        assert s.calls[0][0] == "planner"  # the changed bead re-planned, naming the same follow-up
        assert sum(1 for c in self.bd_calls if c[:2] == ("create", lo["title"])) == 1

    def test_a_replan_keeps_the_stages_already_accepted(self):
        one_left = dict(self.TWO, stages=[dict(self.TWO["stages"][1], goal="stage two, again")])
        rc, s = self.run_engine({"plan": [self.TWO, one_left], "write": [WRITE] * 4,
                                 "review": [CLEAN, review(unmet=["a"]), review(unmet=["b"]), CLEAN]}, max_rounds=2)
        assert rc == 0
        roles = [c[0] for c in s.calls]
        assert roles == ["planner", "worker", "reviewer", "worker", "reviewer", "worker", "reviewer",
                                 "planner", "worker", "reviewer"]
        replan = s.prompts[7]
        assert "already accepted" in replan
        assert "stage one" in replan
        assert "stage two, again" in s.prompts[8]

    def test_a_changed_bead_keeps_accepted_stages_and_replans_the_rest(self):
        with self.stop_at("reviewer", 2):
            self.run_engine({"plan": [self.TWO], "write": [WRITE, WRITE], "review": [CLEAN]})
        bead = dict(BEAD, description="Add the file f, and say hi.")
        one_left = dict(self.TWO, stages=[self.TWO["stages"][1]])
        with self.store.stub(show=bead):
            rc, s = self.run_engine({"plan": [one_left], "write": [WRITE], "review": [CLEAN]})
        assert rc == 0
        assert [c[0] for c in s.calls] == ["planner", "worker", "reviewer"]
        assert "already accepted" in s.prompts[0]

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
        assert rc == 0, self.blocked
        assert [c[0] for c in s.calls] == ["reviewer"]  # the write and checks were green: the review goes on (tl-q3ma)
        assert "outcome=failed" not in s.prompts[0]  # tl-7y6.6.2: no engine record in the brief, so none in the prompt

    def test_the_last_stage_note_reaches_a_resumed_writer(self):
        two = dict(PLAN, stages=[dict(PLAN["stages"][0], goal="first"), dict(PLAN["stages"][0], goal="second")])
        rc, s = self.run_engine({"plan": [two], "write": [WRITE, WRITE], "review": [CLEAN, CLEAN]},
                                j_extra={"write": [{"family": "claude"}] * 2}, worker_rules="a.txt")
        assert rc == 0, self.blocked
        assert s.calls[3][1] == "ref-write"
        assert "acceptance cases run on this last stage" in s.prompts[3]
        assert "new_cases" in s.prompts[3]
        assert "acceptance cases run on this last stage" not in s.prompts[1]
        assert "a.txt" not in s.prompts[3]  # tl-7y6.6.1: the rules are in the first prompt only; a resume never says Read <rules>
        assert "Read " not in s.prompts[3]
        assert "worker_rules" not in s.prompts[3]

    def test_replans_count_across_runs(self):
        with self.stop_at("reviewer", 3):  # stage 1 sent back twice -> replan; stopped in the new plan's review
            self.run_engine({"plan": [PLAN, PLAN], "write": [WRITE] * 3,
                             "review": [review(unmet=["a"]), review(unmet=["b"])]}, max_rounds=2, max_replans=1)
        assert self.checkpoint()["replans"] == 1
        rc, s = self.run_engine({"write": [WRITE] * 2, "review": [review(unmet=["c"]), review(unmet=["d"])]},
                                max_rounds=2, max_replans=1)
        assert rc == 2
        assert "re-plan" in self.blocked[-1]
        assert "planner" not in [c[0] for c in s.calls]

    def test_acceptance_cases_run_on_the_last_stage_only(self):
        seen, case = self.counter("case")
        plan = dict(self.TWO, cases=[{"criterion": "f.txt exists", "check": case}])
        rc, s = self.run_engine({"plan": [plan], "write": [WRITE, WRITE], "review": [CLEAN, CLEAN]})
        assert rc == 0
        assert seen.read_text() == "1"  # stage 2 of 2, not stage 1
        assert "f.txt exists" in s.prompts[0] + s.prompts[3]

    def test_a_fix_round_runs_the_acceptance_cases_again(self):
        seen, case = self.counter("case")
        plan = dict(PLAN, cases=[{"criterion": "f.txt exists", "check": case}])
        gate = procsim.fake("red-on-d2", lambda cwd, env: (1 if procsim.f_txt(cwd) == "d2" else 0, ""))
        rc, _s = self.run_engine({"plan": [plan], "write": [WRITE, WRITE], "review": [CLEAN, CLEAN]}, gate=gate)
        assert rc == 0
        assert seen.read_text() == "11"

    def test_a_planner_question_is_a_decision_ask_on_the_bead(self):
        rc, _ = self.run_engine({"plan": [dict(PLAN, irreversible="push_shared", question="Old format or new?")]})
        assert rc == 2
        a = self.ask()
        assert (a["kind"], a["class"], a["status"]) == ("decision", "open_question", "open")
        assert a["decision"] == "Old format or new?"
        assert a["detail"]["text"] == "Old format or new?"
        assert any(c[:2] == ("comments", "add") and "{} (decision)".format(a["id"]) in c[3] for c in self.bd_calls)

    def test_a_used_up_replan_is_a_stuck_ask(self):
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [review(unmet=["a"])]},
                                max_rounds=1, max_replans=0)
        assert rc == 2
        assert self.ask()["kind"] == "stuck"

    def test_a_decision_ask_carries_the_options_the_planner_gave(self):
        rc, _ = self.run_engine({"plan": [dict(PLAN, irreversible="push_shared", question="Build now or park?", options=self.CHOICES)]})
        assert rc == 2
        assert [(o["label"], o["text"], o["cost"], o["recommended"], o["action"]) for o in self.ask()["options"]] == [
                ("Keep parked", "B: keep it parked", "none", True, "text"),
                ("Build it", "A: build the slice now", "about 4 stages", False, "text"),
            ]

    def test_the_decision_schemas_require_options(self):
        for node in ("plan", "write", "review"):
            sch = answers.schema_for(node)
            assert "options" in sch["required"]
            assert sch["properties"]["options"]["items"]["required"] == ["label", "cost", "answer", "recommended"]
            assert "options: with a question, 2-4 answers" in {"plan": pp.PLAN_PROMPT, "write": wp.WRITE_PROMPT,
                                                                     "review": rp.REVIEW_PROMPT}[node]
        ok = {"label": "A", "cost": "c", "answer": "a", "recommended": True}
        assert answers.check("plan", False, plancheck.to_wire(dict(PLAN, options=[ok]))) == []
        bare = {k: v for k, v in plancheck.to_wire(PLAN).items() if k != "options"}
        assert answers.check("plan", False, bare) == ["PlanAnswer.options: missing"]
        assert (
            answers.check("plan", False, plancheck.to_wire(dict(PLAN, options=[{"label": "A"}])))
            == ["PlanAnswer.options[0].cost: missing"]
        )  # msgspec reports the first violation only

    def test_a_verify_answer_with_a_yes_and_a_change_plans_it(self):
        more = dict(PLAN, stages=[dict(PLAN["stages"][0], goal="test Y")])
        with self.store.stub(comments=self.verify_then_answer("text", "right, but add a test for Y")):
            rc, s = self.run_engine({"plan": [more], "write": [WRITE], "review": [CLEAN]})
        assert rc == 0, self.blocked
        assert [c[0] for c in s.calls] == ["planner", "worker", "reviewer"]

    def test_a_verify_answer_asking_for_more_work_plans_it_keeping_the_accepted_stages(self):
        # lifesim-fld.26.15: 'add a test that ..., then land' went straight to land without the test
        text = "add a test that f.txt is not empty, then land"
        more = dict(PLAN, stages=[dict(PLAN["stages"][0], goal="test f.txt")])
        with self.store.stub(comments=self.verify_then_answer("text", text)):
            rc, s = self.run_engine({"plan": [more], "write": [WRITE], "review": [CLEAN]})
        assert rc == 0, self.blocked
        assert [c[0] for c in s.calls] == ["planner", "worker", "reviewer"]
        assert text in s.prompts[0]
        assert "- add f\n" in s.prompts[0]  # the accepted stage, not planned again
        assert self.eng.state.replans == 0

    def test_a_bead_without_acceptance_criteria_is_a_ticket_and_never_planned(self):
        with self.store.stub(show={"id": "t-1", "title": "Add f", "metadata": {}, "description": "Add f."}):
            rc, s = self.run_engine({"plan": [PLAN]})
        assert rc == 2
        assert s.calls == []
        assert self.ask()["kind"] == "ticket"

    def test_a_plan_of_more_than_three_stages_is_a_split_ticket(self):
        four = dict(PLAN, stages=[dict(PLAN["stages"][0], goal=f"part {k}") for k in range(4)])
        rc, s = self.run_engine({"plan": [four]})
        assert rc == 2
        assert [c[0] for c in s.calls] == ["planner"]
        a = self.ask()
        assert a["kind"] == "ticket"
        assert "part 3" in self.card()

    def test_fail_on_a_plan_fails_the_task_without_retry(self):
        bad = stop("worker_failed", say="the worker exited 1")
        rc, s = self.run_engine({"plan": [bad]})
        assert rc == 2
        assert len(s.calls) == 1
        assert self.blocked == []
        assert "the worker exited 1" in self.said()

    def test_a_changed_bead_amends_the_old_plan_it_does_not_plan_again(self):
        self.stopped_run(plan=self.TWO, answers={"plan": [self.TWO], "write": [WRITE]})
        with self.store.stub(show=dict(BEAD, description="Also say hi.")), \
                self.store.stub(comments=[{"author": "denis", "text": "Keep it small."}]):
            rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        assert rc == 0, self.blocked
        p = s.prompts[0]
        assert "<old_plan>" in p
        assert "stage one" in p
        assert "smallest change" in p
        assert "do not re-explore code the old plan already names" in p
        assert "description changed:" in p
        assert "+Also say hi." in p
        assert "new comment:\nKeep it small." in p
        assert self.eng.plan_log[-1].mode == "amend"

    def test_a_comment_alone_is_not_an_amend_and_costs_no_replan(self):
        self.stopped_run(plan=self.TWO, answers={"plan": [self.TWO], "write": [WRITE]})
        with self.store.stub(show=BEAD), \
                self.store.stub(comments=[{"author": "denis", "text": "Fresh start: use the other slot."}]):
            rc, s = self.run_engine({"write": [WRITE, WRITE], "review": [CLEAN, CLEAN]})
        assert rc == 0, self.blocked
        assert "planner" not in [c[0] for c in s.calls]
        assert "an edit with no ask" not in self.eng.log_path.read_text()
        assert "nothing the plan reads" in self.eng.log_path.read_text()

    def only_engine_written(self, name):
        noise, _ = self.engine_noise(name)
        assert len(noise) > 1, "the fixture has engine comments"
        self.stopped_run()
        with self.store.stub(show=dict(BEAD, notes="Engine paused: paused: no lane for write")), \
                self.store.stub(comments=noise):
            rc, s = self.run_engine({"write": [WRITE, WRITE], "review": [CLEAN, CLEAN]})
        assert rc == 0, self.blocked
        log = self.eng.log_path.read_text()
        assert "planner" not in [c[0] for c in s.calls]
        assert "an edit with no ask" not in log
        assert "amending its plan" not in log
        assert self.eng.planned == 1  # the first plan only: nothing charged
        assert self.ask() is None

    def test_o67g_engine_comments_and_notes_cost_no_replan(self):
        self.only_engine_written(CAP_PARKS[0])

    def test_yxbb2_engine_comments_and_notes_cost_no_replan(self):
        self.only_engine_written(CAP_PARKS[1])

    def test_d5f40_engine_comments_and_notes_cost_no_replan(self):
        self.only_engine_written(CAP_PARKS[2])

    def test_an_owner_answer_to_an_ask_amends_the_plan_with_the_answer(self):
        ask = dict(WRITE, question="Which format?")
        rc, _ = self.run_engine({"plan": [PLAN], "write": [ask]})
        assert rc == 2
        assert self.ask()["kind"] == "decision"
        with self.store.stub(comments=[{"author": "denis", "text": "Use the new format."}]):
            rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        assert rc == 0, self.blocked
        assert s.calls[0][0] == "planner"
        assert "<old_plan>" in s.prompts[0]
        assert "Use the new format." in s.prompts[0]
        assert "the owner answered ask t-1-1" in self.eng.plan_log[-1].why

    def test_a_bead_that_changed_in_nothing_the_plan_reads_keeps_its_plan_and_calls_no_planner(self):
        self.stopped_run()
        with self.store.stub(show=dict(BEAD, labels=["urgent"])):
            rc, s = self.run_engine({"write": [WRITE, WRITE], "review": [CLEAN, CLEAN]})
        assert rc == 0, self.blocked
        assert "planner" not in [c[0] for c in s.calls]
        assert "keeping the plan, no planner run" in self.eng.log_path.read_text()

    def test_a_branch_changed_since_the_checkpoint_amends_instead_of_planning_again(self):
        self.stopped_run()
        sh("git", "checkout", "-q", "task/t-1", cwd=self.wt)  # a parked slot is left detached at the base
        (self.wt / "g.txt").write_text("someone edited it\n")
        sh("git", "add", "-A", cwd=self.wt)
        sh("git", "commit", "-qm", "by hand", cwd=self.wt)
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        assert rc == 0, self.blocked
        assert "<old_plan>" in s.prompts[0]
        assert "The branch changed outside the engine" in s.prompts[0]
        assert "by hand" in s.prompts[0]

    def test_an_in_run_replan_amends_with_the_old_plan_and_the_failure_tail(self):
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[FALSE])])
        flag = dict(WRITE, bad_checks=[{"cmd": FALSE, "why": "it exits 1 whatever the code does"}])
        rc, s = self.run_engine({"plan": [plan, PLAN], "write": [flag, WRITE], "review": [CLEAN]})
        assert rc == 0
        again = s.prompts[2]
        assert "<old_plan>" in again
        assert json.dumps(FALSE)[1:-1] in again  # the plan is quoted as JSON: a Windows path has doubled backslashes
        assert "it exits 1 whatever the code does" in again
        assert [e.mode for e in self.eng.plan_log] == ["plan", "amend"]

    def test_the_stage_level_cap_is_the_replan_cap_ask_and_allow_one_more_works_on_it(self):
        rc, _s = self.run_engine({"plan": [PLAN, PLAN], "write": [WRITE, WRITE],
                                 "review": [review(unmet=["x"]), review(unmet=["x"])]}, max_rounds=1, max_replans=1)
        assert rc == 2
        a = self.ask()
        assert a["why"].startswith(REPLAN_CAP), a["why"]
        assert "stage 1 stuck after 1 rounds" in a["why"]
        assert "allow one more" in self.card().lower()
        self.file_answer("rerun")
        rc, _s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, max_rounds=1, max_replans=1)
        assert rc == 0, self.blocked
        assert self.eng.extra == 1

    def cap_answered_rerun(self):
        """Run to the stage-level cap (max_replans=1), answer 'allow one more run' with a typed word."""
        rc, _s = self.run_engine({"plan": [PLAN, PLAN], "write": [WRITE, WRITE],
                                 "review": [review(unmet=["x"]), review(unmet=["x"])]}, max_rounds=1, max_replans=1)
        assert rc == 2
        self.file_answer("rerun", "Allow one more run. The amends were supervisor comments, not requirement changes")

    def test_tl_9un_12_owner_comments_after_a_cap_answer_never_ask_at_the_replan_cap(self):
        self.cap_answered_rerun()
        before = len(self.blocked)
        for n in range(3):  # more comment-only amends than the cap allows
            with self.stop_at("reviewer", 1), self.store.stub(comments=[{"author": "denis", "text": f"Keep it small {n}."}]):
                self.run_engine({"plan": [PLAN], "write": [WRITE]}, max_rounds=1, max_replans=1)
            assert "re-planned" not in " ".join(self.blocked[before:])
        amends = [e for e in self.eng.plan_log if "comments only" in e.why]
        assert amends and not any(e.counted for e in amends), self.eng.plan_log
        assert self.eng.planned <= 1 + 1 + self.eng.extra  # the planner's total stays inside the cap

    def test_tl_9un_12_a_requirement_change_still_counts_against_the_replan_cap(self):
        self.cap_answered_rerun()
        with self.store.stub(show=dict(BEAD, description="Also say hi.")):
            self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, max_rounds=1, max_replans=1)
        assert self.eng.plan_log[-1].counted, self.eng.plan_log

    def test_max_replans_is_read_from_the_config(self):
        self.stopped_run()
        with self.store.stub(show=dict(BEAD, description="v2")):
            rc, s = self.run_engine({}, max_replans=0)
        assert rc == 2
        assert s.calls == []
        assert "re-planned 1 times" in self.ask()["why"]
        assert EngineConfig().max_replans == 2

    def test_the_plan_is_in_the_checkpoint_the_moment_the_planner_answers(self):
        # d5f.38: a SIGTERM after the planner answered lost a finished plan before the checkpoint
        with mock.patch.object(
            Planner, "add_leftovers", side_effect=engine.Blocked("failed: stopped (SIGTERM)", kind=Kind.PAUSE_KILLED)
        ):
            rc, _ = self.run_engine({"plan": [PLAN]})
        assert rc == 2
        ck = self.checkpoint()
        assert (ck["plan"]["summary"], ck["planned"], ck["step"]) == ("do it", 1, "write")
        with mock.patch.object(SendBack, "find", side_effect=AssertionError("a write checkpoint is already validated")):
            rc, s = self.run_engine({"write": [WRITE, WRITE], "review": [CLEAN, CLEAN]})
        assert rc == 0, self.blocked
        assert "planner" not in [c[0] for c in s.calls]

    def test_a_stop_during_the_checks_send_back_resumes_with_the_first_plan(self):
        cat = procsim.fake("cat <(echo x)", procsim.exits(1, "cat: '<(echo': No such file or directory"))
        bad = dict(PLAN, summary="first", stages=[dict(PLAN["stages"][0], checks=[cat])])
        with self.stop_at("planner", 2):
            rc, _ = self.run_engine({"plan": [bad, PLAN]})
        assert rc == 2
        ck = self.checkpoint()
        assert (ck["plan"]["summary"], ck["planned"], ck["planner_ref"]) == ("first", 1, "ref-plan")
        rc, s = self.run_engine({"write": [WRITE], "review": [CLEAN]})
        assert "planner" not in [c[0] for c in s.calls]
        assert s.calls[0][0] == "worker"

    def test_the_decided_path_planner_call_counts_toward_the_cap(self):
        q = dict(PLAN, irreversible="push_shared", question="Which?", decided="the accepted requirement says A")
        rc, _s = self.run_engine({"plan": [q, PLAN], "write": [WRITE], "review": [CLEAN]})
        assert rc == 0, self.blocked
        assert self.eng.planned == 2

    def test_a_plan_with_a_question_or_too_many_stages_is_not_checkpointed_early(self):
        self.run_engine({"plan": [dict(PLAN, irreversible="push_shared", question="Old format or new?")]})
        self.assertNoCheckpoint()

    def test_checks_that_cannot_run_go_back_to_the_same_planner_thread_once_and_do_not_count(self):
        bad = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=["no-such-program-x f.txt", "echo a && echo b"])])
        rc, s = self.run_engine({"plan": [bad, PLAN], "write": [WRITE], "review": [CLEAN]})
        assert rc == 0, self.blocked
        assert [c[0] for c in s.calls] == ["planner", "planner", "worker", "reviewer"]
        assert s.calls[0][1] is None
        assert s.calls[1][1] == "ref-plan"  # --resume of the planner thread
        assert "is not an executable here" in s.prompts[1]
        assert "literal argument in an argv, not a shell operator" in s.prompts[1]
        assert '["just", "name"]' in s.prompts[1]
        assert "plan_sent_back" in [r["cause"] for r in records(self.eng, "transition")]
        assert self.eng.planned == 1
        assert len(s.prompts[1]) < 3000

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
        assert "RULES-MARK" in p
        assert "Read {}".format(self.wt / "docs/agents/codex.md") not in p
        assert "rg -n" in p
        assert "line ranges" in p
        assert "about 12 tool calls" in p
        assert "Read the code it names" not in p
        assert len(p.encode("utf-8")) < 12 * 1024
        _rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, worker_rules="docs/agents/big.md")
        assert "Read {}".format(self.wt / "docs/agents/big.md") not in s.prompts[0]  # tl-7y6.6.1: a hard 3 KB cap, no path to read
        assert "x" * RULES_MAX in s.prompts[0]
        assert "x" * (RULES_MAX + 1) not in s.prompts[0]
        assert len(s.prompts[0].encode("utf-8")) < 12 * 1024
