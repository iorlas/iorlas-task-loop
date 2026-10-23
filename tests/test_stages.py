"""tl-bxk.13: stage handoffs (docs/design/stages.md). Reuses test_engine's harness without re-running its tests."""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_engine as te  # noqa: E402
from test_engine import BEAD, CLEAN, FALSE, HAS_F, PLAN, WRITE, engine, tl  # noqa: E402,F401


class StagesTest(unittest.TestCase):
    setUp = te.EngineTest.setUp
    tearDown = te.EngineTest.tearDown
    fake_bd = te.EngineTest.fake_bd
    commit_base_cfg = te.EngineTest.commit_base_cfg
    run_engine = te.EngineTest.run_engine
    checks_engine = te.EngineTest.checks_engine

    def created(self):
        return [a[1] for a in self.bd_calls if a and a[0] == "create"]


class EmptyPlan(StagesTest):
    """13.2: the planner says the work is done and only follow-up beads are left."""

    def test_an_empty_plan_with_leftovers_files_them_and_closes_done(self):
        plan = dict(PLAN, stages=[], leftovers=[{"title": "File the table bead", "why": "the sheet lists a table"}])
        rc, s = self.run_engine({"plan": [plan]})
        self.assertEqual(rc, 0)
        self.assertEqual([c[0] for c in s.calls], ["planner"])
        self.assertEqual(self.created(), ["File the table bead"])
        self.assertTrue(self.closed and self.closed[0].startswith("done with nothing to land"))
        self.assertEqual(self.blocked, [])

    def test_an_empty_plan_with_nothing_to_file_still_fails(self):
        rc, s = self.run_engine({"plan": [dict(PLAN, stages=[])]})
        self.assertNotEqual(rc, 0)
        self.assertTrue(self.blocked and "no stages" in self.blocked[0])

    def test_an_empty_plan_over_work_no_review_accepted_is_not_done(self):
        te.sh("git", "checkout", "-qb", "task/t-1", cwd=self.wt)
        (self.wt / "g.txt").write_text("half done\n")
        te.sh("git", "add", "-A", cwd=self.wt)
        te.sh("git", "commit", "-qm", "wip", cwd=self.wt)
        te.sh("git", "checkout", "-q", "-", cwd=self.wt)
        plan = dict(PLAN, stages=[], leftovers=[{"title": "File the table bead", "why": "x"}])
        rc, s = self.run_engine({"plan": [plan]})
        self.assertNotEqual(rc, 0)
        self.assertTrue(self.blocked and "no stages" in self.blocked[0])
        self.assertEqual(self.created(), [])

    def test_done_when_counts_as_acceptance_criteria(self):
        has = engine.has_criteria
        self.assertFalse(has({"description": "Done when? tbd"}))
        self.assertTrue(has({"description": "Goal.\n\n## Done when\n- x works\n"}))
        self.assertTrue(has({"description": "Goal.\n\nDone when: x works"}))
        self.assertTrue(has({"description": "Goal.\n\n**Done when**\n- x works"}))
        self.assertTrue(has({"description": "## Acceptance Criteria\n- x"}))
        self.assertFalse(has({"description": "Goal only."}))
        self.assertFalse(has({"description": "## Done when\n\n## Notes\nnothing"}))
        self.assertFalse(has({"description": ""}))


class BadChecks(StagesTest):
    """13.3: the writer names a broken check loosely; the engine still finds it."""

    LONG = FALSE + " ; echo padding-so-the-check-is-long-enough-to-shorten"

    def test_flagged_why_matches_loose_names(self):
        c = {"id": "x", "cmd": "grep -qE 'name=\"GameLogTests\"[^>]*result=\"Passed\"' client/Logs/unity-tests.xml"}
        why = engine.flagged_why
        self.assertEqual(why(c, [{"cmd": c["cmd"], "why": "a"}]), "a")
        self.assertEqual(why(c, [{"cmd": "grep   -qE 'name=\"GameLogTests\"[^>]*result=\"Passed\"'\nclient/Logs/unity-tests.xml", "why": "b"}]), "b")
        self.assertEqual(why(c, [{"cmd": "grep -qE 'name=\"GameLogTests\"...unity-tests.xml", "why": "c"}]), "c")
        self.assertEqual(why(c, [{"cmd": "`" + c["cmd"] + "`", "why": "d"}]), "d")
        self.assertEqual(why(dict(c, id="unity-tests"), [{"cmd": "unity-tests", "why": "e"}]), "e")
        self.assertEqual(why(c, [{"cmd": "grep -qE 'other'...nothing.xml", "why": "f"}]), "")
        self.assertEqual(why(c, [{"cmd": "grep", "why": "g"}]), "")  # too short to say which check
        self.assertEqual(why(c, []), "")
        mine = {"id": "u", "cmd": "python3 -m unittest discover -s tests -p 'test_a.py'"}
        self.assertEqual(why(mine, [{"cmd": "python3 -m unittest discover -s tests", "why": "h"}]), "")  # another, shorter check

    def test_a_shortened_bad_check_replans_at_once(self):
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[self.LONG])])
        cmd = plan["stages"][0]["checks"][0]
        flag = dict(WRITE, bad_checks=[{"cmd": cmd[:25] + "..." + cmd[-12:], "why": "cannot pass"}])
        rc, s = self.run_engine({"plan": [plan, PLAN], "write": [flag, WRITE], "review": [CLEAN]})
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "planner", "worker", "reviewer"])


