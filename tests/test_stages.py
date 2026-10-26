"""tl-bxk.13: stage handoffs (docs/design/stages.md). Reuses test_engine's harness without re-running its tests."""
import json
import shutil
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "task-loop"))
import fake_route  # noqa: E402
import test_engine as te  # noqa: E402
from test_engine import BEAD, CLEAN, FALSE, HAS_F, PLAN, WRITE, engine, lint, tl  # noqa: E402,F401


_REAL_CMD_BLOCK = tl.cmd_block  # te's harness patches it per test; this is the real one


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
        rc, s = self.run_engine({"plan": [dict(PLAN, stages=[]), dict(PLAN, stages=[])]})  # sent back once (tl-wjj), still empty
        self.assertNotEqual(rc, 0)
        self.assertEqual(self.blocked, [])
        self.assertIn("no stages", te.EngineTest.said(self))

    def test_an_empty_plan_over_work_no_review_accepted_is_not_done(self):
        te.sh("git", "checkout", "-qb", "task/t-1", cwd=self.wt)
        (self.wt / "g.txt").write_text("half done\n")
        te.sh("git", "add", "-A", cwd=self.wt)
        te.sh("git", "commit", "-qm", "wip", cwd=self.wt)
        te.sh("git", "checkout", "-q", "-", cwd=self.wt)
        plan = dict(PLAN, stages=[], leftovers=[{"title": "File the table bead", "why": "x"}])
        rc, s = self.run_engine({"plan": [plan]})
        self.assertNotEqual(rc, 0)
        self.assertEqual(self.blocked, [])
        self.assertIn("no stages", te.EngineTest.said(self))
        self.assertEqual(self.created(), [])

    @te.no_repo
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

    @te.no_repo
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

    @te.no_repo
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

    def test_a_check_red_two_rounds_running_tells_the_writer_it_may_flag_it(self):
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[FALSE])])
        rc, s = self.run_engine({"plan": [plan], "write": [WRITE, WRITE, WRITE], "review": [CLEAN]}, max_check_tries=3)
        writes = [p for p, c in zip(s.prompts, s.calls) if c[0] == "worker"]
        self.assertNotIn("failed in the last round too", writes[1])  # red for the first time
        self.assertIn("failed in the last round too", writes[2])
        self.assertIn("list it in bad_checks", writes[2])

    @te.no_repo
    def test_a_codex_session_is_not_resumed_above_100k_inside_a_stage(self):
        self.assertEqual(engine.DEFAULTS["write_fresh_above_k"], {"claude": 150, "codex": 100, "xai": 100})

    def test_python_isolated_mode_with_a_repo_module_is_sent_back(self):
        (self.wt / "tools" / "tests").mkdir(parents=True)
        (self.wt / "tools" / "tests" / "test_x.py").write_text("x = 1\n")
        te.sh("git", "add", "-A", cwd=self.wt)
        te.sh("git", "commit", "-qm", "tools", cwd=self.wt)
        te.sh("git", "push", "-q", "origin", "HEAD:main", cwd=self.wt)
        bad = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=["python3 -I -m unittest tools.tests.test_x"])])
        self.assertEqual(len(lint.dry_check(bad, str(self.wt))), 1)
        self.assertIn("python -I removes the working directory", lint.dry_check(bad, str(self.wt))[0])
        for ok in ("python3 -I -m unittest discover -s tools/tests -p 'test_x.py'", "python3 -m unittest tools.tests.test_x",
                   "python3 -I -m json.tool f.json", "python3 -I -c 'import tools.x'"):
            self.assertEqual(lint.dry_check(dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[ok])]), str(self.wt)), [], ok)
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

    def test_a_look_judge_with_no_lane_leaves_the_pictures_unjudged_and_the_bead_unparked(self):
        late = te.stop("no_lane", at=engine.time.time() + 3600, family="xai", lane="GROK", say="no lane")
        rc, s = self.go({"plan": [PLAN], "write": [self.write()], "look": [late], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertIn("the look judge had no lane", self.eng.log_path.read_text())
        self.assertIn("look judge, round 1", self.eng.look_unjudged)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer", "reviewer"])  # the judge's one try, then the review

    def test_a_login_or_a_crash_is_not_swallowed_by_the_look_judge(self):
        out = te.stop("logged_out", family="claude", lane="CLAUDE", say="logged out")
        rc, s = self.go({"plan": [PLAN], "write": [self.write()], "look": [out, out]})
        self.assertIn("paused", self.eng.why)

    def test_the_judge_from_the_same_family_says_so(self):
        rc, s = self.go({"plan": [PLAN], "write": [self.write()], "look": [self.judged()], "review": [CLEAN]},
                        j_extra={"look": [{"flag": "same_family"}]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertIn("same family as the writer", " ".join(self.eng.look_notes))

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

    def test_a_visual_write_with_no_shots_and_no_reason_is_asked_once_more_at_no_cost_to_the_rounds(self):
        rc, s = self.go({"plan": [PLAN], "write": [WRITE, self.write()], "look": [self.judged()], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(self.roles(s), ["planner", "worker", "worker", "reviewer", "reviewer"])  # the second write, then the judge, then the review
        self.assertIn("named no shots and gave no logic_only reason", s.prompts[2])
        self.assertIn("ScreenShots: the main screen", s.prompts[2])  # the table is in the question
        self.assertEqual(self.eng.stats["rounds"], 0)  # not a send-back round
        self.assertIn("shots_contract", self.eng.log_path.read_text())
        self.assertTrue((self.eng.evidence_dir / "main.png").is_file())  # the second answer's shots were rendered

    def test_a_logic_only_reason_or_shots_need_no_second_ask(self):
        rc, s = self.go({"plan": [PLAN], "write": [dict(WRITE, logic_only="a rename: nothing on screen differs")], "review": [CLEAN]})
        self.assertEqual(self.roles(s), ["planner", "worker", "reviewer"])
        rc, s = self.go({"plan": [PLAN], "write": [self.write()], "look": [self.judged()], "review": [CLEAN]})
        self.assertEqual(self.roles(s).count("worker"), 1)

    def test_a_writer_that_still_names_nothing_meets_the_reviews_finding_as_before(self):
        rc, s = self.go({"plan": [PLAN], "write": [WRITE, WRITE, WRITE, WRITE], "review": [CLEAN, CLEAN]})
        handoff = self.eng.run_dir.joinpath("handoff.json").read_text()
        self.assertIn("asked for no shots", handoff)
        self.assertEqual(sum(1 for t in s.prompts if "named no shots and gave no logic_only reason" in t), 1)  # asked once, not again

    def test_the_planner_is_told_the_rule_and_the_repos_shot_methods(self):
        base = Path(self.tmp.name, "base-files")
        (base / "lifesim.json").write_text((Path(__file__).resolve().parent / "fixtures" / "lifesim_shot_table.json").read_text())
        te.sh("git", "add", "-A", cwd=base)
        te.sh("git", "commit", "-qm", "lifesim table", cwd=base)
        te.sh("git", "push", "-q", "origin", "HEAD:main", cwd=base)
        te.sh("git", "pull", "-q", "origin", "main", cwd=self.wt)
        rc, s = self.go({"plan": [PLAN], "write": [self.write()], "review": [CLEAN]}, table="lifesim.json")
        planner = s.prompts[0]
        self.assertIn("changes how something looks", planner)
        self.assertIn("logic_only", planner)
        self.assertIn("(f.txt)", planner)  # the visual paths
        self.assertIn("- BuildShots: Build mode: flat, drag, undo", planner)
        self.assertIn("- PoseShots: Every declared body slot", planner)
        self.assertNotIn("Diagnostic records", planner)  # a line per method, not the whole summary

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

    def test_the_planner_is_told_the_classes_and_to_assume_a_missing_reference(self):
        rc, s = self.go({"plan": [PLAN], "write": [self.write()], "look": [self.judged()], "review": [CLEAN]})
        plan_prompt = s.prompts[0]
        self.assertIn("look-objective:", plan_prompt)
        self.assertIn("Never invent one as a check", plan_prompt)
        self.assertIn("assume the look", plan_prompt)  # no reference image in the task

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

    @te.POSIX_CHECK
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
        rc, s = self.go({"plan": [plan], "write": [self.write(), self.write(shots=[], logic_only="nothing on screen changed")], "look": [self.judged()], "review": [CLEAN]},
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


class Executable(StagesTest):
    """tl-bxk.13.16.2: a plan check must be able to start; an accepted stage's promised files must exist on resume."""

    @te.NO_BASH
    def test_a_sentence_is_not_a_command(self):
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=["After building the current player: python3 tools/x.py", HAS_F])])
        errs = lint.dry_check(plan, str(self.wt))
        self.assertEqual(len(errs), 1)
        self.assertIn("`After` is not a command here", errs[0])

    def test_real_commands_pass_the_word_check(self):
        for ok in ("grep -q x a.txt && test -f a.txt", "! grep -q zzz a.txt", "FOO=1 bash -c 'echo hi' | wc -l",
                   "echo hi > out.txt 2>&1 && test -s out.txt", "for f in a b; do echo $f; done", "(cd . && ls)",
                   "git status --short", "python3 -c 'a;b'", te.PY + " -c 'pass'"):
            self.assertEqual(lint.command_problems(ok, str(self.wt)), [], ok)

    @unittest.skipUnless(shutil.which("just"), "needs the real `just` (the engine asks it for the recipes)")
    @te.NO_BASH
    def test_a_just_recipe_must_exist_in_the_tree(self):
        (self.wt / "justfile").write_text("fmt-check:\n\techo ok\n")
        lint._RECIPES.clear()
        self.assertEqual(lint.command_problems("just fmt-check && echo done", str(self.wt)), [])
        bad = lint.command_problems("just fmt-check && just unity-play-tests", str(self.wt))
        self.assertEqual(len(bad), 1)
        self.assertIn("no recipe unity-play-tests", bad[0])
        self.assertIn("fmt-check", bad[0])
        lint._RECIPES.clear()

    def test_valid_checks_the_word_check_must_not_block(self):
        for tool in ("make", "npm"):  # tools a dev machine has; this test is about the grammar, not about what is installed
            lint._WORDS[(str(self.wt), tool)] = (True, time.time())
        for ok in ("command -v git >/dev/null", "env -i PATH=$PATH git --version", "f () { echo hi; }; f",
                   "cat <<EOF2 > x.txt\nhello\nEOF2\ntest -s x.txt", "cd sub && ./x.sh", "make && ./build/x", "npm ci && node_modules/.bin/jest",
                   "~/bin/foo", ".venv/bin/python -c pass", "source env.sh && git status", "time git status"):
            self.assertEqual(lint.command_problems(ok, str(self.wt)), [], ok)

    @unittest.skipUnless(shutil.which("just"), "needs the real `just` (the engine asks it for the recipes)")
    @te.NO_BASH
    def test_just_aliases_private_recipes_options_and_a_recipe_a_stage_adds(self):
        (self.wt / "justfile").write_text("alias ci := check\ncheck:\n\techo ok\n_private:\n\techo p\n")
        lint._RECIPES.clear()
        for ok in ("just ci", "just _private", "just --justfile justfile check", "just --set v x check", "just -d . check", "just check"):
            self.assertEqual(lint.command_problems(ok, str(self.wt)), [], ok)
        self.assertEqual(len(lint.command_problems("just nope", str(self.wt))), 1)
        self.assertEqual(lint.command_problems("just newrecipe", str(self.wt), made=["justfile"]), [])  # a stage adds it
        (self.wt / "justfile").write_text("newrecipe:\n\techo n\n")  # a rebase changes the file: seen at once
        self.assertEqual(lint.command_problems("just newrecipe", str(self.wt)), [])
        lint._RECIPES.clear()

    @te.NO_BASH
    def test_a_missing_script_is_found_unless_a_stage_makes_it(self):
        check = "./tools/probe.sh --all"
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[check])])
        self.assertIn("is not a file of this tree", lint.dry_check(plan, str(self.wt))[0])
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], files=["tools/probe.sh"], checks=[check])])
        self.assertEqual([e for e in lint.dry_check(plan, str(self.wt)) if "not a file" in e], [])

    @te.NO_BASH
    def test_the_plan_with_a_sentence_goes_back_once(self):
        bad = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=["Confirm that f exists", HAS_F])])
        rc, s = self.run_engine({"plan": [bad, PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual([c[0] for c in s.calls], ["planner", "planner", "worker", "reviewer"])
        self.assertIn("`Confirm` is not a command here", s.prompts[1])

    PATH1 = ".task/t-1/evidence/sleeper-on-bed.txt"

    def two_stage(self):
        return dict(PLAN, stages=[
            dict(PLAN["stages"][0], goal="stage one", checks=["echo ok > %s" % self.PATH1, HAS_F]),
            dict(PLAN["stages"][0], goal="stage two", checks=['test -s %s' % self.PATH1])])

    def test_a_file_an_accepted_stage_promised_and_a_later_check_reads(self):
        e = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        plan = self.two_stage()
        self.assertEqual(e.promised_missing(plan, 1), 0)  # stage 1 is accepted, the file is gone, stage 2 reads it
        Path(self.wt, self.PATH1).parent.mkdir(parents=True, exist_ok=True)
        Path(self.wt, self.PATH1).write_text("ok\n")
        self.assertIsNone(e.promised_missing(plan, 1))
        Path(self.wt, self.PATH1).unlink()
        own = dict(plan, stages=[plan["stages"][0], dict(plan["stages"][1], checks=["echo ok > %s && test -s %s" % (self.PATH1, self.PATH1)])])
        self.assertIsNone(e.promised_missing(own, 1))  # the later check writes it itself
        self.assertIsNone(e.promised_missing(plan, 0))  # nothing accepted yet

    def test_a_replanned_runs_goals_survive_the_stage_that_runs_again(self):
        e = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        e.reset(dict(BEAD))
        e.plan_data = self.two_stage()
        e.done, e.accepted = ["an earlier plan's goal", "stage one"], [0]
        e.save_checkpoint(stage=1, rounds=0, n=0, feedback="", step="write")
        again = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        again.reset(dict(BEAD))
        again.resume_point()
        self.assertEqual(again.done, ["an earlier plan's goal"])

    def test_a_resume_runs_the_stage_again_when_its_file_is_gone(self):
        e = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        e.reset(dict(BEAD))
        e.plan_data = self.two_stage()
        e.done, e.accepted = ["stage one"], [0]
        e.save_checkpoint(stage=1, rounds=0, n=0, feedback="", step="write")
        again = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        again.reset(dict(BEAD))
        plan, i, state = again.resume_point()
        self.assertEqual((i, state, again.accepted, again.done), (0, None, [], []))
        self.assertIn("a file stage 1 promised is missing", again.log_path.read_text())
        Path(self.wt, self.PATH1).parent.mkdir(parents=True, exist_ok=True)
        Path(self.wt, self.PATH1).write_text("ok\n")
        third = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        third.reset(dict(BEAD))
        self.assertEqual(third.resume_point()[1], 1)  # the file is there: stage 2 goes on



class Ledger(StagesTest):
    """tl-bxk.13.16.1: the plan says how each criterion is proved; review and verify go by it, not by the wording of an item."""

    LEFT = [{"title": "Import the chosen prefabs and add object rows", "why": "next bead"}]
    FILE = {"criterion": "Record the plan's follow-up issues about stale layer prose and bead wording", "check": "",
            "proved_by": "engine_step", "via": "file_beads"}
    DEFER = {"criterion": "A follow-up bead imports the chosen prefabs and adds object rows", "check": "",
             "proved_by": "leftover", "via": "Import the chosen prefabs and add object rows"}

    def plan(self, **kw):
        return dict(PLAN, cases=[self.FILE, self.DEFER, {"criterion": "f exists", "check": HAS_F, "proved_by": "check"}],
                    leftovers=self.LEFT, **kw)

    def test_the_review_is_told_what_the_engine_does_and_what_is_deferred(self):
        rc, s = self.run_engine({"plan": [self.plan()], "write": [WRITE], "review": [CLEAN]})
        review = s.prompts[2]
        self.assertIn("The engine does these itself", review)
        self.assertIn("Record the plan's follow-up issues", review)
        self.assertIn("Import the chosen prefabs", review)

    def test_a_ledgered_item_is_not_unmet_in_any_wording(self):
        unmet = ["A follow-up bead for importing the chosen prefabs and adding object rows is not filed",
                 "The plan's follow-up issues about stale layer prose and bead wording are not recorded"]
        rc, s = self.run_engine({"plan": [self.plan()], "write": [WRITE], "review": [review_with(unmet)]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer"])  # no send-back
        self.assertIn("unmet items dropped", self.eng.log_path.read_text())

    def test_a_claim_about_the_code_that_shares_words_with_a_deferred_item_is_not_that_item(self):
        e = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        e.plan_data = dict(PLAN, leftovers=[{"title": "Add tests for parser edge cases", "why": "later"}])
        self.assertEqual(e.ledger_route("parser edge cases are not handled"), "")
        self.assertEqual(e.ledger_route("The parser does not handle edge cases such as empty input or nested quotes"), "")
        self.assertEqual(e.ledger_route("Add tests for the parser edge cases"), "leftover")
        self.assertEqual(e.ledger_route("A follow-up bead for tests of parser edge cases is not filed"), "leftover")

    def test_a_defect_the_verifier_found_is_not_filed_away_by_the_ledger(self):
        e = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        e.plan_data = self.plan()
        e.unchecked = []
        what = "Import the chosen prefabs and add object rows"
        left = e.route_left([{"what": what, "kind": "checkable", "why": "found wrong: the rows are missing"}])
        self.assertEqual([u["what"] for u in left], [what])  # still a defect: not unverified, not settled
        self.assertEqual(e.unverified, [])

    def test_an_unrelated_unmet_item_still_sends_the_stage_back(self):
        rc, s = self.run_engine({"plan": [self.plan()], "write": [WRITE, WRITE],
                                 "review": [review_with(["The settings page does not save the volume"]), CLEAN]})
        self.assertEqual([c[0] for c in s.calls].count("worker"), 2)

    def test_unchecked_items_in_the_ledger_never_reach_the_verifier_or_the_writer(self):
        items = [{"what": "Record the plan's follow-up issues about stale layer prose and bead wording", "kind": "checkable", "source": ""},
                 {"what": "The follow-up bead for importing the chosen prefabs and adding object rows exists", "kind": "checkable", "source": ""}]
        rc, s = self.run_engine({"plan": [self.plan()], "write": [WRITE], "review": [dict(CLEAN, unchecked=items)]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer"])  # no verify call, no fix round
        self.assertEqual([u["what"] for u in self.eng.unverified], [items[1]["what"]])  # the deferral lands for the owner
        self.assertEqual(self.eng.verified[0]["why"], "the engine does this at land")

    def test_an_unrelated_checkable_item_is_still_verified(self):
        item = {"what": "The volume slider saves its value across restarts on every platform", "kind": "checkable", "source": ""}
        e = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        e.plan_data = self.plan()
        self.assertEqual(e.ledger_route(item["what"]), "")
        self.assertEqual(e.engine_steps([dict(item)]), [item])

    def test_a_deferred_case_the_plan_forgot_to_list_is_listed(self):
        plan = dict(PLAN, cases=[self.DEFER], leftovers=[])
        rc, s = self.run_engine({"plan": [plan], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([lo["title"] for lo in self.eng.plan_data["leftovers"]], ["Import the chosen prefabs and add object rows"])
        self.assertIn("Import the chosen prefabs and add object rows", self.created())

    def test_a_case_with_nothing_to_prove_it_goes_back_to_the_planner(self):
        bad = dict(PLAN, cases=[{"criterion": "the rows exist", "check": ""}])
        rc, s = self.run_engine({"plan": [bad, PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual([c[0] for c in s.calls], ["planner", "planner", "worker", "reviewer"])
        self.assertIn("case `the rows exist` has no check", s.prompts[1])
        self.assertEqual(lint.ledger_problems(self.plan()), [])

    def test_ledgered_cases_run_no_command(self):
        e = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        e.plan_data = self.plan()
        self.assertEqual(e.case_checks(), [HAS_F])
        self.assertEqual(lint.plan_checks(self.plan()), [HAS_F] + [c for st in PLAN["stages"] for c in st["checks"] if c != HAS_F])


def review_with(unmet):
    return dict(CLEAN, unmet=list(unmet))



class Inputs(StagesTest):
    """tl-bxk.13.16.3: inputs the criteria need that were not found are the owner's to decide in minute 4."""

    WIN = {"what": "a Windows PC to run the play test on", "kind": "platform", "path": ""}

    def test_a_missing_input_no_case_defers_is_an_assumption_not_an_ask(self):
        """tl-ntp: tl-7y6.6.15 stopped on study files no worktree can read; now the plan goes on and records it."""
        rc, s = self.run_engine({"plan": [dict(PLAN, unresolved=[self.WIN])], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertIsNone(self.ask())
        self.assertEqual([c[0] for c in s.calls][:2], ["planner", "worker"])
        plan = json.loads((self.eng.run_dir / "plan.json").read_text())
        self.assertEqual(plan["assumptions"], [{"step": "plan", "text": plan["assumptions"][0]["text"], "reversible": True}])
        self.assertIn("Windows PC", plan["assumptions"][0]["text"])
        self.assertIn("Assumption: ", self.eng.log_path.read_text())
        self.assertIn("Windows PC", s.prompts[1])  # the writer reads the plan, assumptions included

    def ask(self):
        p = tl.config_dir() / "asks" / "t-1.json"
        return json.loads(p.read_text()) if p.exists() else None

    def test_a_plan_question_about_missing_inputs_proceeds_to_write_with_an_assumption(self):
        q = dict(PLAN, question="84-self-hosting.md is outside the worktree: which draft do I follow?",
                 options=[{"label": "Wait", "cost": "slow", "answer": "wait", "recommended": True}])
        rc, s = self.run_engine({"plan": [q], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertIsNone(self.ask())
        plan = json.loads((self.eng.run_dir / "plan.json").read_text())
        self.assertEqual((plan["question"], plan["options"]), ("", []))
        self.assertIn("84-self-hosting.md", plan["assumptions"][0]["text"])
        self.assertTrue(plan["assumptions"][0]["reversible"])

    def test_a_reversible_question_with_no_stages_sends_the_planner_back_once_to_plan_on_it(self):
        q = dict(PLAN, stages=[], cases=[], question="Which file do I follow?")
        rc, s = self.run_engine({"plan": [q, PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls][:2], ["planner", "planner"])
        self.assertIn("Nothing in that question cannot be undone", s.prompts[1])
        plan = json.loads((self.eng.run_dir / "plan.json").read_text())
        self.assertIn("Which file do I follow?", plan["assumptions"][0]["text"])

    def test_an_irreversible_step_still_reaches_the_ask_path(self):
        self.assertEqual(sorted(engine.IRREVERSIBLE), ["close_epic", "delete_outside", "push_shared", "spend_money"])
        q = dict(PLAN, question="Push the rewritten history to main?", irreversible="push_shared",
                 options=[{"label": "Push", "cost": "shared", "answer": "push", "recommended": True},
                          {"label": "Hold", "cost": "slow", "answer": "hold", "recommended": False}])
        rc, s = self.run_engine({"plan": [q]})
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in s.calls], ["planner"])
        self.assertIn("Push the rewritten history", self.ask()["question"])

    def test_an_input_a_case_defers_is_no_question(self):
        case = {"criterion": "The play test passes on the Windows PC", "check": "", "proved_by": "leftover",
                "via": "Run the play test on a Windows PC"}
        plan = dict(PLAN, unresolved=[self.WIN], cases=[case], leftovers=[{"title": "Run the play test on a Windows PC", "why": "no PC"}])
        rc, s = self.run_engine({"plan": [plan], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertIn("inputs not found, their criteria deferred", self.eng.log_path.read_text())

    def test_a_file_that_is_there_after_all_is_dropped(self):
        plan = dict(PLAN, unresolved=[{"what": "the notes file", "kind": "file", "path": "a.txt"}])
        rc, s = self.run_engine({"plan": [plan], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)

    def test_after_the_owner_answered_the_engine_does_not_ask_again(self):
        ask = dict(WRITE, question="Which format?")
        self.run_engine({"plan": [PLAN], "write": [ask]})
        with mock.patch.object(tl, "comments", return_value=[{"author": "denis", "text": "Use the new format."}]):
            rc, s = self.run_engine({"plan": [dict(PLAN, unresolved=[self.WIN])], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)

    def test_planner_notes_reach_the_planner_as_text_or_a_repo_file(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, planner_notes="No Windows PC. Godot left main on 2026-10-12.")
        self.assertIn("Facts about this factory and project", s.prompts[0])
        self.assertIn("No Windows PC. Godot left main", s.prompts[0])
        (self.wt / "notes.md").write_text("The factory is a Mac only.\n")
        te.sh("git", "add", "-A", cwd=self.wt)
        te.sh("git", "commit", "-qm", "notes", cwd=self.wt)
        te.sh("git", "push", "-q", "origin", "HEAD:main", cwd=self.wt)
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, planner_notes="@notes.md")
        self.assertIn("The factory is a Mac only.", s.prompts[0])
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertNotIn("Facts about this factory", s.prompts[0])

class ResumeCount(StagesTest):
    """tl-19i: the re-plan limit counts failed plans on one base, never the owner's answer; a branch that conflicts with main starts again."""

    def behind_branch(self, conflict=False):
        """task/t-1 with one commit of earlier work, and main moved on (touching the same file when `conflict`)."""
        te.sh("git", "checkout", "-qb", "task/t-1", cwd=self.wt)
        (self.wt / ("a.txt" if conflict else "g.txt")).write_text("earlier work\n")
        te.sh("git", "add", "-A", cwd=self.wt)
        te.sh("git", "commit", "-qm", "wip (t-1): blocked", cwd=self.wt)
        te.sh("git", "checkout", "-q", "-", cwd=self.wt)
        base = Path(self.tmp.name, "base-moves")
        te.sh("git", "clone", "-q", str(Path(self.tmp.name, "o.git")), str(base), cwd=self.tmp.name)
        (base / ("a.txt" if conflict else "h.txt")).write_text("main moved on\n")
        te.sh("git", "add", "-A", cwd=base)
        te.sh("git", "commit", "-qm", "main moves", cwd=base)
        te.sh("git", "push", "-q", "origin", "HEAD:main", cwd=base)
        te.sh("git", "fetch", "-q", "origin", cwd=self.wt)

    def test_the_owners_answer_is_no_failed_plan_even_at_the_limit(self):
        ask = dict(WRITE, question="Which format?")
        rc, _ = self.run_engine({"plan": [PLAN], "write": [ask]}, max_replans=0)  # one plan allowed, no amend
        self.assertEqual(rc, 2)
        with mock.patch.object(tl, "comments", return_value=[{"author": "denis", "text": "Use the new format."}]):
            rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, max_replans=0)
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(s.calls[0][0], "planner")  # it amended
        self.assertEqual((self.eng.planned, self.eng.plan_log[-1]["counted"]), (1, False))

    def test_an_edit_with_no_ask_still_counts(self):
        # who edited the bead is not known: a comment from a sibling agent must not lift the limit
        self.run_engine({"plan": [PLAN], "write": [dict(WRITE, question="Which format?")]}, max_replans=1)
        path = tl.config_dir() / "asks" / "t-1.json"
        path.unlink()
        with mock.patch.object(tl, "show", return_value=dict(BEAD, description="Also say hi.")):
            rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, max_replans=1)
        self.assertEqual(self.eng.plan_log[-1]["counted"], True)

    def test_a_failed_plan_still_counts_and_the_limit_still_stops(self):
        flag = dict(WRITE, bad_checks=[{"cmd": FALSE, "why": "never passes"}])
        bad = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[FALSE])])
        rc, s = self.run_engine({"plan": [bad, bad], "write": [flag, flag]}, max_replans=1)
        self.assertEqual(rc, 2)
        self.assertTrue(self.blocked and self.blocked[0].startswith(engine.REPLAN_CAP))

    def test_a_rebase_onto_a_new_base_starts_the_plan_count_again(self):
        self.behind_branch()
        e = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        e.git("checkout", "-q", "task/t-1")
        e.planned, e.plan_log = 3, [{"mode": "plan", "why": "x"}] * 3
        self.assertEqual(e.rebase_onto_base(), "rebased")
        self.assertEqual((e.planned, e.rebase_resets), (0, 1))
        self.assertEqual(e.plan_log[-1]["counted"], False)  # the history stays, with a note
        self.assertEqual(e.rebase_onto_base(), "")  # nothing behind now

    def test_the_count_starts_again_after_a_rebase_at_most_twice_per_bead(self):
        e = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        e.rebase_resets = engine.MAX_REBASE_RESETS
        e.planned = 3
        self.behind_branch()
        e.git("checkout", "-q", "task/t-1")
        self.assertEqual(e.rebase_onto_base(), "rebased")
        self.assertEqual(e.planned, 3)  # a bead stuck for a real reason still reaches the limit while main moves

    def test_a_branch_that_conflicts_with_main_starts_again_fresh_and_nothing_is_counted(self):
        self.behind_branch(conflict=True)
        with mock.patch.object(tl, "comments", return_value=[{"author": "denis", "text": "Use the new format."}]):
            rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, max_replans=0)
        self.assertEqual(rc, 0, self.blocked)
        text = self.eng.log_path.read_text()
        self.assertIn("resume_conflict", text)
        self.assertIn("resume conflict: task/t-1 kept as task/t-1-stale-", text)
        self.assertNotIn("<old_plan>", s.prompts[0])  # a fresh plan, not an amend
        self.assertIn("Use the new format.", s.prompts[0])  # the answer is in the planner's brief
        self.assertEqual(self.eng.planned, 1)
        out = engine.subprocess.run(["git", "branch", "--list", "task/t-1-stale-*"], cwd=self.wt, capture_output=True, text=True).stdout
        self.assertIn("task/t-1-stale-", out)  # the earlier work is kept
        shown = engine.subprocess.run(["git", "show", "origin/main:a.txt"], cwd=self.wt, capture_output=True, text=True).stdout
        self.assertEqual(shown, "main moved on\n")
        self.assertTrue(any("Resume (engine)" in str(c) for c in self.bd_calls))  # the bead says where the parked work is

    # -- tl-7y6.2.19: a resume conflict is squashed and fixed in place (a few files), not thrown away
    def wip_branch(self, steps, main, files=("a.txt",)):
        """task/t-1 with one wip commit per entry of `steps` (the text every file in `files` gets), a checkpoint mid-stage, and
        main moved on to `main` in the same files. The slot is left detached at the base, as a parked run leaves it."""
        te.sh("git", "checkout", "-qb", "task/t-1", cwd=self.wt)
        for n, text in enumerate(steps):
            for f in files:
                (self.wt / f).write_text(text + "\n")
            te.sh("git", "add", "-A", cwd=self.wt)
            te.sh("git", "commit", "-qm", "wip (t-1): %d" % n, cwd=self.wt)
        base = Path(self.tmp.name, "base-moves")
        te.sh("git", "clone", "-q", str(Path(self.tmp.name, "o.git")), str(base), cwd=self.tmp.name)
        for f in files:
            (base / f).write_text(main + "\n")
        te.sh("git", "add", "-A", cwd=base)
        te.sh("git", "commit", "-qm", "main moves", cwd=base)
        te.sh("git", "push", "-q", "origin", "HEAD:main", cwd=base)
        e = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        e.reset(dict(BEAD))
        e.plan_data = dict(PLAN)
        e.save_checkpoint(stage=0, rounds=0, n=1, feedback="", step="write")
        te.sh("git", "checkout", "-q", "--detach", "origin/main", cwd=self.wt)

    def resolving_worker(self, which=1, file="a.txt", text="merged"):
        """The `which`-th worker call resolves `file` (the conflict fix), as a real writer would."""
        real = fake_route.Script.reply

        def call(this, role, *a, **kw):
            r = real(this, role, *a, **kw)
            if role == "worker" and [c[0] for c in this.calls].count("worker") == which:
                Path(this.cwds[-1], file).write_text(text + "\n")
            return r
        return mock.patch.object(fake_route.Script, "reply", call)

    def last_trace(self):
        return json.loads((tl.config_dir() / "traces.jsonl").read_text().splitlines()[-1])

    def test_wip_commits_that_conflict_only_unsquashed_are_squashed_and_rebase_without_a_fix(self):
        self.wip_branch(["step 1", "step 2", "step 3", "main moved on"], "main moved on")
        rc, s = self.run_engine({"write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["worker", "reviewer"])  # no fix round, no plan
        text = self.eng.log_path.read_text()
        self.assertIn("squashed the branch's wip commits into one", text)
        self.assertNotIn("resume_conflict", text)
        self.assertFalse(self.last_trace()["salvaged"])
        self.assertEqual(te.tl.git("show", "origin/main:a.txt", cwd=str(self.wt)), "main moved on")
        self.assertEqual(engine.subprocess.run(["git", "branch", "--list", "task/t-1-stale-*"], cwd=self.wt, capture_output=True, text=True).stdout, "")

    def test_a_real_resume_conflict_in_a_few_files_is_fixed_not_thrown_away(self):
        self.wip_branch(["mine 1", "mine 2"], "theirs")
        with self.resolving_worker():
            rc, s = self.run_engine({"write": [WRITE, WRITE], "review": [CLEAN, CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["worker", "reviewer", "worker", "reviewer"])  # the conflict fix, then the stage; no plan
        self.assertIn("conflict", s.prompts[0])
        text = self.eng.log_path.read_text()
        self.assertNotIn("resume_conflict", text)
        self.assertTrue(self.last_trace()["salvaged"])
        self.assertEqual(te.tl.git("show", "origin/main:a.txt", cwd=str(self.wt)), "merged")
        self.assertEqual(self.eng.fixes, 0)  # the land's two fix rounds are its own
        self.assertEqual(engine.subprocess.run(["git", "branch", "--list", "task/t-1-stale-*"], cwd=self.wt, capture_output=True, text=True).stdout, "")

    def test_a_resume_conflict_in_more_than_ten_files_starts_again_as_before(self):
        files = ["c%d.txt" % n for n in range(11)]
        self.wip_branch(["mine 1", "mine 2"], "theirs", files=files)
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer"])
        self.assertIn("resume_conflict", self.eng.log_path.read_text())
        self.assertFalse(self.last_trace()["salvaged"])
        out = engine.subprocess.run(["git", "branch", "--list", "task/t-1-stale-*"], cwd=self.wt, capture_output=True, text=True).stdout
        self.assertIn("task/t-1-stale-", out)
        stale = out.split()[-1]
        self.assertEqual(te.tl.git("show", stale + ":c0.txt", cwd=str(self.wt)), "mine 2")  # the work is kept whole

    def test_exactly_ten_conflicted_files_are_still_fixed(self):
        files = ["c%d.txt" % n for n in range(10)]
        self.wip_branch(["mine"], "theirs", files=files)
        real = fake_route.Script.reply

        def fix_all(this, role, *a, **kw):
            r = real(this, role, *a, **kw)
            if role == "worker" and not any(Path(this.cwds[-1], f).read_text() == "merged\n" for f in files):
                for f in files:
                    Path(this.cwds[-1], f).write_text("merged\n")
            return r
        with mock.patch.object(fake_route.Script, "reply", fix_all):
            rc, s = self.run_engine({"write": [WRITE, WRITE], "review": [CLEAN, CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertTrue(self.last_trace()["salvaged"])

    def test_a_conflict_fix_that_does_not_resolve_it_restores_the_branch_and_starts_again(self):
        self.wip_branch(["mine 1", "mine 2"], "theirs")
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE] * 3, "review": [CLEAN]}, max_check_tries=1, max_rounds=1)
        self.assertEqual(rc, 0, self.blocked)
        self.assertIn("resume_conflict", self.eng.log_path.read_text())
        self.assertFalse(self.last_trace()["salvaged"])
        out = engine.subprocess.run(["git", "branch", "--list", "task/t-1-stale-*"], cwd=self.wt, capture_output=True, text=True).stdout
        stale = out.split()[-1]
        self.assertEqual(te.tl.git("show", stale + ":a.txt", cwd=str(self.wt)), "mine 2")  # the original work, not a half-fixed rebase
        self.assertEqual(self.eng.fixes, 0)

    def test_a_branch_that_cannot_be_kept_aside_is_not_reset(self):
        self.behind_branch(conflict=True)
        e = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        e.git("checkout", "-q", "task/t-1")
        e.branch = "task/t-1"
        before = e.git("rev-parse", "HEAD")
        real = e.sh
        e.sh = lambda cmd, **kw: (1, "refused") if cmd[:3] == ["git", "branch", "-m"] else real(cmd, **kw)
        self.assertFalse(e.start_again_on_base("x"))
        self.assertEqual(e.git("rev-parse", "HEAD"), before)  # the work is where it was
        e.sh = real
        e.git("checkout", "-q", "--detach")
        self.assertFalse(e.start_again_on_base("x"))  # detached: nothing renamed or reset

    def test_a_fresh_start_clears_what_the_old_attempt_left(self):
        self.behind_branch(conflict=True)
        e = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        e.git("checkout", "-q", "task/t-1")
        e.branch = "task/t-1"
        e.unverified, e.look_paths, e.handoff["rounds"], e.fixes, e.replans, e.rendered_names = [{"what": "x"}], ["p.png"], [{"r": 1}], 2, 2, {"a.png"}
        e.verify_answer = "Use the old format"
        self.assertTrue(e.start_again_on_base("x"))
        self.assertEqual((e.unverified, e.look_paths, e.handoff["rounds"], e.fixes, e.replans, e.rendered_names), ([], [], [], 0, 0, set()))
        self.assertEqual(e.verify_answer, "Use the old format")  # the owner's word still goes to the planner



class Claims(StagesTest):
    """tl-159, tl-wjj, tl-05s."""

    def setUp(self):
        global real_cmd_block
        real_cmd_block = _REAL_CMD_BLOCK
        super().setUp()

    def test_a_parked_bead_whose_actor_is_live_elsewhere_can_be_taken_over(self):
        parked = {"id": "t-1", "status": "blocked", "assignee": "tl-2be89f88", "lease_expires_at": "2999-01-01T00:00:00Z", "dependencies": []}
        comments = [{"text": "Blocked: stuck: re-planned 3 times", "created_at": "1", "author": "engine"}]
        import loop
        with mock.patch.object(tl, "show", return_value=parked), mock.patch.object(tl, "live_actors", return_value={"tl-2be89f88"}), \
                mock.patch.object(tl, "comments", return_value=comments), mock.patch.object(loop, "running", return_value={}), \
                mock.patch.object(tl, "bd", return_value=mock.Mock(returncode=0)) as bd:
            ok, why = engine.reclaim("t-1", str(self.wt))
        self.assertTrue(ok, why)
        self.assertEqual(why, "reopened")
        self.assertEqual(bd.call_args_list[0][0], ("update", "t-1", "--status", "open", "--if-assignee", "tl-2be89f88", "--assignee", ""))

    def test_a_parked_bead_with_an_engine_still_on_it_is_a_live_claim(self):
        parked = {"id": "t-1", "status": "blocked", "assignee": "tl-2be89f88", "lease_expires_at": "", "dependencies": []}
        import loop
        with mock.patch.object(tl, "show", return_value=parked), mock.patch.object(tl, "live_actors", return_value=set()), \
                mock.patch.object(loop, "running", return_value={"t-1": "s2"}):
            ok, why = engine.reclaim("t-1", str(self.wt))
        self.assertFalse(ok)
        self.assertIn("a live claim", why)

    def test_a_working_bead_of_a_live_actor_is_still_a_live_claim(self):
        busy = {"id": "t-1", "status": "in_progress", "assignee": "tl-2be89f88", "lease_expires_at": "", "dependencies": []}
        with mock.patch.object(tl, "show", return_value=busy), mock.patch.object(tl, "live_actors", return_value={"tl-2be89f88"}):
            ok, why = engine.reclaim("t-1", str(self.wt))
        self.assertFalse(ok)
        self.assertIn("a live claim", why)

    @te.no_repo
    def test_parking_a_bead_lets_go_of_its_claim(self):
        calls = []
        for holder, expect in (("tl-2be89f88", ("update", "t-1", "--status", "blocked", "--assignee", "")),
                               ("denis", ("update", "t-1", "--status", "blocked")), ("", ("update", "t-1", "--status", "blocked"))):
            calls.clear()
            with mock.patch.object(tl, "bd", side_effect=lambda *a, **k: calls.append(a) or mock.Mock(returncode=0, stdout="", stderr="")), \
                    mock.patch.object(tl, "show", return_value={"assignee": holder}), \
                    mock.patch.object(tl, "event"), mock.patch.object(tl, "provenance"):
                self.assertEqual(real_cmd_block(mock.Mock(id="t-1", why="stuck")), 0)
            self.assertEqual(calls[0], expect, holder)  # a person's own claim stays theirs

    def test_a_plan_with_no_stages_goes_back_to_the_planner_once(self):
        empty = dict(PLAN, stages=[])
        rc, s = self.run_engine({"plan": [empty, PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["planner", "planner", "worker", "reviewer"])
        self.assertIn("it has no stages, no question and no leftovers", s.prompts[1])
        self.assertIn("has no stages", self.eng.log_path.read_text())

    def test_a_plan_that_stays_empty_after_the_send_back_still_fails(self):
        empty = dict(PLAN, stages=[])
        rc, s = self.run_engine({"plan": [empty, empty]})
        self.assertNotEqual(rc, 0)
        self.assertEqual(self.blocked, [])
        self.assertIn("no stages", te.EngineTest.said(self))
        self.assertEqual([c[0] for c in s.calls], ["planner", "planner"])

    def test_an_empty_plan_with_leftovers_or_a_question_is_not_sent_back(self):
        rc, s = self.run_engine({"plan": [dict(PLAN, stages=[], leftovers=[{"title": "File it", "why": "x"}])]})
        self.assertEqual([c[0] for c in s.calls], ["planner"])
        self.assertEqual(rc, 0)

    REFLECTION = {"went_well": ["the plan was right at once"], "wasted": ["2 min waiting for a lane"], "change": ["engine: none"],
                  "went_badly": [{"what": "the review sent the same finding back twice", "cause": "prompt", "session": "ref-review",
                                  "evidence": "2 reviews, same file:line"}]}

    def test_a_run_ends_with_a_reflection_in_the_trace_and_the_bead_comment(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN], "reflect": [self.REFLECTION]}, reflect=True)
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer", "reviewer"])  # the reflection is the last call
        self.assertIn("Bead t-1: Add f", s.prompts[3])
        self.assertIn("session ref-write", s.prompts[3])  # the sessions to cite
        last = json.loads((tl.config_dir() / "traces.jsonl").read_text().splitlines()[-1])
        self.assertEqual(last["reflection"]["went_badly"][0]["cause"], "prompt")
        self.assertEqual(last["reflection"]["went_badly"][0]["session"], "ref-review")
        comment = [c[3] for c in self.bd_calls if c[:2] == ("comments", "add") and c[3].startswith("Reflect (engine)")][0]
        self.assertIn("reflection: badly: [prompt] the review sent the same finding back twice (session ref-review)", comment)
        self.assertLess(comment.index("reflection:"), comment.index("filed="))  # first: the view of the last run clips at 400 characters
        self.assertEqual(last["stats"]["tokens_in"], sum(s["tokens"]["in"] for s in last["sessions"] if s["node"] != "reflect"))

    def test_a_reflection_that_fails_changes_nothing(self):
        crash = fake_route.NO_ANSWER
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN], "reflect": [crash, crash, crash]}, reflect=True)
        self.assertEqual(rc, 0, self.blocked)
        last = json.loads((tl.config_dir() / "traces.jsonl").read_text().splitlines()[-1])
        self.assertEqual((last["outcome"], last["reflection"]), ("landed", None))
        self.assertTrue(self.closed and self.closed[0].startswith("merged"))

    def test_no_reflection_for_a_paused_run_or_when_switched_off(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})  # reflect off in the harness
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer"])
        e = engine.Engine("t-1", str(self.wt), dict(engine.load_cfg(str(self.wt)), reflect=True))
        e.route = "/fake/route.py"
        e.sessions = [{"node": "plan"}]
        self.assertIsNone(e.reflect_run("failed", "failed: x"))  # a run that only planned
        e.sessions = [{"node": "plan"}, {"node": "write"}]
        self.assertIsNone(e.reflect_run("blocked", "paused: no lane for write until 04:00"))
        e.stop_pending = True
        self.assertIsNone(e.reflect_run("landed", ""))  # a stop is on its way
        e.stop_pending = False
        self.assertIsNone(e.reflect_run("failed", "failed: infrastructure: bad_request"))
        e.dry = True
        self.assertIsNone(e.reflect_run("landed", ""))

    @te.no_repo
    def test_the_reflection_text_names_cause_and_session(self):
        text = engine.reflection_text(self.REFLECTION)
        self.assertIn("[prompt]", text)
        self.assertIn("(session ref-review)", text)
        self.assertEqual(engine.reflection_text(None), "")
        self.assertIn("badly: none", engine.reflection_text(dict(self.REFLECTION, went_badly=[])))



class StaleTree(StagesTest):
    """tl-fsj: the tree a check runs on must have what the base's config names."""

    stop_at = te.EngineTest.stop_at
    stopped_run = te.EngineTest.stopped_run

    def main_moves(self, name="moved.txt"):
        base = Path(self.tmp.name, "base-moves")
        if not base.exists():
            te.sh("git", "clone", "-q", str(Path(self.tmp.name, "o.git")), str(base), cwd=self.tmp.name)
        te.sh("git", "pull", "-q", "origin", "main", cwd=base)
        (base / name).write_text("main moved on\n")
        te.sh("git", "add", "-A", cwd=base)
        te.sh("git", "commit", "-qm", "main moves", cwd=base)
        te.sh("git", "push", "-q", "origin", "HEAD:main", cwd=base)

    def test_a_resume_mid_stage_rebases_first_and_goes_on(self):
        self.stopped_run()
        self.main_moves()
        rc, s = self.run_engine({"write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        text = self.eng.log_path.read_text()
        self.assertIn("rebased the task branch onto the latest origin/main", text)
        self.assertNotIn("planner", [c[0] for c in s.calls])  # the plan was kept
        self.assertEqual(self.eng.stage_tree, "")

    def junk_and_moving_main(self):
        """The slot has Unity's untracked log (the base ignores it) and main has moved on with a new recipe file."""
        base = Path(self.tmp.name, "base-ignore")
        te.sh("git", "clone", "-q", str(Path(self.tmp.name, "o.git")), str(base), cwd=self.tmp.name)
        (base / ".gitignore").write_text("client/log.txt\n")
        (base / "justfile").write_text("fmt-check-changed:\n\techo ok\n")
        te.sh("git", "add", "-A", cwd=base)
        te.sh("git", "commit", "-qm", "recipe and ignore", cwd=base)
        te.sh("git", "push", "-q", "origin", "HEAD:main", cwd=base)
        te.sh("git", "fetch", "-q", "origin", cwd=self.wt)
        (self.wt / "client").mkdir(exist_ok=True)
        (self.wt / "client" / "log.txt").write_text("unity wrote this\n")

    def test_a_resume_start_rebases_even_with_a_base_ignored_file_in_the_slot(self):
        # lifesim-fld.27.12-20261024-230954: started_because resume, 75 commits behind, no rebase, the check named a recipe the tree lacked
        self.stopped_run()
        te.sh("git", "checkout", "-q", "task/t-1", cwd=self.wt)
        self.junk_and_moving_main()
        rc, s = self.run_engine({"write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertIn("rebased the task branch onto the latest origin/main", self.eng.log_path.read_text())
        self.assertTrue(Path(self.wt, "justfile").exists() or "justfile" in self.eng.git("ls-tree", "-r", "--name-only", "HEAD"))

    def test_an_answer_start_rebases_even_with_a_base_ignored_file_in_the_slot(self):
        # lifesim-6pld-20261024-224705: started_because answer, the same
        te.sh("git", "checkout", "-q", "-b", "task/t-1", cwd=self.wt)
        (self.wt / "g.txt").write_text("earlier work\n")
        te.sh("git", "add", "-A", cwd=self.wt)
        te.sh("git", "commit", "-qm", "wip (t-1): blocked", cwd=self.wt)
        te.sh("git", "checkout", "-q", "-", cwd=self.wt)
        self.junk_and_moving_main()
        te.sh("git", "checkout", "-q", "task/t-1", cwd=self.wt)
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertIn("rebased the task branch onto the latest origin/main", self.eng.log_path.read_text())

    def test_a_tracked_change_in_the_slot_still_stops_the_rebase(self):
        te.sh("git", "checkout", "-q", "-b", "task/t-1", cwd=self.wt)
        e = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        self.junk_and_moving_main()
        (self.wt / "a.txt").write_text("edited and not committed\n")
        self.assertEqual(e.rebase_onto_base(), "")

    def test_the_writer_is_told_the_check_variables_exist_only_inside_the_engines_checks(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        writer = s.prompts[1]
        self.assertIn("exist only while the engine runs the checks, never in your session", writer)
        self.assertIn("do not call it a blocker", writer)

    def test_a_resume_that_conflicts_with_main_starts_again(self):
        te.sh("git", "checkout", "-qb", "task/t-1", cwd=self.wt)
        (self.wt / "a.txt").write_text("my work\n")
        te.sh("git", "add", "-A", cwd=self.wt)
        te.sh("git", "commit", "-qm", "wip", cwd=self.wt)
        te.sh("git", "checkout", "-q", "-", cwd=self.wt)
        self.main_moves("a.txt")
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertIn("resume_conflict", self.eng.log_path.read_text())

    def test_a_configured_check_the_tree_lacks_is_the_engines_error_not_a_writers_amend(self):
        miss = [{"id": "fmt", "cmd": te.PY + " -c \"import sys; sys.stderr.write('error: Justfile does not contain recipe `fmt-check-changed`.'); sys.exit(1)\"",
                 "group": "static"}]
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE]}, checks=miss)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker"])  # no second write: nothing was sent back to the writer
        self.assertTrue(self.eng.why.startswith("failed: infrastructure: the configured check `fmt` needs something this tree lacks"), self.eng.why)

    @te.no_repo
    def test_words_in_the_middle_of_a_long_output_are_not_a_stale_tree(self):
        noisy = "a test about justfile prints: This checkout has no recipe x\n" + "ok\n" * 300 + "2 failed: Foo"
        self.assertTrue(engine.STALE_TREE.search(noisy))  # the whole log matches...
        self.assertFalse(engine.STALE_TREE.search(noisy[-500:]))  # ...its last lines, which the engine reads, do not

    def test_the_checkpoint_head_follows_a_squash_and_rebase_over_the_wip_commit(self):
        te.sh("git", "checkout", "-qb", "task/t-1", cwd=self.wt)
        (self.wt / "g.txt").write_text("work\n")
        te.sh("git", "add", "-A", cwd=self.wt)
        te.sh("git", "commit", "-qm", "work", cwd=self.wt)
        e = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        before = e.git("rev-parse", "HEAD")
        (self.wt / "g.txt").write_text("more work\n")
        te.sh("git", "commit", "-qam", "wip (t-1): blocked", cwd=self.wt)  # what reset() does with a dirty tree
        e.left_dirty = True
        e.checkpoint_path().parent.mkdir(exist_ok=True)
        e.checkpoint_path().write_text(json.dumps({"v": 1, "head": before}))
        self.main_moves()
        te.sh("git", "fetch", "-q", "origin", cwd=self.wt)
        self.assertEqual(e.rebase_onto_base(), "rebased")
        self.assertEqual(json.loads(e.checkpoint_path().read_text())["head"], e.git("rev-parse", "HEAD"))  # tl-7y6.2.19: the wip commit is squashed in
        self.assertEqual(e.git("rev-list", "--count", "origin/main..HEAD"), "1")

    def test_the_lifesim_wording_is_found_too_and_a_plain_red_check_is_not(self):
        self.assertTrue(engine.STALE_TREE.search("This checkout has no fmt-check-changed; rebase onto main"))
        self.assertFalse(engine.STALE_TREE.search("2 tests failed: FooTests.Bar"))
        plain = [{"id": "unit", "cmd": FALSE, "group": "tests"}]
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, WRITE, WRITE]}, checks=plain, max_check_tries=2)
        self.assertNotIn("infrastructure", self.eng.why)

    def test_a_plan_check_that_prints_the_same_words_is_the_writers_not_the_engines(self):
        words = te.PY + " -c \"import sys; sys.stderr.write('Justfile does not contain recipe x'); sys.exit(1)\""
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[words])])
        rc, s = self.run_engine({"plan": [plan], "write": [WRITE, WRITE, WRITE]}, max_check_tries=2)
        self.assertNotIn("infrastructure", self.eng.why)



class SlotHygiene(StagesTest):
    """tl-g6a: base-ignored files do not make a slot dirty; a parked bead leaves the slot at the base."""

    def put_ignore_on_main(self, text, name=".gitignore", sub=""):
        base = Path(self.tmp.name, "base-ignore")
        if not base.exists():
            te.sh("git", "clone", "-q", str(Path(self.tmp.name, "o.git")), str(base), cwd=self.tmp.name)
        te.sh("git", "pull", "-q", "origin", "main", cwd=base)
        d = base / sub
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(text)
        te.sh("git", "add", "-A", cwd=base)
        te.sh("git", "commit", "-qm", "gitignore", cwd=base)
        te.sh("git", "push", "-q", "origin", "HEAD:main", cwd=base)
        te.sh("git", "fetch", "-q", "origin", cwd=self.wt)

    def test_files_the_base_ignores_do_not_count_as_dirty_work(self):
        self.put_ignore_on_main("client/log.txt\n")
        self.put_ignore_on_main("*.log\n!keep.log\n", sub="client")
        (self.wt / "client").mkdir()
        for f in ("client/log.txt", "client/Logs.log", "client/deep/x.log"):
            Path(self.wt, f).parent.mkdir(parents=True, exist_ok=True)
            Path(self.wt, f).write_text("noise\n")
        e = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        self.assertEqual(e.dirty_status(), "")
        self.assertIn("?? client/", e.git("status", "--porcelain"))  # git alone calls it dirty: the old tree has no such rule
        Path(self.wt, "client/keep.log").write_text("real\n")  # negated by the base: real work
        Path(self.wt, "client/src.cs").write_text("real\n")
        self.assertEqual(sorted(l[3:] for l in e.dirty_status().splitlines()), ["client/keep.log", "client/src.cs"])

    def test_the_users_own_global_excludes_still_apply(self):
        self.put_ignore_on_main("client/log.txt\n")
        glob = Path(self.tmp.name, "global-ignore")
        glob.write_text("*.swp\n")
        te.sh("git", "config", "core.excludesFile", str(glob), cwd=self.wt)
        (self.wt / "notes.swp").write_text("editor\n")
        (self.wt / "client").mkdir()
        (self.wt / "client" / "log.txt").write_text("unity\n")
        e = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        self.assertEqual(e.dirty_status(), "")

    def test_files_the_base_does_not_ignore_keep_a_parked_slot_where_it_is(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [dict(WRITE, question="Which format?")]})
        self.assertEqual(rc, 2)
        # the bead's branch is checked out again by the next run; a stray untracked file the commit left out blocks the detach
        e = self.eng
        e.git("checkout", "-q", "task/t-1")
        (self.wt / "stray.dat").write_text("not ignored, not committed\n")
        e.leave_slot("blocked", "task/t-1")
        self.assertEqual(e.git("symbolic-ref", "--short", "-q", "HEAD"), "task/t-1")

    def test_a_slot_left_on_an_old_branch_with_only_ignored_files_is_not_another_branchs_work(self):
        te.sh("git", "checkout", "-qb", "task/old-bead", cwd=self.wt)
        self.put_ignore_on_main("client/log.txt\nclient/log-previous.txt\n")
        (self.wt / "client").mkdir()
        (self.wt / "client" / "log.txt").write_text("unity\n")
        (self.wt / "client" / "log-previous.txt").write_text("unity\n")
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertNotIn("another branch", self.eng.why)

    def test_real_work_of_another_branch_still_stops_the_run(self):
        te.sh("git", "checkout", "-qb", "task/old-bead", cwd=self.wt)
        (self.wt / "keep.py").write_text("work\n")
        rc, s = self.run_engine({"plan": [PLAN]})
        self.assertNotEqual(rc, 0)
        self.assertIn("uncommitted work of another branch", self.eng.why)

    def test_a_parked_bead_leaves_the_slot_at_the_detached_base(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [dict(WRITE, question="Which format?")]})
        self.assertEqual(rc, 2)
        head = engine.subprocess.run(["git", "symbolic-ref", "-q", "HEAD"], cwd=self.wt, capture_output=True, text=True)
        self.assertNotEqual(head.returncode, 0)  # detached
        self.assertEqual(self.eng.git("rev-parse", "HEAD"), self.eng.git("rev-parse", "origin/main"))
        self.assertTrue(self.eng.git("rev-parse", "--verify", "-q", "refs/heads/task/t-1"))  # the branch keeps the bead's work

    def test_a_parked_bead_with_work_commits_it_to_its_branch_first(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [dict(WRITE, question="Which format?")]})
        self.assertEqual(rc, 2)
        log = self.eng.git("log", "--format=%s", "task/t-1")
        self.assertIn("wip (t-1)", log)  # f.txt was written by the writer: kept on the bead's branch
        self.assertEqual(Path(self.wt, "f.txt").exists(), False)  # and gone from the slot

    def test_the_beads_new_files_go_to_its_branch_when_it_parks_and_the_base_ignored_junk_does_not(self):
        self.put_ignore_on_main("client/log.txt\n")
        (self.wt / "tests").mkdir(exist_ok=True)

        class Writer(fake_route.Script):  # a writer that makes a new feature file nothing in the plan names, and Unity's log
            def reply(this, role, prompt, schema, cwd, *a, **kw):
                if role == "worker":
                    Path(cwd, "tests", "edit_content.feature").write_text("Feature: x\n")
                    (Path(cwd) / "client").mkdir(exist_ok=True)
                    (Path(cwd) / "client" / "log.txt").write_text("unity\n")
                return super().reply(role, prompt, schema, cwd, *a, **kw)
        with mock.patch.object(fake_route, "Script", Writer):
            rc, s = self.run_engine({"plan": [PLAN], "write": [dict(WRITE, question="Which format?")]})
        self.assertEqual(rc, 2)
        branch_files = self.eng.git("ls-tree", "-r", "--name-only", "task/t-1").splitlines()
        self.assertIn("tests/edit_content.feature", branch_files)  # not lost: it is on the bead's branch
        self.assertNotIn("client/log.txt", branch_files)  # the base ignores it: no junk on the branch
        self.assertFalse(Path(self.wt, "tests", "edit_content.feature").exists())  # and the slot is at the base
        self.assertFalse(self.eng.git("symbolic-ref", "--short", "-q", "HEAD"))

class DeadLane(StagesTest):
    """A lane that fails to start without being marked out must not hold a read-only step for ten minutes."""

    def blips(self, n, lane="GROK_SUBSCRIPTION"):
        """vendor_blip (lane / transient / poll): the lane failed to start. Three polls wait for it, the next try goes elsewhere."""
        return [te.stop("vendor_blip", family="xai", lane=lane, say="opencode failed before any work: spending limit")] * n

    def test_a_retry_from_a_failing_family_routes_the_next_try_past_it(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": self.blips(4) + [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        reviews = [c for c in s.calls if c[0] == "reviewer"]
        self.assertEqual(len(reviews), 5)  # three polls of the lane, then the route is asked again
        self.assertEqual(reviews[4][2], "xai")  # authored-by the failing family: the route puts the others first
        self.assertNotEqual(reviews[0][2], "xai")

    def test_the_writers_own_family_after_a_dead_lane_is_flagged_same_family(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": self.blips(4) + [CLEAN]},
                                j_extra={"review": [{"family": "openai"}]})  # the route landed on openai, the writer's family
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(self.eng.last_flag, "same_family")
        self.assertIn("review is from the writer's own model family", self.eng.log_path.read_text())

    def test_a_same_family_step_with_delegates_warning_is_logged_traced_and_commented_never_paused(self):
        extra = {"review": [{"flag": "same_family", "warning": "only the Codex lane is up: the review is the writer's own model"}]}
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, j_extra=extra)
        self.assertEqual(rc, 0, self.blocked)
        note = "the review step ran on the writer's own model family: only the Codex lane is up"
        self.assertIn(note, self.eng.log_path.read_text())
        comments = [c[3] for c in self.bd_calls if c[:2] == ("comments", "add") and c[3].startswith("Lane (engine)")]
        self.assertEqual(len(comments), 1)
        self.assertIn(note, comments[0])
        last = json.loads((tl.config_dir() / "traces.jsonl").read_text().splitlines()[-1])
        self.assertEqual(last["lane_notes"], [note + last["lane_notes"][0][len(note):]])
        self.assertIn("only the Codex lane is up", [s_["warning"] for s_ in last["sessions"] if s_["node"] == "review"][0])
        self.assertTrue(self.closed)  # it landed

    def test_one_family_failing_twice_is_not_switched_back_and_forth(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": self.blips(5, "GROK") + [CLEAN]})
        reviews = [c for c in s.calls if c[0] == "reviewer"]
        self.assertEqual([c[2] for c in reviews][4:], ["xai", "xai"])  # rebound once, kept

    def test_a_busy_lane_is_waited_for_as_before(self):
        busy = te.stop("busy", family="openai", lane="OPENAI_SUBSCRIPTION", say="no free slot")
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [busy, CLEAN]})
        reviews = [c for c in s.calls if c[0] == "reviewer"]
        self.assertEqual(reviews[1][2], reviews[0][2])


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

    @te.no_repo
    def test_a_hooks_test_output_before_the_push_is_not_a_network_error(self):
        tail = "tests: Connection refused by the fake server (expected)\n" + "ok test passed\n" * 60 + "error: failed to push some refs\n"
        self.assertTrue(engine.TRANSIENT_PUSH.search(tail))  # the whole output would match
        self.assertFalse(engine.TRANSIENT_PUSH.search(tail[-600:]))  # the engine reads only the push's own last lines

    @te.no_repo
    def test_a_rejected_or_other_push_failure_is_not_retried_as_the_network(self):
        self.assertFalse(engine.TRANSIENT_PUSH.search("! [rejected] HEAD -> main (non-fast-forward)"))
        self.assertFalse(engine.TRANSIENT_PUSH.search("remote: error: GH006: Protected branch update failed"))
        self.assertTrue(engine.TRANSIENT_PUSH.search("fatal: unable to access 'https://x/': Could not resolve host: x"))

    def test_a_delegate_crash_is_retried_fresh_and_the_run_goes_on(self):
        crash = fake_route.NO_ANSWER  # route.py died: delegate printed no answer
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [crash, CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer", "reviewer"])
        self.assertIn("delegate crashed", self.eng.log_path.read_text())

    def test_the_wip_commit_skips_the_pre_commit_hook_and_a_failed_one_is_loud(self):
        import os
        import subprocess
        self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        eng = self.eng
        hook = Path(eng.git("rev-parse", "--path-format=absolute", "--git-common-dir")) / "hooks" / "pre-commit"
        hook.parent.mkdir(exist_ok=True)
        hook.write_text("#!/bin/sh\necho 'csharpier: unformatted' >&2\nexit 1\n")
        os.chmod(str(hook), 0o755)
        (Path(eng.wt) / "wip-file.txt").write_text("x\n")
        self.assertTrue(eng.wip("paused"))
        self.assertEqual(eng.git("status", "--porcelain"), "")
        self.assertIn("wip (t-1): paused", eng.git("log", "-1", "--format=%s"))
        (Path(eng.wt) / "wip-file2.txt").write_text("y\n")
        with mock.patch.object(eng, "sh", return_value=(1, "fatal: boom")), mock.patch.object(eng, "warn") as warn:
            self.assertFalse(eng.wip("paused"))
        self.assertIn("wip commit", warn.call_args[0][0])
        self.assertIn("boom", warn.call_args[0][0])

    def test_a_lane_that_is_out_for_hours_pauses_with_its_reset_time_and_is_not_waited_for(self):
        # lifesim r0yc/rl4s: the dead lane's own reset time is hours away; delegate re-routes inside the call, so a stop is final
        import time
        due = time.time() + 3 * 3600
        out = te.stop("rate_limited", say="lane_out: ZAI", lane="ZAI", at=due)
        rc, s = self.run_engine({"plan": [PLAN], "write": [out, WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker"])
        self.assertAlmostEqual(self.eng.retry_after, due, delta=1)
        self.assertTrue(any(c[:3] == ("comments", "add", "t-1") and c[3].startswith("Engine paused:") and "paused: no lane for write until" in c[3]
                            for c in self.bd_calls))

    def test_a_lane_that_is_out_with_no_reset_time_pauses_at_once(self):
        out = te.stop("rate_limited", say="lane_out: ZAI", lane="ZAI")
        rc, s = self.run_engine({"plan": [PLAN], "write": [out], "review": [CLEAN]})
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker"])
        self.assertTrue(any(c[:3] == ("comments", "add", "t-1") and c[3].startswith("Engine paused:") and "paused: no lane for write" in c[3] for c in self.bd_calls))

    def test_a_delegate_that_keeps_crashing_pauses_the_bead_and_asks_nobody(self):
        crash = fake_route.NO_ANSWER
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [crash, crash, crash]})
        self.assertNotEqual(rc, 0)
        self.assertTrue(self.eng.why.startswith("failed: delegate crashed 3 times on the review step"), self.eng.why)
        self.assertFalse(self.eng.asked)  # a machine fault: the bead stays open, labelled engine-fault, nobody is asked
        self.assertEqual(self.blocked, [])
        self.assertTrue(any(c[:3] == ("label", "add", "t-1") and c[3] == "engine-fault" for c in self.bd_calls), self.bd_calls)

    def test_a_run_again_answer_keeps_the_plan_and_is_no_amend(self):
        ask = dict(WRITE, question="Which format?")
        rc, _ = self.run_engine({"plan": [PLAN], "write": [ask]})
        self.assertEqual(rc, 2)
        path = tl.config_dir() / "asks" / "t-1.json"
        a = json.loads(path.read_text())
        path.write_text(json.dumps(dict(a, kind="stuck")))  # an over-budget or stuck ask, which has a Run again button
        with mock.patch.object(tl, "comments", return_value=[{"author": "denis", "text": "Run again."}]):
            rc, s = self.run_engine({"write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertNotIn("planner", [c[0] for c in s.calls])
        self.assertIn("only asks for a rerun", self.eng.log_path.read_text())
        for text in ("run-again", "Retry!", "re-run", "try again"):
            self.assertTrue(engine.RERUN_ANSWER.fullmatch(" ".join(text.lower().replace("-", " ").split()).strip(" .!")), text)
        for text in ("yes", "use option A", "run again with more budget", "continue", "go on", "resume"):
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
        other = Path(self.tmp.name) / "other-repo"
        (other / ".beads").mkdir(parents=True)
        (Path(self.wt) / ".beads").mkdir(exist_ok=True)
        for bead in ("b-open", "b-closed", "b-gone", "b-hidden"):
            (asks / ("%s.json" % bead)).write_text(json.dumps({"v": 1, "id": bead + "-1", "bead": bead, "status": "open", "kind": "stuck",
                                                                "repo": str(self.wt)}))
        (asks / "b-flaky.json").write_text(json.dumps({"v": 1, "id": "f-1", "bead": "b-flaky", "status": "open", "kind": "stuck",
                                                        "repo": str(other)}))  # its tracker fails: nothing is learned, the ask stays
        (asks / "b-norepo.json").write_text(json.dumps({"v": 1, "id": "n-1", "bead": "b-norepo", "status": "open", "kind": "stuck"}))
        (asks / "b-answered.json").write_text(json.dumps({"v": 1, "id": "x", "bead": "b-answered", "status": "answered"}))
        calls = []

        def fake_bd(*a, **k):
            calls.append((a, k.get("cwd")))
            if k.get("cwd") == str(other):
                return mock.Mock(returncode=1, stdout="", stderr="dolt: database not found")
            if a[0] == "show":  # absent from the list: only a bead bd really does not know is gone (a gate or wisp is hidden from lists)
                return (mock.Mock(returncode=0, stdout="[{}]", stderr="") if a[1] == "b-hidden"
                        else mock.Mock(returncode=1, stdout="", stderr="Error: no issue found matching %s" % a[1]))
            return mock.Mock(returncode=0, stderr="", stdout=json.dumps([{"id": "b-open", "status": "open"}, {"id": "b-closed", "status": "closed"}]))
        with mock.patch.object(tl, "bd", side_effect=fake_bd):
            closed = tl.close_stale_asks(every=0)
            self.assertEqual(sorted(closed), ["b-closed", "b-gone"])
            self.assertEqual(tl.close_stale_asks(), [])  # throttled
        self.assertEqual([c[0][0] for c in calls].count("list"), 2)  # one list per repo, not one read per ask (a show only for an absent id)
        state = {b: json.loads((asks / ("%s.json" % b)).read_text())["status"] for b in ("b-open", "b-closed", "b-gone", "b-hidden", "b-flaky", "b-answered", "b-norepo")}
        self.assertEqual(state, {"b-hidden": "open", "b-open": "open", "b-closed": "closed", "b-gone": "closed", "b-flaky": "open", "b-answered": "answered",
                                 "b-norepo": "open"})  # no repo recorded: which tracker to ask is unknown, the ask stays

class PlanTimeout(StagesTest):
    """tl-btt: a check that sets a limit above the engine's check limit is sent back at plan time."""

    @te.no_repo
    def test_the_limits_a_check_sets_for_itself_are_read_in_minutes(self):
        for check, minutes in (("just play --timeout_ms 2400000", 40.0), ("tool -testTimeoutMs=1800000", 30.0), ("run --timeout=40m", 40.0),
                               ("run --timeout 2h", 120.0), ("timeout 2400 python3 t.py", 40.0), ("x --timeout-min 45", 45.0),
                               ("x timeout_seconds=600", 10.0), ("x --timeout 90", 1.5)):
            got = [m for m, _ in lint.own_timeouts(check)]
            self.assertEqual(got, [minutes], check)
        for check in ("pytest tests", "grep -q timeout config.yaml", "x --timeouts 5", "x --no-timeout", "x timeout_msg"):
            self.assertEqual(lint.own_timeouts(check), [], check)

    @te.no_repo
    def test_yxbb3s_play_test_of_40_minutes_under_a_30_minute_cap_is_found(self):
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=["just unity-play-tests --timeout_ms 2400000", HAS_F])])
        got = lint.timeout_problems(plan, 30)
        self.assertEqual(len(got), 1)
        self.assertIn("= 40 min, above the engine's check limit of 30 min", got[0])
        self.assertEqual(lint.timeout_problems(plan, 40), [])  # equal is fine
        self.assertEqual(lint.timeout_problems(plan, 60), [])
        cases = dict(PLAN, cases=[{"criterion": "c", "check": "x --timeout 5400", "class": "test"}])
        self.assertEqual(len(lint.timeout_problems(cases, 60)), 1)  # cases are checks too

    def test_the_plan_goes_back_to_the_planner_once_with_the_reason(self):
        bad = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[HAS_F + " ; true --timeout_ms 2400000"])])
        rc, s = self.run_engine({"plan": [bad, PLAN], "write": [WRITE], "review": [CLEAN]}, check_timeout_min=30)
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["planner", "planner", "worker", "reviewer"])
        self.assertIn("above the engine's check limit of 30 min", s.prompts[1])

    def test_a_plan_inside_the_limit_is_not_sent_back(self):
        ok = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[HAS_F + " ; true --timeout_ms 600000"])])
        rc, s = self.run_engine({"plan": [ok], "write": [WRITE], "review": [CLEAN]}, check_timeout_min=30)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer"])