class Deferred(StagesTest):
    """13.1: the reviewer is told what the plan set aside; 'file beads' is an engine step; an owner item with a bead lands."""

    LEFT = [{"title": "File the table and chair beads", "why": "the sheet lists them; the engine files them"}]

    def eng_(self):
        return engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))

    def test_the_review_prompt_lists_what_the_plan_set_aside(self):
        rc, s = self.run_engine({"plan": [dict(PLAN, leftovers=self.LEFT)], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        review = s.prompts[2]
        self.assertIn("Already set aside", review)
        self.assertIn("File the table and chair beads", review)
        self.assertIn("Never list one as unmet", review)

    def test_no_set_aside_section_without_leftovers(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertNotIn("Already set aside", s.prompts[2])

    def test_filing_beads_in_any_wording_is_an_engine_step_when_there_are_leftovers(self):
        e = self.eng_()
        for w in ("File beads for the table, chairs and sink", "Follow-up beads for each object are to be filed",
                  "The nine beads are not filed", "Create a bead per object", "file follow-up tasks"):
            self.assertFalse(e.engine_does(w), w + " (no leftovers yet)")
        e.leftovers = [{"title": "x", "why": "y"}]
        for w in ("File beads for the table, chairs and sink", "Follow-up beads for each object are to be filed",
                  "The nine beads are not filed", "Create a bead per object", "file follow-up tasks"):
            self.assertTrue(e.engine_does(w), w)
        self.assertFalse(e.engine_does("The beads cover all nine objects"))  # a claim about the result goes to the verifier

    def test_an_owner_item_with_an_owner_review_bead_in_the_leftovers_lands_unverified(self):
        e = self.eng_()
        e.leftovers = [{"title": "Owner review of the retuned knob values and placeholder art", "why": "iqad"}]
        item = {"what": "Owner sign-off on the retuned knob values and the placeholder art", "kind": "owner_decision"}
        self.assertTrue(e.backed_by_leftover(item["what"]))
        self.assertEqual(e.engine_steps([item]), [])
        self.assertEqual([u["what"] for u in e.unverified], [item["what"]])
        other = {"what": "Whether the storyteller preset is the intended default", "kind": "owner_decision"}
        self.assertEqual(e.engine_steps([other]), [other])
        e.leftovers = [{"title": "Tune the knob values and placeholder art", "why": "later"}]  # not an owner bead
        self.assertFalse(e.backed_by_leftover(item["what"]))
        e.leftovers = [{"title": "Owner review of retry timeout defaults", "why": "unrelated"}]
        self.assertFalse(e.backed_by_leftover(item["what"]))

    def test_beads_in_other_sentences_are_not_the_filing_step(self):
        e = self.eng_()
        e.leftovers = [{"title": "x", "why": "y"}]
        for w in ("The config file lists the bead ids", "No open beads remain in the epic", "Open the bead and read it"):
            self.assertFalse(e.engine_does(w), w)


class Scope(StagesTest):
    """13.5: a checkable note outside the done-when is a follow-up, not a verify gap."""

    def test_an_item_outside_the_done_when_is_filed_not_verified(self):
        e = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        e.scope = "Acceptance Criteria\n- the soak passes with three lifers across five seeds"
        e.plan_data = dict(PLAN)
        inside = {"what": "the soak holds with three lifers on seed 4", "kind": "checkable"}
        outside = {"what": "Sit To Stand and Laying Sleeping poses were not probed", "kind": "checkable"}
        taste = {"what": "Sit To Stand and Laying Sleeping poses look right", "kind": "taste"}
        self.assertEqual(e.out_of_scope([inside, outside, taste]), [inside, taste])
        self.assertEqual(len(e.leftovers), 1)
        self.assertIn("Sit To Stand", e.leftovers[0]["title"])

    def test_with_no_acceptance_text_nothing_moves(self):
        e = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        item = {"what": "Sit To Stand was not probed", "kind": "checkable"}
        self.assertEqual(e.out_of_scope([item]), [item])
        self.assertEqual(e.leftovers, [])

    def test_non_latin_text_is_compared_and_a_note_is_filed_once(self):
        e = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        e.scope = "Done when: суп варится три минуты"
        e.plan_data = dict(PLAN)
        inside = {"what": "суп варится три минуты на плите", "kind": "checkable"}
        outside = {"what": "wallpaper colour not probed", "kind": "checkable"}
        self.assertEqual(e.out_of_scope([inside, outside]), [inside])
        e.out_of_scope([outside])
        self.assertEqual(len(e.leftovers), 1)

    def test_acceptance_text_reads_the_field_and_the_description_from_the_heading(self):
        txt = engine.acceptance_text({"acceptance_criteria": "A works", "description": "Intro.\n## Done when\n- B works\n"})
        self.assertIn("A works", txt)
        self.assertIn("B works", txt)
        self.assertNotIn("Intro", txt)

    def test_a_note_outside_the_done_when_does_not_stop_the_run(self):
        with mock.patch.object(tl, "show", return_value=dict(BEAD, acceptance_criteria="f.txt exists and holds data")):
            review = dict(CLEAN, unchecked=[{"what": "the wallpaper colour was not probed", "kind": "checkable", "source": ""}])
            rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [review]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer"])
        self.assertTrue(any("wallpaper" in t for t in self.created()))


class Handoff(StagesTest):
    """13.6, 13.7: the rounds reach the planner of an amend; lows are not listed twice; a big writer starts the next stage fresh."""

    def test_the_amend_planner_sees_what_the_rounds_did(self):
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[FALSE])])
        flag = dict(WRITE, summary="tried the rename", bad_checks=[{"cmd": FALSE, "why": "it exits 1 whatever the code does"}])
        rc, s = self.run_engine({"plan": [plan, PLAN], "write": [flag, WRITE], "review": [CLEAN]})
        amend = s.prompts[2]
        self.assertIn("<rounds>", amend)
        self.assertIn("tried the rename", amend)
        self.assertIn("bad_checks", amend)
        handoff = json.loads((self.eng.run_dir / "handoff.json").read_text())
        self.assertEqual(handoff["rounds"][0]["kind"], "bad_checks")

    def test_a_low_finding_is_not_listed_again_by_the_next_review(self):
        first = dict(CLEAN, findings=[te.finding("medium"), dict(te.finding("low"), fix="rename the helper")])
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, WRITE], "review": [first, CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        reviews = [p for p, c in zip(s.prompts, s.calls) if c[0] == "reviewer"]
        self.assertNotIn("already noted", reviews[0])
        self.assertIn("already noted", reviews[1])
        self.assertIn("rename the helper", reviews[1])

    def test_the_rounds_text_keeps_the_newest_within_its_cap(self):
        e = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        for k in range(8):
            e.note_round("stage 1/1", k + 1, "review", "w" * 300, ["x" * 200])
        text = e.rounds_text()
        self.assertLessEqual(len(text), engine.HANDOFF_CAP + 700)
        self.assertIn("round 8", text)
        self.assertNotIn("round 1,", text)

    TWO = dict(PLAN, stages=[PLAN["stages"][0], dict(PLAN["stages"][0], goal="add g")])

    def boundary(self, ctx_k, **cfg):
        path = Path(self.tmp.name, "session.jsonl")
        n = int(ctx_k * 1000) - 100
        path.write_text(json.dumps({"type": "user"}) + "\n" + json.dumps({"type": "assistant", "message": {"usage": {
            "input_tokens": 3, "cache_read_input_tokens": n, "cache_creation_input_tokens": 97}}}) + "\n")
        extra = {"family": "claude", "transcript": str(path)}
        return self.run_engine({"plan": [self.TWO], "write": [WRITE, WRITE], "review": [CLEAN, CLEAN]},
                               j_extra={"write": [extra, extra]}, **cfg)

    def test_a_writer_session_over_100k_starts_the_next_stage_fresh(self):
        rc, s = self.boundary(120)  # under the 150k a claude session may grow to inside a stage
        self.assertEqual(rc, 0, self.blocked)
        writes = [(p, c) for p, c in zip(s.prompts, s.calls) if c[0] == "worker"]
        self.assertIsNone(writes[1][1][1])
        self.assertIn("fresh session for the next one", writes[1][0])
        self.assertIn("add f", writes[1][0])  # the accepted stage's goal

    def test_a_smaller_session_goes_on_and_the_limit_is_the_repos_to_set(self):
        rc, s = self.boundary(90)
        self.assertEqual([c[1] for c in s.calls if c[0] == "worker"][1], "ref-write")
        rc, s = self.boundary(120, write_fresh_above_k=0)  # 0 is never, for the stage boundary too
        self.assertEqual([c[1] for c in s.calls if c[0] == "worker"][1], "ref-write")
        rc, s = self.boundary(120, write_fresh_stage_k=0)
        self.assertEqual([c[1] for c in s.calls if c[0] == "worker"][1], "ref-write")


class RepeatedChecks(StagesTest):
    """13.4: a slow command wrapped in two checks, or around a repo check, goes back to the planner once."""

    def wrap(self, out):
        return "mkdir -p ev && just unity-tests > ev/%s.out 2>&1 && grep -q Passed ev/%s.out" % (out, out)

    def test_repeats_are_found_through_redirects_and_wrappers(self):
        e = engine.Engine("t-1", str(self.wt), dict(engine.load_cfg(str(self.wt)), checks=[
            {"id": "tests", "cmd": "just fast-tests", "group": "tests"}]))
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[self.wrap("a"), self.wrap("b"), "just fast-tests", "just lint"])],
                    cases=[{"criterion": "c", "check": self.wrap("c")}])
        got = {part: len(cs) for part, cs, rid in e.repeated_slow(plan)}
        self.assertEqual(got, {"just unity-tests": 3})
        self.assertEqual(e.repeated_slow(dict(PLAN, stages=[dict(PLAN["stages"][0], checks=["just unity-tests", "just unity-tests"])])), [])
        two = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[self.wrap("a")]), dict(PLAN["stages"][0], checks=[self.wrap("b")])])
        self.assertEqual(e.repeated_slow(two), [])  # two stages' checks run in two rounds
        wrapped = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=["mkdir -p ev && just fast-tests > ev/o 2>&1"])])
        self.assertEqual([(p, rid) for p, cs, rid in e.repeated_slow(wrapped)], [])  # not slow by name or history
        e.cfg["checks"][0]["cmd"] = "just unity-tests"
        one = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[self.wrap("a")])])
        self.assertEqual([(p, rid) for p, cs, rid in e.repeated_slow(one)], [("just unity-tests", "tests")])

    def test_the_plan_is_sent_back_once(self):
        bad = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[self.wrap("a"), self.wrap("b")])])
        rc, s = self.run_engine({"plan": [bad, PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["planner", "planner", "worker", "reviewer"])
        self.assertIn("slow commands run in more than one check", s.prompts[1])
        self.assertIn("just unity-tests", s.prompts[1])


class SharedNotes(StagesTest):
    """13.8: the tasks of a repo share what is running, what landed and which tests are flaky."""

    def eng_(self):
        return engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))

    def test_flakes_are_kept_per_repo_once_and_listed_for_the_next_prompts(self):
        e = self.eng_()
        self.assertEqual(e.known_flakes(), [])
        e.add_flakes([{"test": "SoakTests.HeapGrowth", "note": "process-wide heap check"}, {"test": " ", "note": "x"}])
        e.add_flakes([{"test": "SoakTests.HeapGrowth", "note": "again"}])
        self.assertEqual([f["test"] for f in e.known_flakes()], ["SoakTests.HeapGrowth"])
        self.assertIn("SoakTests.HeapGrowth", e.flakes_text())
        self.assertIn("do not build a new isolation", e.flakes_text())
        self.assertIn("SoakTests.HeapGrowth", self.eng_().shared_text())  # another task of the repo reads the same file
        e.add_flakes(["not a dict", {"test": "A"}, {"test": "B"}, {"test": "C"}, {"test": "D"}])
        self.assertEqual([f["test"] for f in e.known_flakes()][1:], ["A", "B", "C"])  # three a write
        data = json.loads(e.shared_path().read_text())
        data["flakes"][0]["t"] = 1  # a writer's word lapses
        e.shared_path().write_text(json.dumps(data))
        self.assertNotIn("SoakTests.HeapGrowth", [f["test"] for f in e.known_flakes()])

    def test_a_writer_that_reports_a_flake_tells_the_next_prompts(self):
        flake = dict(WRITE, flakes=[{"test": "SoakTests.HeapGrowth", "note": "failed on the untouched base"}])
        rc, s = self.run_engine({"plan": [PLAN], "write": [flake], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertNotIn("Known flaky", s.prompts[1])
        self.assertEqual([f["test"] for f in self.eng.known_flakes()], ["SoakTests.HeapGrowth"])
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertIn("SoakTests.HeapGrowth", s.prompts[0])  # the planner
        self.assertIn("SoakTests.HeapGrowth", s.prompts[1])  # the writer's first prompt
        self.assertIn("SoakTests.HeapGrowth", s.prompts[2])  # the reviewer

    def test_what_landed_since_the_branch_left_the_base_is_listed(self):
        te.sh("git", "checkout", "-qb", "task/t-1", cwd=self.wt)
        self.commit_base_cfg({"gate": ""})
        te.sh("git", "fetch", "-q", "origin", cwd=self.wt)
        self.assertEqual(self.eng_().landed_since(), ["engine config"])

    def test_a_task_running_in_another_worktree_is_listed_with_its_files(self):
        other = Path(self.tmp.name, "wt2")
        te.sh("git", "worktree", "add", "-q", "--detach", str(other), cwd=self.wt)
        tl.write_engine_lock(str(other), {"pid": engine.os.getpid(), "start": tl.proc_start(engine.os.getpid()), "bead": "t-2"})
        tl.config_dir().joinpath("checkpoints").mkdir(exist_ok=True)
        tl.config_dir().joinpath("checkpoints", "t-2.json").write_text(json.dumps({"plan": {"summary": "tune the soak", "stages": [
            {"goal": "g", "files": ["SoakTests.cs", "justfile"], "checks": [], "hard": False}]}}))
        got = self.eng_().siblings()
        self.assertEqual(got, [("t-2", "tune the soak", ["SoakTests.cs", "justfile"])])
        self.assertIn("t-2: tune the soak [files: SoakTests.cs, justfile]", self.eng_().shared_text())
        tl.write_engine_lock(str(other), {"pid": 99999999, "start": "", "bead": "t-2"})  # dead
        self.assertEqual(self.eng_().siblings(), [])

    def test_a_branch_behind_the_base_is_rebased_before_it_is_planned(self):
        te.sh("git", "checkout", "-qb", "task/t-1", cwd=self.wt)
        (self.wt / "g.txt").write_text("g\n")
        te.sh("git", "add", "-A", cwd=self.wt)
        te.sh("git", "commit", "-qm", "earlier work", cwd=self.wt)
        te.sh("git", "checkout", "-q", "-", cwd=self.wt)
        self.commit_base_cfg({"gate": ""})  # main moves on
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertIn("rebased the task branch onto the latest origin/main", self.eng.log_path.read_text())
        out = engine.subprocess.run(["git", "log", "--format=%s", "origin/main"], cwd=self.wt, capture_output=True, text=True).stdout
        self.assertIn("engine config", out)
        self.assertIn("Add f (t-1)", out)

    def test_the_rebase_moves_the_checkpoints_head_with_it(self):
        te.sh("git", "checkout", "-qb", "task/t-1", cwd=self.wt)
        (self.wt / "g.txt").write_text("g\n")
        te.sh("git", "add", "-A", cwd=self.wt)
        te.sh("git", "commit", "-qm", "earlier work", cwd=self.wt)
        e = self.eng_()
        old = e.git("rev-parse", "HEAD")
        e.checkpoint_path().parent.mkdir(exist_ok=True)
        e.checkpoint_path().write_text(json.dumps({"v": 1, "head": old}))
        self.commit_base_cfg({"gate": ""})
        te.sh("git", "fetch", "-q", "origin", cwd=self.wt)
        e.rebase_onto_base()
        new = e.git("rev-parse", "HEAD")
        self.assertNotEqual(old, new)
        self.assertEqual(json.loads(e.checkpoint_path().read_text())["head"], new)


class Fdyo(StagesTest):
    """13.11-13.14, from the lifesim-fdyo run (15.7M tokens): checks only the engine can pass, a late fresh writer, a check that
    cannot run, slow tests before a fast verdict."""

    PASS = te.PY + ' -c "pass"'

    def test_the_planner_is_told_not_to_invent_a_threshold_for_an_owner_judged_criterion(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertIn("only the owner can judge", s.prompts[0])

    def test_a_check_red_two_rounds_running_tells_the_writer_it_may_flag_it(self):
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[FALSE])])
        rc, s = self.run_engine({"plan": [plan], "write": [WRITE, WRITE, WRITE], "review": [CLEAN]}, max_check_tries=3)
        writes = [p for p, c in zip(s.prompts, s.calls) if c[0] == "worker"]
        self.assertNotIn("failed in the last round too", writes[1])  # red for the first time
        self.assertIn("failed in the last round too", writes[2])
        self.assertIn("list it in bad_checks", writes[2])

    def test_a_codex_session_is_not_resumed_above_100k_inside_a_stage(self):
        self.assertEqual(engine.DEFAULTS["write_fresh_above_k"], {"claude": 150, "codex": 100})

    def test_python_isolated_mode_with_a_repo_module_is_sent_back(self):
        (self.wt / "tools" / "tests").mkdir(parents=True)
        (self.wt / "tools" / "tests" / "test_x.py").write_text("x = 1\n")
        te.sh("git", "add", "-A", cwd=self.wt)
        te.sh("git", "commit", "-qm", "tools", cwd=self.wt)
        te.sh("git", "push", "-q", "origin", "HEAD:main", cwd=self.wt)
        bad = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=["python3 -I -m unittest tools.tests.test_x"])])
        self.assertEqual(len(engine.dry_check(bad, str(self.wt))), 1)
        self.assertIn("python -I removes the working directory", engine.dry_check(bad, str(self.wt))[0])
        for ok in ("python3 -I -m unittest discover -s tools/tests -p 'test_x.py'", "python3 -m unittest tools.tests.test_x",
                   "python3 -I -m json.tool f.json", "python3 -I -c 'import tools.x'"):
            self.assertEqual(engine.dry_check(dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[ok])]), str(self.wt)), [], ok)
        rc, s = self.run_engine({"plan": [bad, PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual([c[0] for c in s.calls], ["planner", "planner", "worker", "reviewer"])
        self.assertIn("python -I removes the working directory", s.prompts[1])

    def test_after_a_round_red_only_in_acceptance_the_fast_group_runs_before_the_slow_tests(self):
        eng = self.checks_engine(checks=[{"id": "slow", "cmd": self.PASS, "group": "tests"}])
        st = {"checks": [FALSE], "files": []}
        first = eng.run_checks(st, "s")
        self.assertEqual([(c["group"], c["status"]) for c in first], [("tests", "ran"), ("acceptance", "failed")])
        again = eng.run_checks(st, "s", acceptance_first=True)
        self.assertEqual([(c["group"], c["status"]) for c in again], [("acceptance", "failed"), ("tests", "skipped")])
        self.assertIn("acceptance failed first", again[1]["why"])

    def test_the_reorder_is_off_when_an_acceptance_check_reads_a_repo_checks_log(self):
        eng = self.checks_engine(checks=[{"id": "slow", "cmd": self.PASS, "group": "tests"}])
        st = {"checks": ['grep -q . "$TL_CHECK_LOG_SLOW" || true'], "files": []}
        res = eng.run_checks(st, "s", acceptance_first=True)
        self.assertEqual([c["group"] for c in res], ["tests", "acceptance"])

    def test_a_stage_whose_acceptance_check_was_red_runs_acceptance_first_the_next_round(self):
        flaky = te.EngineTest.RED_ONCE
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[flaky])])
        rc, s = self.run_engine({"plan": [plan], "write": [WRITE, WRITE], "review": [CLEAN]},
                                checks=[{"id": "slow", "cmd": self.PASS, "group": "tests"}])
        self.assertEqual(rc, 0, self.blocked)
        rounds = [json.loads(l) for l in self.eng.log_path.read_text().splitlines() if '"kind": "checks"' in l]
        self.assertEqual([[i["group"] for i in r["items"]] for r in rounds], [["tests", "acceptance"], ["acceptance", "tests"]])

    def test_acceptance_first_is_used_once_then_the_normal_order_returns(self):
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[FALSE])])
        rc, s = self.run_engine({"plan": [plan], "write": [WRITE] * 4, "review": [CLEAN]}, max_check_tries=4,
                                checks=[{"id": "slow", "cmd": self.PASS, "group": "tests"}])
        rounds = [json.loads(l) for l in self.eng.log_path.read_text().splitlines() if '"kind": "checks"' in l]
        self.assertEqual([r["items"][0]["group"] for r in rounds], ["tests", "acceptance", "tests", "acceptance"])

    def test_a_repo_check_red_twice_is_not_offered_to_bad_checks(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE] * 3, "review": [CLEAN]}, max_check_tries=3,
                                checks=[{"id": "repo-red", "cmd": FALSE, "group": "tests"}])
        writes = [p for p, c in zip(s.prompts, s.calls) if c[0] == "worker"]
        self.assertTrue(len(writes) >= 3)
        self.assertNotIn("failed in the last round too", writes[2])