class ClaimPerBead(StagesTest):
    """tl-kwo: a claim is live when an engine runs that bead, not because the claiming actor's loop is alive."""

    def reclaim(self, bead, slots, running, hand_live=False):
        import loop
        with mock.patch.object(tl, "show", return_value=bead), mock.patch.object(tl, "slot_beads", return_value=slots), \
                mock.patch.object(tl, "live_actors", return_value={"tl-2be89f88"} if hand_live or slots else set()), \
                mock.patch.object(loop, "running", return_value=running), mock.patch.object(tl, "comments", return_value=[]), \
                mock.patch.object(tl, "bd", return_value=mock.Mock(returncode=0)):
            return engine.reclaim("o67g", str(self.wt))

    BEAD = {"id": "o67g", "status": "open", "assignee": "tl-2be89f88", "lease_expires_at": "2999-01-01T00:00:00Z", "dependencies": []}
    SLOT = {"id": "sl-5", "status": "in_progress", "assignee": "tl-2be89f88", "lease_expires_at": "2999-01-01T00:00:00Z",
            "metadata": {"held_bead": "fld.27.12"}, "title": "slot h s5"}

    def test_a_bead_the_loop_left_for_another_is_takeable(self):
        ok, why = self.reclaim(self.BEAD, [self.SLOT], {"fld.27.12": "s5"})
        self.assertTrue(ok, why)
        self.assertIn("released tl-2be89f88", why)

    def test_an_engine_running_the_bead_is_a_live_claim(self):
        ok, why = self.reclaim(self.BEAD, [self.SLOT], {"fld.27.12": "s5", "o67g": "s2"})
        self.assertFalse(ok)
        self.assertIn("a live claim", why)

    def test_the_loop_running_this_very_bead_keeps_its_claim(self):
        slot = dict(self.SLOT, metadata={"held_bead": "o67g"})
        ok, why = self.reclaim(self.BEAD, [slot], {})  # the slot says it, the engine is just starting
        self.assertFalse(ok)

    def test_a_session_working_by_hand_keeps_its_claim(self):
        ok, why = self.reclaim(self.BEAD, [], {}, hand_live=True)
        self.assertFalse(ok)
        self.assertIn("a live claim", why)

    def test_the_release_is_conditional_on_the_claim_just_read(self):
        import loop
        calls = []
        with mock.patch.object(tl, "show", return_value=self.BEAD), mock.patch.object(tl, "slot_beads", return_value=[self.SLOT]), \
                mock.patch.object(tl, "live_actors", return_value={"tl-2be89f88"}), mock.patch.object(loop, "running", return_value={}), \
                mock.patch.object(tl, "comments", return_value=[]), \
                mock.patch.object(tl, "bd", side_effect=lambda *a, **k: calls.append(a) or mock.Mock(returncode=0)):
            ok, why = engine.reclaim("o67g", str(self.wt))
        self.assertTrue(ok, why)
        self.assertEqual(calls[-1], ("update", "o67g", "--if-assignee", "tl-2be89f88", "--assignee", ""))

    def test_a_claim_that_changed_hands_meanwhile_is_not_taken(self):
        import loop
        with mock.patch.object(tl, "show", return_value=self.BEAD), mock.patch.object(tl, "slot_beads", return_value=[self.SLOT]), \
                mock.patch.object(tl, "live_actors", return_value={"tl-2be89f88"}), mock.patch.object(loop, "running", return_value={}), \
                mock.patch.object(tl, "comments", return_value=[]), mock.patch.object(tl, "bd", return_value=mock.Mock(returncode=1)):
            ok, why = engine.reclaim("o67g", str(self.wt))
        self.assertFalse(ok)
        self.assertIn("changed hands", why)

    def test_a_loop_that_pauses_a_bead_clears_its_assignee(self):
        late = te.stop("no_lane", at=engine.time.time() + 3600, family="openai", lane="OPENAI", say="no lane")
        rc, s = self.run_engine({"plan": [late]})
        self.assertTrue(self.eng.why.startswith("paused:"), self.eng.why)
        updates = [c for c in self.bd_calls if c[:2] == ("update", "t-1") and "--append-notes" not in c]
        self.assertTrue(updates and updates[-1][2:6] == ("--status", "open", "--assignee", ""), updates)
        self.assertTrue([c for c in self.bd_calls if c[:3] == ("comments", "add", "t-1") and c[3].startswith("Engine paused:")], self.bd_calls)


class FreshAside(StagesTest):
    """--fresh (lifesim-6pld): the old branch is kept as task/<id>-stale-<time> and the task starts again on the base."""

    def old_branch(self, commits=1):
        te.sh("git", "checkout", "-qb", "task/t-1", cwd=self.wt)
        for k in range(commits):
            (self.wt / ("old%d.txt" % k)).write_text("earlier work\n")
            te.sh("git", "add", "-A", cwd=self.wt)
            te.sh("git", "commit", "-qm", "wip %d" % k, cwd=self.wt)
        te.sh("git", "checkout", "-q", "-", cwd=self.wt)

    def branches(self):
        return self.eng.git("branch", "--list", "task/t-1*", "--format=%(refname:short)").split()

    def test_fresh_keeps_the_old_branch_aside_and_starts_on_the_base(self):
        self.old_branch(2)
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, fresh=True)
        self.assertEqual(rc, 0, self.blocked)
        text = self.eng.log_path.read_text()
        self.assertIn("--fresh: the old branch task/t-1 is kept as task/t-1-stale-", text)
        self.assertNotIn("git checkout -q task/t-1\n", text)  # the old branch was never checked out
        stale = [b for b in self.branches() if "-stale-" in b]
        self.assertEqual(len(stale), 1)
        kept = self.eng.git("ls-tree", "-r", "--name-only", stale[0]).split()
        self.assertIn("old1.txt", kept)  # the earlier work is there
        self.assertNotIn("old0.txt", self.eng.git("ls-tree", "-r", "--name-only", "origin/main").split())
        self.assertTrue(any("Fresh (engine)" in str(c) for c in self.bd_calls))

    def test_fresh_on_a_branch_with_no_work_of_its_own_just_starts_on_the_base(self):
        te.sh("git", "branch", "task/t-1", "HEAD", cwd=self.wt)
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, fresh=True)
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([b for b in self.branches() if "-stale-" in b], [])

    def test_without_fresh_the_old_branch_is_used_as_before(self):
        self.old_branch(1)
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual([b for b in self.branches() if "-stale-" in b], [])
        self.assertIn("git checkout -q task/t-1", self.eng.log_path.read_text())