class VisualWork(StagesTest):
    """tl-bxk.13.15: the engine renders the writer's shots, a look judge judges, the owner decides taste."""

    SHOT = ("import sys, pathlib\n"
            "out = pathlib.Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)\n"
            "name = sys.argv[2] if len(sys.argv) > 2 else 'screen'\n"
            "(out / (name + '.png')).write_bytes(b'\\x89PNG fake ' + name.encode())\n")
    TABLE = {"v": 1, "methods": [{"method": "ScreenShots", "summary": "the main screen", "timeout_min": 1,
                                  "cmd": te.PY + " tools/shot.py {out}{args}", "args": [{"name": "name", "flag": "", "pattern": "[a-z-]+"}]}]}
    VIS = {"include": ["f.txt"]}

    def setUp(self):
        super().setUp()
        base = Path(self.tmp.name, "base-files")
        te.sh("git", "clone", "-q", str(Path(self.tmp.name, "o.git")), str(base), cwd=self.tmp.name)
        (base / "tools").mkdir()
        (base / "tools" / "shot.py").write_text(self.SHOT)
        (base / "shots.json").write_text(json.dumps(self.TABLE))
        te.sh("git", "add", "-A", cwd=base)
        te.sh("git", "commit", "-qm", "shot table", cwd=base)
        te.sh("git", "push", "-q", "origin", "HEAD:main", cwd=base)
        te.sh("git", "pull", "-q", "origin", "main", cwd=self.wt)

    def go(self, answers, table="shots.json", **cfg):
        raw = {"visual_paths": self.VIS, "shot_table": table, "evidence_dir": "design/look-reviews"}
        return self.run_engine(answers, raw=raw, **cfg)

    SHOTS = [{"method": "ScreenShots", "args": [{"name": "name", "value": "main"}], "names": ["main screen"]}]

    @staticmethod
    def judged(*defects, summary="the main screen shows"):
        return {"findings": [{"item": "general", "verdict": "defect", "where": w, "why": y} for w, y in defects] or
                [{"item": "general", "verdict": "pass", "where": "", "why": "fine"}], "summary": summary}

    def write(self, **kw):
        return dict(WRITE, **dict({"shots": self.SHOTS}, **kw))

    def roles(self, s):
        return [c[0] for c in s.calls]

    def test_the_writer_is_asked_for_shot_requests_not_screenshots(self):
        rc, s = self.go({"plan": [PLAN], "write": [self.write()], "look": [self.judged()], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        first = s.prompts[1]
        self.assertIn("You cannot render it here: the engine does", first)
        self.assertIn("ScreenShots: the main screen", first)
        self.assertNotIn("Save a screenshot of every changed", first)

    def test_the_engine_renders_and_a_judge_with_only_the_pictures_reads_them(self):
        rc, s = self.go({"plan": [PLAN], "write": [self.write()], "look": [self.judged()], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(self.roles(s), ["planner", "worker", "reviewer", "reviewer"])  # the judge, then the review
        judge = s.prompts[2]
        self.assertIn("You judge how a screen looks from pictures", judge)
        self.assertIn("main.png", judge)
        cwd = Path(s.cwds[2])
        self.assertEqual(cwd.name, "r1")
        self.assertEqual(sorted(p.name for p in cwd.iterdir() if p.is_file()), ["main.png"])  # no repo, only the pictures
        self.assertTrue((self.eng.evidence_dir / "main.png").is_file())  # the full-size copy for the land and the review
        self.assertIn("a look judge", s.prompts[3])  # the reviewer is told, and does not open the pictures by default

    def test_the_judge_is_from_the_other_family_like_the_review(self):
        rc, s = self.go({"plan": [PLAN], "write": [self.write()], "look": [self.judged()], "review": [CLEAN]})
        self.assertIsNotNone(s.calls[2][2])  # authored-by: the writer's family

    def test_a_defect_goes_back_to_the_writer_as_text_then_a_second_render_passes(self):
        defect = self.judged(("main.png, top right", "The Save button is clipped at the right edge"))
        rc, s = self.go({"plan": [PLAN], "write": [self.write(), self.write()], "look": [defect, self.judged()], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(self.roles(s), ["planner", "worker", "reviewer", "worker", "reviewer", "reviewer"])
        again = s.prompts[3]
        self.assertIn("Save button is clipped at the right edge", again)
        self.assertIn("main.png", again)
        self.assertEqual([x for x in self.created() if x.startswith("Look:")], [])

    def test_the_same_defect_twice_is_a_leftover_not_a_third_write(self):
        defect = self.judged(("main.png", "The Save button is clipped at the right edge"))
        same = self.judged(("main.png", "Save button clipped at right edge of the card"))
        rc, s = self.go({"plan": [PLAN], "write": [self.write(), self.write()], "look": [defect, same], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(self.roles(s).count("worker"), 2)
        self.assertEqual(len([t for t in self.created() if t.startswith("Look:")]), 1)

    def test_a_new_defect_in_the_last_render_round_is_a_leftover_too(self):
        one = self.judged(("main.png", "The Save button is clipped"))
        two = self.judged(("main.png", "A magenta texture on the sofa"))
        rc, s = self.go({"plan": [PLAN], "write": [self.write(), self.write()], "look": [one, two], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(self.roles(s).count("worker"), 2)  # two render rounds, no third
        self.assertEqual([t for t in self.created() if t.startswith("Look:")], ["Look: A magenta texture on the sofa"])

    def test_a_method_the_table_does_not_have_is_a_defect_with_no_judge_call(self):
        bad = dict(WRITE, shots=[{"method": "Nope", "args": [], "names": []}])
        rc, s = self.go({"plan": [PLAN], "write": [bad, self.write()], "look": [self.judged()], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(self.roles(s), ["planner", "worker", "worker", "reviewer", "reviewer"])
        self.assertIn("no shot method 'Nope'", s.prompts[2])

    def test_a_visual_write_with_no_shots_and_no_reason_is_a_finding(self):
        rc, s = self.go({"plan": [PLAN], "write": [WRITE, WRITE], "review": [CLEAN, CLEAN]})
        self.assertIn("asked for no shots", self.eng.run_dir.joinpath("handoff.json").read_text())

    def test_without_a_shot_table_a_visual_stage_works_the_old_way(self):
        rc, s = self.go({"plan": [PLAN], "write": [WRITE, WRITE], "review": [CLEAN, CLEAN]}, table="")
        self.assertIn("Save a screenshot of every changed", s.prompts[1])
        self.assertNotIn("You cannot render it here", s.prompts[1])
        self.assertNotIn("look", [k for k in self.eng.run_dir.glob("look-*.json")])

    def test_the_table_is_read_from_the_base_branch_not_the_working_copy(self):
        (self.wt / "shots.json").write_text(json.dumps({"v": 1, "methods": [{"method": "Evil", "cmd": "touch pwned"}]}))
        e = engine.Engine("t-1", str(self.wt), dict(engine.load_cfg(str(self.wt)), shot_table="shots.json"))
        self.assertEqual(list(e.shot_methods()), ["ScreenShots"])

    def test_a_missing_table_is_warned_once_and_the_old_way_stands(self):
        e = engine.Engine("t-1", str(self.wt), dict(engine.load_cfg(str(self.wt)), shot_table="nowhere.json"))
        self.assertEqual(e.shot_methods(), {})
        self.assertEqual(e.shot_methods(), {})

    def test_look_and_taste_cases_have_no_command_and_run_nothing(self):
        cases = [{"criterion": "the picker shows", "check": "", "class": "look-objective"},
                 {"criterion": "it reads well", "check": "", "class": "taste"}]
        rc, s = self.go({"plan": [dict(PLAN, cases=cases)], "write": [self.write()], "look": [self.judged()], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertIn("the picker shows", s.prompts[2])  # the judge judges the look-objective item
        self.assertNotIn("it reads well", s.prompts[2])
        self.assertEqual(self.eng.case_checks(), [])

    def test_the_planner_is_told_the_classes_and_asks_for_a_missing_reference(self):
        rc, s = self.go({"plan": [PLAN], "write": [self.write()], "look": [self.judged()], "review": [CLEAN]})
        plan_prompt = s.prompts[0]
        self.assertIn("look-objective:", plan_prompt)
        self.assertIn("Never invent one as a check", plan_prompt)
        self.assertIn("ask that as your question", plan_prompt)  # no reference image in the task

    def test_a_visual_repo_without_a_shot_table_is_told_nothing_of_classes(self):
        rc, s = self.go({"plan": [PLAN], "write": [WRITE, WRITE], "review": [CLEAN, CLEAN]}, table="")
        self.assertNotIn("look-objective:", s.prompts[0])

    TWO = dict(PLAN, stages=[PLAN["stages"][0], dict(PLAN["stages"][0], goal="add g")],
               cases=[{"criterion": "the picker shows a hue gradient", "check": "", "class": "look-objective"}])

    def test_the_plans_look_items_are_judged_on_the_last_stage_only(self):
        rc, s = self.go({"plan": [self.TWO], "write": [self.write(), self.write()], "look": [self.judged(), self.judged()],
                         "review": [CLEAN, CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        judges = [p for p in s.prompts if p.startswith("You judge how a screen looks")]
        self.assertEqual(len(judges), 2)
        self.assertNotIn("hue gradient", judges[0])
        self.assertIn("hue gradient", judges[1])

    def test_only_the_engines_own_pictures_count_with_a_shot_table(self):
        e = engine.Engine("t-1", str(self.wt), dict(engine.load_cfg(str(self.wt)), shot_table="shots.json"))
        e.evidence_dir.mkdir(parents=True, exist_ok=True)
        (e.evidence_dir / "writer.png").write_bytes(b"x")
        (e.evidence_dir / "main.png").write_bytes(b"x")
        e.rendered_names = {"main.png"}
        self.assertEqual(e.shots(), ["main.png"])

    def test_a_failed_shot_command_is_a_defect_even_if_it_left_a_picture(self):
        self.TABLE["methods"][0]["cmd"] = te.PY + " tools/shot.py {out}{args}; exit 3"
        try:
            base = Path(self.tmp.name, "base-files")
            (base / "shots.json").write_text(json.dumps(self.TABLE))
            te.sh("git", "commit", "-qam", "failing shot", cwd=base)
            te.sh("git", "push", "-q", "origin", "HEAD:main", cwd=base)
            te.sh("git", "pull", "-q", "origin", "main", cwd=self.wt)
            rc, s = self.go({"plan": [PLAN], "write": [self.write(), self.write()], "review": [CLEAN]})
        finally:
            self.TABLE["methods"][0]["cmd"] = te.PY + " tools/shot.py {out}{args}"
        self.assertEqual(self.roles(s)[:3], ["planner", "worker", "worker"])  # no judge call: the render failed
        self.assertIn("failed (exit 3)", s.prompts[2])

    def test_pictures_made_before_a_later_fix_are_rendered_again_before_the_land(self):
        red_once = te.PY + ' -c "import sys; sys.exit(0 if open(\'f.txt\').read().strip() != \'d2\' else 1)"'  # red after the first write
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[red_once])])
        rc, s = self.go({"plan": [plan], "write": [self.write(), self.write(shots=[])], "look": [self.judged()], "review": [CLEAN]},
                        look_rounds=1)
        self.assertEqual(rc, 0, self.blocked)
        self.assertIn("rendering the last shots again", self.eng.log_path.read_text())
        self.assertEqual(self.eng.render_stale, False)

    def test_a_resumed_stage_keeps_its_render_rounds(self):
        e = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        e.look_done, e.look_prev, e.rendered_names, e.last_reqs, e.render_stale = 1, [{"why": "x", "where": ""}], {"a.png"}, self.SHOTS, True
        e.plan_data = dict(PLAN)
        e.branch = "task/t-1"
        e.git("checkout", "-q", "-b", "task/t-1")
        e.save_checkpoint(stage=0, rounds=0, n=1, feedback="", step="write")
        ck = json.loads(e.checkpoint_path().read_text())
        self.assertEqual((ck["look_done"], ck["rendered"], ck["render_stale"]), (1, ["a.png"], True))
        again = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        again.reset(dict(BEAD))
        again.resume_point()
        self.assertEqual((again.look_done, again.rendered_names, again.render_stale), (1, {"a.png"}, True))

    def test_a_non_visual_repo_gets_none_of_it(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertNotIn("look-objective:", s.prompts[0])

    def test_the_gallery_data_lands_in_the_owner_look_beads_metadata(self):
        e = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        e.plan_data = dict(PLAN, cases=[{"criterion": "it reads well", "check": "", "class": "taste"}])
        e.look_paths = ["design/look-reviews/t-1/main.png"]
        e.look_notes = ["the main screen shows"]
        sent = []
        old = {"metadata": {"looks": [
            {"id": "t-0#1", "bead": "t-0", "title": "other", "shots": [], "status": "open"},
            {"id": "t-1#1", "bead": "t-1", "title": "it reads well", "shots": [], "status": "good"}], "keep": "me"}}
        with mock.patch.object(tl, "show", return_value=old), \
                mock.patch.object(tl, "bd", side_effect=lambda *a, **k: sent.append(a) or mock.Mock(returncode=0, stdout="", stderr="")):
            e.write_looks("lk-1")
        (call,) = sent
        self.assertEqual(call[:3], ("update", "lk-1", "--metadata"))
        meta = json.loads(call[3])
        self.assertEqual(meta["keep"], "me")
        self.assertEqual([x["id"] for x in meta["looks"]], ["t-0#1", "t-1#1"])
        self.assertEqual(meta["looks"][1]["status"], "good")  # the owner's answer stays
        e.leftovers = []
        old["metadata"]["looks"].pop()
        sent.clear()
        with mock.patch.object(tl, "show", return_value=old), \
                mock.patch.object(tl, "bd", side_effect=lambda *a, **k: sent.append(a) or mock.Mock(returncode=0, stdout="", stderr="")):
            e.write_looks("lk-1")
        entry = json.loads(sent[0][3])["looks"][-1]
        self.assertEqual((entry["id"], entry["bead"], entry["title"], entry["status"]), ("t-1#1", "t-1", "it reads well", "open"))
        self.assertEqual(entry["note"], "the main screen shows")
        self.assertEqual(entry["shots"], [{"path": "design/look-reviews/t-1/main.png", "role": "after", "label": "main"}])


class Contracts(StagesTest):
    """tl-bxk.13.16: infrastructure is retried with a rest, never asked; the version is recorded."""

    FLAKY = ("import os, subprocess, sys\nm = %r\nn = int(open(m).read()) if os.path.exists(m) else 0\n"
             "open(m, 'w').write(str(n + 1))\n"
             "if n < %d:\n    sys.stderr.write('error: RPC failed; curl 56 Send failure: Broken pipe\\nfatal: the remote end hung up unexpectedly\\n'); sys.exit(1)\n"
             "sys.exit(subprocess.call(['git', 'push', 'origin', 'HEAD:main']))\n")

    def land_with(self, fails):
        script = Path(self.tmp.name, "flaky_push.py")
        script.write_text(self.FLAKY % (str(Path(self.tmp.name, "flaky-count")), fails))
        return te.PY + " " + str(script).replace("\\", "/")

    def test_a_network_failure_on_the_push_is_retried_with_a_rest_and_lands(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, land=self.land_with(2))
        self.assertEqual(rc, 0, self.blocked)
        text = self.eng.log_path.read_text()
        self.assertEqual(text.count("the push failed with a network error"), 2)
        self.assertIsNone(self.eng.__dict__.get("asked") or None)
        self.assertTrue(self.closed and self.closed[0].startswith("merged"))

    def test_a_push_that_keeps_failing_pauses_the_bead_and_asks_nobody(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, land=self.land_with(99))
        self.assertNotEqual(rc, 0)
        self.assertTrue(self.eng.why.startswith("paused: the land push failed 4 times"), self.eng.why)
        self.assertFalse(self.eng.asked)

    def test_a_rejected_or_other_push_failure_is_not_retried_as_the_network(self):
        self.assertFalse(engine.TRANSIENT_PUSH.search("! [rejected] HEAD -> main (non-fast-forward)"))
        self.assertFalse(engine.TRANSIENT_PUSH.search("remote: error: GH006: Protected branch update failed"))
        self.assertTrue(engine.TRANSIENT_PUSH.search("fatal: unable to access 'https://x/': Could not resolve host: x"))

    def test_a_delegate_crash_is_retried_fresh_and_the_run_goes_on(self):
        crash = te.ans("failed", "crash", "owner", say="UnicodeDecodeError: 'utf-8' codec can't decode bytes in position 65534-65535")
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [crash, CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer", "reviewer"])
        self.assertIn("delegate crashed", self.eng.log_path.read_text())

    def test_a_delegate_that_keeps_crashing_pauses_the_bead_and_asks_nobody(self):
        crash = te.ans("failed", "crash", "owner", say="UnicodeDecodeError")
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [crash, crash, crash]})
        self.assertNotEqual(rc, 0)
        self.assertTrue(self.eng.why.startswith("paused: delegate crashed 3 times on the review step"), self.eng.why)
        self.assertFalse(self.eng.asked)

    def test_a_run_again_answer_keeps_the_plan_and_is_no_amend(self):
        ask = dict(WRITE, question="Which format?")
        rc, _ = self.run_engine({"plan": [PLAN], "write": [ask]})
        self.assertEqual(rc, 2)
        with mock.patch.object(tl, "comments", return_value=[{"author": "denis", "text": "Run again."}]):
            rc, s = self.run_engine({"write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertNotIn("planner", [c[0] for c in s.calls])
        self.assertIn("only asks for a rerun", self.eng.log_path.read_text())
        for text in ("run-again", "Retry!", "go on", "re-run"):
            self.assertTrue(engine.RERUN_ANSWER.fullmatch(" ".join(text.lower().replace("-", " ").split()).strip(" .!")), text)
        for text in ("yes", "use option A", "run again with more budget"):
            self.assertFalse(engine.RERUN_ANSWER.fullmatch(text), text)

    def test_a_real_answer_still_amends(self):
        ask = dict(WRITE, question="Which format?")
        self.run_engine({"plan": [PLAN], "write": [ask]})
        with mock.patch.object(tl, "comments", return_value=[{"author": "denis", "text": "Use the new format, then run again."}]):
            rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(s.calls[0][0], "planner")

    def test_asks_of_closed_or_missing_beads_are_closed_and_others_left(self):
        asks = tl.config_dir() / "asks"
        asks.mkdir(exist_ok=True)
        for bead in ("b-open", "b-closed", "b-gone", "b-flaky"):
            (asks / ("%s.json" % bead)).write_text(json.dumps({"v": 1, "id": bead + "-1", "bead": bead, "status": "open", "kind": "stuck"}))
        (asks / "b-answered.json").write_text(json.dumps({"v": 1, "id": "x", "bead": "b-answered", "status": "answered"}))

        def fake_bd(*a, **k):
            bead = a[1]
            if bead == "b-gone":
                return mock.Mock(returncode=1, stdout="", stderr="Error: no issue found matching b-gone")
            if bead == "b-flaky":
                return mock.Mock(returncode=1, stdout="", stderr="dolt: connection lost")
            return mock.Mock(returncode=0, stdout=json.dumps([{"id": bead, "status": "closed" if bead == "b-closed" else "open"}]), stderr="")
        with mock.patch.object(tl, "bd", side_effect=fake_bd):
            closed = tl.close_stale_asks(every=0)
            self.assertEqual(sorted(closed), ["b-closed", "b-gone"])
            self.assertEqual(tl.close_stale_asks(), [])  # throttled
        state = {b: json.loads((asks / ("%s.json" % b)).read_text())["status"] for b in ("b-open", "b-closed", "b-gone", "b-flaky", "b-answered")}
        self.assertEqual(state, {"b-open": "open", "b-closed": "closed", "b-gone": "closed", "b-flaky": "open", "b-answered": "answered"})

    def test_the_engine_log_and_trace_record_the_version(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        want = json.loads((Path(engine.__file__).resolve().parents[2] / ".claude-plugin" / "plugin.json").read_text())["version"]
        self.assertEqual(engine.plugin_version(), want)
        self.assertIn("task-loop %s" % want, self.eng.log_path.read_text())
        last = json.loads((tl.config_dir() / "traces.jsonl").read_text().splitlines()[-1])
        self.assertEqual(last["version"], want)


if __name__ == "__main__":
    unittest.main()