if __name__ == "__main__":
    unittest.main()


class FollowUps(StagesTest):
    """tl-7y6.7.9: a follow-up is filed only when bd's create worked; lint sections are added once; a refused one is never 'filed'."""
    LO = {"title": "Rename x", "why": "found in passing"}
    LINT = "missing required sections for task: ## Acceptance Criteria, ## Touches"

    def lint_bd(self, always=False):
        def fake(*a, **kw):
            r = self.fake_bd(*a, **kw)
            if a[:1] == ("create",):
                body = a[a.index("--description") + 1] if "--description" in a else ""
                if always or not ("## Touches" in body and "## Acceptance Criteria" in body):
                    return mock.Mock(returncode=1, stdout="", stderr=self.LINT)
            return r
        return fake

    def reflect_comments(self):
        return [c[3] for c in self.bd_calls if c[:2] == ("comments", "add") and c[3].startswith("Reflect (engine)")]

    def test_a_follow_up_bd_lint_refuses_is_filed_again_with_the_sections_it_names(self):
        with mock.patch.object(tl, "bd", side_effect=self.lint_bd()):
            rc, _ = self.run_engine({"plan": [dict(PLAN, leftovers=[self.LO])], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        creates = [c for c in self.bd_calls if c[:2] == ("create", "Rename x")]
        self.assertEqual(len(creates), 2)
        body = creates[1][creates[1].index("--description") + 1]
        self.assertIn("found in passing", body)
        self.assertIn("## Touches", body)
        self.assertIn("## Acceptance Criteria", body)
        self.assertIn("filed=1", self.reflect_comments()[0])
        self.assertNotIn("unfiled", self.reflect_comments()[0])

    def test_a_follow_up_bd_will_not_take_is_reported_unfiled_the_run_still_lands(self):
        with mock.patch.object(tl, "bd", side_effect=self.lint_bd(always=True)):
            rc, _ = self.run_engine({"plan": [dict(PLAN, leftovers=[self.LO])], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(self.eng.filed, [])
        self.assertIn("filed=0", self.reflect_comments()[0])
        self.assertIn("unfiled=1", self.reflect_comments()[0])
        self.assertTrue(any(c[:2] == ("comments", "add") and c[3].startswith("Follow-up (engine)") and "Rename x" in c[3]
                            for c in self.bd_calls))
        self.assertEqual(len([c for c in self.bd_calls if c[:2] == ("create", "Rename x")]), 2)  # one retry, no more

    @te.no_repo
    def test_lint_sections_reads_the_headings_bd_names(self):
        self.assertEqual(engine.lint_sections("Error: missing required sections for bug: ## Steps to Reproduce, ## Acceptance Criteria"),
                         ["Steps to Reproduce", "Acceptance Criteria"])
        self.assertEqual(engine.lint_sections("some other failure"), [])
        body = engine.with_sections("why\n\n## Touches\nx.py", ["Touches", "Acceptance Criteria"], "t-1")
        self.assertEqual(body.count("## Touches"), 1)
        self.assertIn("## Acceptance Criteria", body)
