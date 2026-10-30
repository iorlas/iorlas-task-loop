"""tl-bxk.13: stage handoffs (docs/design/stages.md). Reuses test_engine's harness without re-running its tests."""
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from typing import Any, ClassVar, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import engine_case as te
from support import (
    procsim,
)
from support.builders import make_engine
from support.checkpoints import put_ck, read_ck
from support.checks import ck, res, typed
from support.engine_case import BEAD, CLEAN, FALSE, HAS_F, PLAN, WRITE, engine, lint
from support.engine_locks import put_lock
from support.fakes import as_bead, must_bead
from support.narrow import must

from taskloop.adapters import ident, pidcheck
from taskloop.adapters import procs as sproc
from taskloop.adapters.check_probe import PathProbe
from taskloop.app.checks import evidence as check_evidence
from taskloop.app.wire import slots as wslots
from taskloop.app.write.handoff import HANDOFF_CAP
from taskloop.contracts.answers import IRREVERSIBLE
from taskloop.contracts.argv import argv_of
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.ids import BeadId, CheckId
from taskloop.contracts.plancheck import adhoc
from taskloop.domain.checks import planref
from taskloop.domain.plan.matchers import AcceptanceText


class StagesTest(te.EngineTest):
    def probe(self):
        return PathProbe(cast(Any, self).wt, sproc.current_env())

    wt: Path

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
        rc, _s = self.run_engine({"plan": [dict(PLAN, stages=[]), dict(PLAN, stages=[])]})  # sent back once (tl-wjj), still empty
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
        rc, _s = self.run_engine({"plan": [plan]})
        self.assertNotEqual(rc, 0)
        self.assertEqual(self.blocked, [])
        self.assertIn("no stages", te.EngineTest.said(self))
        self.assertEqual(self.created(), [])

    @te.no_repo
    def test_done_when_counts_as_acceptance_criteria(self):
        def has(b):
            return AcceptanceText.present(must_bead(b))
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

    LONG = FALSE + " padding-so-the-check-is-long-enough-to-shorten"

    @te.no_repo
    def test_flagged_why_matches_loose_names(self):
        c = res("grep -qE 'name=\"GameLogTests\"[^>]*result=\"Passed\"' client/Logs/unity-tests.xml", id="x")
        why = check_evidence.flagged_why
        self.assertEqual(why(c, [{"cmd": c.cmd, "why": "a"}]), "a")
        self.assertEqual(
            why(c, [{"cmd": 'grep   -qE \'name="GameLogTests"[^>]*result="Passed"\'\nclient/Logs/unity-tests.xml', "why": "b"}]), "b"
        )
        self.assertEqual(why(c, [{"cmd": "grep -qE 'name=\"GameLogTests\"...unity-tests.xml", "why": "c"}]), "c")
        self.assertEqual(why(c, [{"cmd": "`" + c.cmd + "`", "why": "d"}]), "d")
        self.assertEqual(why(c.replace(id="unity-tests"), [{"cmd": "unity-tests", "why": "e"}]), "e")
        self.assertEqual(why(c, [{"cmd": "grep -qE 'other'...nothing.xml", "why": "f"}]), "")
        self.assertEqual(why(c, [{"cmd": "grep", "why": "g"}]), "")  # too short to say which check
        self.assertEqual(why(c, []), "")
        mine = res("python3 -m unittest discover -s tests -p 'test_a.py'", id="u")
        self.assertEqual(why(mine, [{"cmd": "python3 -m unittest discover -s tests", "why": "h"}]), "")  # another, shorter check

    def test_a_shortened_bad_check_replans_at_once(self):
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[self.LONG])])
        cmd = plan["stages"][0]["checks"][0]
        flag = dict(WRITE, bad_checks=[{"cmd": cmd[:25] + "..." + cmd[-12:], "why": "cannot pass"}])
        _rc, s = self.run_engine({"plan": [plan, PLAN], "write": [flag, WRITE], "review": [CLEAN]})
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "planner", "worker", "reviewer"])


class Deferred(StagesTest):
    """13.1: the reviewer is told what the plan set aside; 'file beads' is an engine step; an owner item with a bead lands."""

    LEFT: ClassVar[Any] = [{"title": "File the table and chair beads", "why": "the sheet lists them; the engine files them"}]

    def eng_(self, **attrs):
        return make_engine(self.wt, store=self.store, attrs=attrs)

    def test_the_review_prompt_lists_what_the_plan_set_aside(self):
        rc, s = self.run_engine({"plan": [dict(PLAN, leftovers=self.LEFT)], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        review = s.prompts[2]
        self.assertIn("Already set aside", review)
        self.assertIn("File the table and chair beads", review)
        self.assertIn("Never list one as unmet", review)

    def test_no_set_aside_section_without_leftovers(self):
        _rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertNotIn("Already set aside", s.prompts[2])

    def test_filing_beads_in_any_wording_is_an_engine_step_when_there_are_leftovers(self):
        e = self.eng_()
        for w in ("File beads for the table, chairs and sink", "Follow-up beads for each object are to be filed",
                  "The nine beads are not filed", "Create a bead per object", "file follow-up tasks"):
            self.assertFalse(e.routing.engine_does(w), w + " (no leftovers yet)")
        e.leftovers = [{"title": "x", "why": "y"}]
        for w in ("File beads for the table, chairs and sink", "Follow-up beads for each object are to be filed",
                  "The nine beads are not filed", "Create a bead per object", "file follow-up tasks"):
            self.assertTrue(e.routing.engine_does(w), w)
        self.assertFalse(e.routing.engine_does("The beads cover all nine objects"))  # a claim about the result goes to the verifier

    def test_an_owner_item_with_an_owner_review_bead_in_the_leftovers_lands_unverified(self):
        e = self.eng_(leftovers=[{"title": "Owner review of the retuned knob values and placeholder art", "why": "iqad"}])
        item = {"what": "Owner sign-off on the retuned knob values and the placeholder art", "kind": "owner_decision"}
        self.assertTrue(e.routing.backed_by_leftover(item["what"]))
        self.assertEqual(e.routing.engine_steps([item]), [])
        self.assertEqual([u["what"] for u in e.unverified], [item["what"]])
        other = {"what": "Whether the storyteller preset is the intended default", "kind": "owner_decision"}
        self.assertEqual(e.routing.engine_steps([other]), [other])
        e.leftovers = [{"title": "Tune the knob values and placeholder art", "why": "later"}]  # not an owner bead
        self.assertFalse(e.routing.backed_by_leftover(item["what"]))
        e.leftovers = [{"title": "Owner review of retry timeout defaults", "why": "unrelated"}]
        self.assertFalse(e.routing.backed_by_leftover(item["what"]))

    def test_beads_in_other_sentences_are_not_the_filing_step(self):
        e = self.eng_(leftovers=[{"title": "x", "why": "y"}])
        for w in ("The config file lists the bead ids", "No open beads remain in the epic", "Open the bead and read it"):
            self.assertFalse(e.routing.engine_does(w), w)


class Scope(StagesTest):
    """13.5: a checkable note outside the done-when is a follow-up, not a verify gap."""

    def test_an_item_outside_the_done_when_is_filed_not_verified(self):
        e = make_engine(self.wt, store=self.store, attrs={
            "scope": "Acceptance Criteria\n- the soak passes with three lifers across five seeds",
            "plan_data": dict(PLAN),
            })
        inside = {"what": "the soak holds with three lifers on seed 4", "kind": "checkable"}
        outside = {"what": "Sit To Stand and Laying Sleeping poses were not probed", "kind": "checkable"}
        taste = {"what": "Sit To Stand and Laying Sleeping poses look right", "kind": "taste"}
        self.assertEqual(e.cases.out_of_scope([inside, outside, taste]), [inside, taste])
        self.assertEqual(len(e.leftovers), 1)
        self.assertIn("Sit To Stand", e.leftovers[0]["title"])

    def test_with_no_acceptance_text_nothing_moves(self):
        e = engine.Engine(BeadId("t-1"), str(self.wt), wslots.load_cfg(str(self.wt)), store=self.store)
        item = {"what": "Sit To Stand was not probed", "kind": "checkable"}
        self.assertEqual(e.cases.out_of_scope([item]), [item])
        self.assertEqual(e.leftovers, [])

    def test_non_latin_text_is_compared_and_a_note_is_filed_once(self):
        e = make_engine(self.wt, store=self.store, attrs={"scope": "Done when: суп варится три минуты", "plan_data": dict(PLAN)})
        inside = {"what": "суп варится три минуты на плите", "kind": "checkable"}
        outside = {"what": "wallpaper colour not probed", "kind": "checkable"}
        self.assertEqual(e.cases.out_of_scope([inside, outside]), [inside])
        e.cases.out_of_scope([outside])
        self.assertEqual(len(e.leftovers), 1)

    @te.no_repo
    def test_acceptance_text_reads_the_field_and_the_description_from_the_heading(self):
        txt = AcceptanceText.text(must_bead({"acceptance_criteria": "A works", "description": "Intro.\n## Done when\n- B works\n"}))
        self.assertIn("A works", txt)
        self.assertIn("B works", txt)
        self.assertNotIn("Intro", txt)

    def test_a_note_outside_the_done_when_does_not_stop_the_run(self):
        with self.store.stub(show=dict(BEAD, acceptance_criteria="f.txt exists and holds data")):
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
        _rc, s = self.run_engine({"plan": [plan, PLAN], "write": [flag, WRITE], "review": [CLEAN]})
        amend = s.prompts[2]
        self.assertIn("<rounds>", amend)
        self.assertIn("tried the rename", amend)
        self.assertIn("bad_checks", amend)
        handoff = json.loads((self.eng.run_dir / "handoff.json").read_text())
        self.assertEqual(handoff["rounds"][0]["kind"], "bad_checks")

    def test_a_low_finding_is_not_listed_again_by_the_next_review(self):
        first = dict(CLEAN, findings=[te.finding("high"), dict(te.finding("low"), fix="rename the helper")])
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, WRITE], "review": [first, CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        reviews = [p for p, c in zip(s.prompts, s.calls, strict=False) if c[0] == "reviewer"]
        self.assertNotIn("already noted", reviews[0])
        self.assertIn("already noted", reviews[1])
        self.assertIn("rename the helper", reviews[1])

    def test_the_rounds_text_keeps_the_newest_within_its_cap(self):
        e = engine.Engine(BeadId("t-1"), str(self.wt), wslots.load_cfg(str(self.wt)), store=self.store)
        for k in range(8):
            e.hand.note_round("stage 1/1", k + 1, "review", "w" * 300, ["x" * 200])
        text = e.hand.rounds_text()
        self.assertLessEqual(len(text), HANDOFF_CAP + 700)
        self.assertIn("round 8", text)
        self.assertNotIn("round 1,", text)

    TWO: ClassVar[Any] = dict(PLAN, stages=[PLAN["stages"][0], dict(PLAN["stages"][0], goal="add g")])

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
        writes = [(p, c) for p, c in zip(s.prompts, s.calls, strict=False) if c[0] == "worker"]
        self.assertIsNone(writes[1][1][1])
        self.assertIn("fresh session for the next one", writes[1][0])
        self.assertIn("add f", writes[1][0])  # the accepted stage's goal

    def test_a_smaller_session_goes_on_and_the_limit_is_the_repos_to_set(self):
        _rc, s = self.boundary(90)
        self.assertEqual([c[1] for c in s.calls if c[0] == "worker"][1], "ref-write")
        _rc, s = self.boundary(120, write_fresh_above_k=0)  # 0 is never, for the stage boundary too
        self.assertEqual([c[1] for c in s.calls if c[0] == "worker"][1], "ref-write")
        _rc, s = self.boundary(120, write_fresh_stage_k=0)
        self.assertEqual([c[1] for c in s.calls if c[0] == "worker"][1], "ref-write")


class Anchors(StagesTest):
    """Plan v2: a plan that changes an existing file without an anchor for it goes back to the planner once."""

    def test_an_unanchored_existing_file_sends_the_plan_back_once_and_the_anchor_reaches_the_writer(self):
        bare = dict(PLAN, stages=[dict(PLAN["stages"][0], files=["a.txt"])])  # a.txt is tracked in the fixture repo
        good = dict(bare, stages=[dict(bare["stages"][0], anchors=[{"path": "a.txt", "lines": "1-3", "symbol": "top", "why": "the file"}])])
        _rc, s = self.run_engine({"plan": [bare, good], "write": [WRITE, WRITE], "review": [CLEAN]})
        self.assertEqual([c[0] for c in s.calls][:3], ["planner", "planner", "worker"])  # sent back once, then written
        self.assertIn("name no anchor", s.prompts[1])
        self.assertIn("- a.txt:1-3 top -- the file", s.prompts[2])


class SharedNotes(StagesTest):
    """13.8: the tasks of a repo share what is running, what landed and which tests are flaky."""

    def eng_(self, **attrs):
        return make_engine(self.wt, store=self.store, attrs=attrs)

    def test_flakes_are_kept_per_repo_once_and_listed_for_the_next_prompts(self):
        e = self.eng_()
        self.assertEqual(e.shared.known_flakes(), [])
        e.shared.add_flakes([{"test": "SoakTests.HeapGrowth", "note": "process-wide heap check"}, {"test": " ", "note": "x"}])
        e.shared.add_flakes([{"test": "SoakTests.HeapGrowth", "note": "again"}])
        self.assertEqual([f["test"] for f in e.shared.known_flakes()], ["SoakTests.HeapGrowth"])
        self.assertIn("SoakTests.HeapGrowth", e.shared.flakes_text())
        self.assertIn("do not build a new isolation", e.shared.flakes_text())
        self.assertIn("SoakTests.HeapGrowth", self.eng_().shared.shared_text())  # another task of the repo reads the same file
        e.shared.add_flakes(["not a dict", {"test": "A"}, {"test": "B"}, {"test": "C"}, {"test": "D"}])
        self.assertEqual([f["test"] for f in e.shared.known_flakes()][1:], ["A", "B", "C"])  # three a write
        data = json.loads(e.shared.shared_path().read_text())
        data["flakes"][0]["t"] = 1  # a writer's word lapses
        e.shared.shared_path().write_text(json.dumps(data))
        self.assertNotIn("SoakTests.HeapGrowth", [f["test"] for f in e.shared.known_flakes()])

    def test_a_flake_entry_without_a_time_has_lapsed(self):
        e = self.eng_()
        e.shared.add_flakes([{"test": "Old.Test"}, {"test": "Fresh.Test"}])
        data = json.loads(e.shared.shared_path().read_text())
        del data["flakes"][0]["t"]
        e.shared.shared_path().write_text(json.dumps(data))
        self.assertEqual([f["test"] for f in e.shared.known_flakes()], ["Fresh.Test"])

    def test_a_writer_that_reports_a_flake_tells_the_next_prompts(self):
        flake = dict(WRITE, flakes=[{"test": "SoakTests.HeapGrowth", "note": "failed on the untouched base"}])
        rc, s = self.run_engine({"plan": [PLAN], "write": [flake], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertNotIn("Known flaky", s.prompts[1])
        self.assertEqual([f["test"] for f in self.eng.shared.known_flakes()], ["SoakTests.HeapGrowth"])
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertIn("SoakTests.HeapGrowth", s.prompts[0])  # the planner
        self.assertIn("SoakTests.HeapGrowth", s.prompts[1])  # the writer's first prompt
        self.assertIn("SoakTests.HeapGrowth", s.prompts[2])  # the reviewer

    def test_what_landed_since_the_branch_left_the_base_is_listed(self):
        te.sh("git", "checkout", "-qb", "task/t-1", cwd=self.wt)
        self.commit_base_cfg({"gate": ""})
        te.sh("git", "fetch", "-q", "origin", cwd=self.wt)
        self.assertEqual(self.eng_().shared.landed_since(), ["engine config"])

    def test_a_task_running_in_another_worktree_is_listed_with_its_files(self):
        other = Path(self.tmp.name, "wt2")
        te.sh("git", "worktree", "add", "-q", "--detach", str(other), cwd=self.wt)
        put_lock(str(other), {"pid": os.getpid(), "start": pidcheck.proc_start(os.getpid()), "bead": "t-2"})
        put_ck(self.eng_(), "t-2", plan_data={"summary": "tune the soak", "stages": [
            {"goal": "g", "files": ["SoakTests.cs", "justfile"], "checks": [], "hard": False}]})
        got = self.eng_().shared.siblings()
        self.assertEqual(got, [("t-2", "tune the soak", ["SoakTests.cs", "justfile"])])
        self.assertIn("t-2: tune the soak [files: SoakTests.cs, justfile]", self.eng_().shared.shared_text())
        put_lock(str(other), {"pid": 99999999, "start": "", "bead": "t-2"})  # dead
        self.assertEqual(self.eng_().shared.siblings(), [])

    def test_a_branch_behind_the_base_is_rebased_before_it_is_planned(self):
        te.sh("git", "checkout", "-qb", "task/t-1", cwd=self.wt)
        (self.wt / "g.txt").write_text("g\n")
        te.sh("git", "add", "-A", cwd=self.wt)
        te.sh("git", "commit", "-qm", "earlier work", cwd=self.wt)
        te.sh("git", "checkout", "-q", "-", cwd=self.wt)
        self.commit_base_cfg({"gate": ""})  # main moves on
        rc, _s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertIn("rebased the task branch onto the latest origin/main", self.eng.log_path.read_text())
        out = subprocess.run(["git", "log", "--format=%s", "origin/main"], cwd=self.wt, capture_output=True, text=True, check=False).stdout
        self.assertIn("engine config", out)
        self.assertIn("Add f (t-1)", out)

    def test_the_rebase_moves_the_checkpoints_head_with_it(self):
        te.sh("git", "checkout", "-qb", "task/t-1", cwd=self.wt)
        (self.wt / "g.txt").write_text("g\n")
        te.sh("git", "add", "-A", cwd=self.wt)
        te.sh("git", "commit", "-qm", "earlier work", cwd=self.wt)
        e = self.eng_()
        old = e.git("rev-parse", "HEAD")
        put_ck(e, head=old)
        self.commit_base_cfg({"gate": ""})
        te.sh("git", "fetch", "-q", "origin", cwd=self.wt)
        e.rebase.onto_base()
        new = e.git("rev-parse", "HEAD")
        self.assertNotEqual(old, new)
        self.assertEqual(read_ck(e).head, new)


class Fdyo(StagesTest):
    """13.11-13.14, from the lifesim-fdyo run (15.7M tokens): checks only the engine can pass, a late fresh writer, a check that
    cannot run, slow tests before a fast verdict."""

    PASS = "true"

    def test_a_check_red_two_rounds_running_tells_the_writer_it_may_flag_it(self):
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[FALSE])])
        _rc, s = self.run_engine({"plan": [plan], "write": [WRITE, WRITE, WRITE], "review": [CLEAN]}, max_check_tries=3)
        writes = [p for p, c in zip(s.prompts, s.calls, strict=False) if c[0] == "worker"]
        self.assertNotIn("failed in the last round too", writes[1])  # red for the first time
        self.assertIn("failed in the last round too", writes[2])
        self.assertIn("list it in bad_checks", writes[2])

    @te.no_repo
    def test_a_codex_session_is_not_resumed_above_100k_inside_a_stage(self):
        self.assertEqual(EngineConfig().write_fresh_above_k, {"claude": 150, "codex": 100, "xai": 100})

    def test_python_isolated_mode_with_a_repo_module_is_sent_back(self):
        (self.wt / "tools" / "tests").mkdir(parents=True)
        (self.wt / "tools" / "tests" / "test_x.py").write_text("x = 1\n")
        te.sh("git", "add", "-A", cwd=self.wt)
        te.sh("git", "commit", "-qm", "tools", cwd=self.wt)
        te.sh("git", "push", "-q", "origin", "HEAD:main", cwd=self.wt)
        bad = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=["python3 -I -m unittest tools.tests.test_x"])])
        self.assertEqual(len(lint.dry_check(typed(bad), self.probe())), 1)
        self.assertIn("python -I removes the working directory", lint.dry_check(typed(bad), self.probe())[0])
        for ok in ("python3 -I -m unittest discover -s tools/tests -p 'test_x.py'", "python3 -m unittest tools.tests.test_x",
                   "python3 -I -m json.tool f.json", "python3 -I -c 'import tools.x'"):
            self.assertEqual(lint.dry_check(typed(dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[ok])])), self.probe()), [], ok)
        _rc, s = self.run_engine({"plan": [bad, PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual([c[0] for c in s.calls], ["planner", "planner", "worker", "reviewer"])
        self.assertIn("python -I removes the working directory", s.prompts[1])

    def test_after_a_round_red_only_in_acceptance_the_fast_group_runs_before_the_slow_tests(self):
        eng = self.checks_engine(checks=[{"id": "slow", "cmd": self.PASS, "group": "tests"}])
        st = {"checks": ck([FALSE]), "files": []}
        first = eng.run_checks(st, "s")
        self.assertEqual([(c.group, c.status) for c in first], [("tests", "passed"), ("acceptance", "failed")])
        again = eng.run_checks(st, "s", acceptance_first=True)
        self.assertEqual([(c.group, c.status) for c in again], [("acceptance", "failed"), ("tests", "skipped")])
        self.assertIn("acceptance failed first", again[1].why)

    def test_the_reorder_is_off_when_an_acceptance_check_reads_a_repo_checks_log(self):
        eng = self.checks_engine(checks=[{"id": "slow", "cmd": self.PASS, "group": "tests"}])
        read = adhoc(procsim.fake('grep -q . "$TL_CHECK_LOG_SLOW" || true', procsim.exits(0)), (CheckId("slow"),))
        st = {"checks": ck([read]), "files": []}
        res = eng.run_checks(st, "s", acceptance_first=True)
        self.assertEqual([c.group for c in res], ["tests", "acceptance"])

    def test_a_stage_whose_acceptance_check_was_red_runs_acceptance_first_the_next_round(self):
        flaky = te.EngineTest.RED_ONCE
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[flaky])])
        rc, _s = self.run_engine({"plan": [plan], "write": [WRITE, WRITE], "review": [CLEAN]},
                                checks=[{"id": "slow", "cmd": self.PASS, "group": "tests"}])
        self.assertEqual(rc, 0, self.blocked)
        rounds = [json.loads(ln) for ln in self.eng.log_path.read_text().splitlines() if '"kind": "checks"' in ln]
        self.assertEqual([[i["group"] for i in r["run"]["results"]] for r in rounds], [["tests", "acceptance"], ["acceptance", "tests"]])

    def test_acceptance_first_is_used_once_then_the_normal_order_returns(self):
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[FALSE])])
        _rc, _s = self.run_engine({"plan": [plan], "write": [WRITE] * 4, "review": [CLEAN]}, max_check_tries=4, max_same_red=0,
                                checks=[{"id": "slow", "cmd": self.PASS, "group": "tests"}])
        rounds = [json.loads(ln) for ln in self.eng.log_path.read_text().splitlines() if '"kind": "checks"' in ln]
        self.assertEqual([r["run"]["results"][0]["group"] for r in rounds], ["tests", "acceptance", "tests", "acceptance"])

    def test_a_repo_check_red_twice_is_not_offered_to_bad_checks(self):
        _rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE] * 3, "review": [CLEAN]}, max_check_tries=3,
                                checks=[{"id": "repo-red", "cmd": FALSE, "group": "tests"}])
        writes = [p for p, c in zip(s.prompts, s.calls, strict=False) if c[0] == "worker"]
        self.assertTrue(len(writes) >= 3)
        self.assertNotIn("failed in the last round too", writes[2])

    def test_a_wall_hit_parks_at_once_with_no_second_write_and_no_retry(self):
        rc, s = self.run_engine(
            {"plan": [PLAN], "write": [WRITE, WRITE, WRITE], "review": [CLEAN]},
            checks=[{"id": "slow", "cmd": procsim.fake("sleep-60", procsim.takes(60)), "group": "tests", "wall_min": 0.01, "retry": 2}],
        )
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker"])  # one write, no fix task, no review
        self.assertNotEqual(rc, 0)
        eng = cast(Any, self).eng
        res = eng.result()
        self.assertEqual(res.outcome, "parked")
        self.assertIn("check slow timed out after 0.01 min (wall_min=0.01)", res.why)
        ends = [json.loads(x) for x in eng.log_path.read_text().splitlines() if '"kind": "check_end"' in x]
        self.assertEqual([(e["exit"], e["wall_hit"], e["tries"]) for e in ends if e["exit"] not in (None, 0)], [(124, True, 1)])


class Executable(StagesTest):
    """tl-bxk.13.16.2: a plan check must be able to start; an accepted stage's promised files must exist on resume."""

    def test_a_sentence_is_not_a_command(self):
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=["After building the current player: python3 tools/x.py", HAS_F])])
        errs = lint.dry_check(typed(plan), self.probe())
        self.assertEqual(len(errs), 1)
        self.assertIn("`After` is not an executable here", errs[0])

    def problems(self, cmd, probe=None, **kw):
        return lint.command_problems(argv_of(cmd), probe or self.probe(), **kw)

    def test_real_commands_pass_the_word_check(self):
        for ok in ("grep -q x a.txt", "env FOO=1 git status", "git status --short", "python3 -c 'a;b'", te.PY + " -c 'pass'"):
            self.assertEqual(self.problems(ok), [], ok)


    def test_valid_checks_the_word_check_must_not_block(self):
        probe = self.probe()
        for tool in ("make", "npm"):  # tools a dev machine has; this test is about the grammar, not about what is installed
            probe.words[tool] = (True, time.time())
        for ok in ("env -i PATH=x git --version", "make", "node_modules/.bin/jest", "~/bin/foo", ".venv/bin/python -c pass"):
            self.assertEqual(self.problems(ok, probe), [], ok)


    def test_a_missing_script_is_found_unless_a_stage_makes_it(self):
        check = "./tools/probe.sh --all"
        plan = typed(dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[check])]))
        self.assertIn("is not a file of this tree", lint.dry_check(plan, self.probe())[0])
        plan = typed(dict(PLAN, stages=[dict(PLAN["stages"][0], files=["tools/probe.sh"], checks=[check])]))
        self.assertEqual([e for e in lint.dry_check(plan, self.probe()) if "not a file" in e], [])

    def test_the_plan_with_a_sentence_goes_back_once(self):
        bad = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=["Confirm that f exists", HAS_F])])
        _rc, s = self.run_engine({"plan": [bad, PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual([c[0] for c in s.calls], ["planner", "planner", "worker", "reviewer"])
        self.assertIn("`Confirm` is not an executable here", s.prompts[1])

    PATH1 = ".task/t-1/evidence/sleeper-on-bed.txt"

    def writes_path1(self, cwd, env):
        (cwd / self.PATH1).parent.mkdir(parents=True, exist_ok=True)
        (cwd / self.PATH1).write_text("ok")
        return 0, ""

    def two_stage(self):
        return dict(
            PLAN,
            stages=[
                dict(
                    PLAN["stages"][0],
                    goal="stage one",
                    checks=ck([procsim.fake(f"writes {self.PATH1}", self.writes_path1), HAS_F]),
                ),
                dict(PLAN["stages"][0], goal="stage two", checks=ck([f"test -s {self.PATH1}"])),
            ],
        )

    def test_a_file_an_accepted_stage_promised_and_a_later_check_reads(self):
        e = engine.Engine(BeadId("t-1"), str(self.wt), wslots.load_cfg(str(self.wt)), store=self.store)
        plan = self.two_stage()
        self.assertEqual(e.cases.promised_missing(plan, 1), 0)  # stage 1 is accepted, the file is gone, stage 2 reads it
        Path(self.wt, self.PATH1).parent.mkdir(parents=True, exist_ok=True)
        Path(self.wt, self.PATH1).write_text("ok\n")
        self.assertIsNone(e.cases.promised_missing(plan, 1))
        Path(self.wt, self.PATH1).unlink()
        self.assertIsNone(e.cases.promised_missing(plan, 0))  # nothing accepted yet

    def test_a_replanned_runs_goals_survive_the_stage_that_runs_again(self):
        e = engine.Engine(BeadId("t-1"), str(self.wt), wslots.load_cfg(str(self.wt)), store=self.store)
        e.tree.reset(as_bead(BEAD))
        e.plan_data = self.two_stage()
        e.done, e.accepted = ["an earlier plan's goal", "stage one"], [0]
        e.checkpoints.save(stage=1, rounds=0, n=0, feedback="", step="write")
        again = engine.Engine(BeadId("t-1"), str(self.wt), wslots.load_cfg(str(self.wt)), store=self.store)
        again.tree.reset(as_bead(BEAD))
        again.resume.point()
        self.assertEqual(again.done, ["an earlier plan's goal"])

    def test_a_resume_runs_the_stage_again_when_its_file_is_gone(self):
        e = engine.Engine(BeadId("t-1"), str(self.wt), wslots.load_cfg(str(self.wt)), store=self.store)
        e.tree.reset(as_bead(BEAD))
        e.plan_data = self.two_stage()
        e.done, e.accepted = ["stage one"], [0]
        e.checkpoints.save(stage=1, rounds=0, n=0, feedback="", step="write")
        again = engine.Engine(BeadId("t-1"), str(self.wt), wslots.load_cfg(str(self.wt)), store=self.store)
        again.tree.reset(as_bead(BEAD))
        _plan, i, state = again.resume.point()
        self.assertEqual((i, state, again.accepted, again.done), (0, None, [], []))
        self.assertIn("a file stage 1 promised is missing", again.log_path.read_text())
        Path(self.wt, self.PATH1).parent.mkdir(parents=True, exist_ok=True)
        Path(self.wt, self.PATH1).write_text("ok\n")
        third = engine.Engine(BeadId("t-1"), str(self.wt), wslots.load_cfg(str(self.wt)), store=self.store)
        third.tree.reset(as_bead(BEAD))
        self.assertEqual(third.resume.point()[1], 1)  # the file is there: stage 2 goes on


class Ledger(StagesTest):
    eng: Any
    """tl-bxk.13.16.1: the plan says how each criterion is proved; review and verify go by it, not by the wording of an item."""

    LEFT: ClassVar[Any] = [{"title": "Import the chosen prefabs and add object rows", "why": "next bead"}]
    FILE: ClassVar[Any] = {"criterion": "Record the plan's follow-up issues about stale layer prose and bead wording", "check": "",
            "proved_by": "engine_step", "via": "file_beads"}
    DEFER: ClassVar[Any] = {"criterion": "A follow-up bead imports the chosen prefabs and adds object rows", "check": "",
             "proved_by": "leftover", "via": "Import the chosen prefabs and add object rows"}

    def plan(self, **kw):
        return typed(dict(PLAN, cases=[self.FILE, self.DEFER, {"criterion": "f exists", "check": HAS_F, "proved_by": "check"}],
                          leftovers=self.LEFT, **kw))

    def test_the_review_is_told_what_the_engine_does_and_what_is_deferred(self):
        _rc, s = self.run_engine({"plan": [self.plan()], "write": [WRITE], "review": [CLEAN]})
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
        self.assertIn("unmet item dropped", self.eng.log_path.read_text())

    def test_a_claim_about_the_code_that_shares_words_with_a_deferred_item_is_not_that_item(self):
        e = make_engine(self.wt, store=self.store, attrs={
            "plan_data": dict(PLAN, leftovers=[{"title": "Add tests for parser edge cases", "why": "later"}]),
            })
        self.assertEqual(e.routing.ledger_route("parser edge cases are not handled"), "")
        self.assertEqual(e.routing.ledger_route("The parser does not handle edge cases such as empty input or nested quotes"), "")
        self.assertEqual(e.routing.ledger_route("Add tests for the parser edge cases"), "leftover")
        self.assertEqual(e.routing.ledger_route("A follow-up bead for tests of parser edge cases is not filed"), "leftover")

    def test_a_defect_the_verifier_found_is_not_filed_away_by_the_ledger(self):
        e = make_engine(self.wt, store=self.store, attrs={"plan_data": self.plan(), "unchecked": []})
        what = "Import the chosen prefabs and add object rows"
        left = e.routing.route_left([{"what": what, "kind": "checkable", "why": "found wrong: the rows are missing"}])
        self.assertEqual([u["what"] for u in left], [what])  # still a defect: not unverified, not settled
        self.assertEqual(e.unverified, [])

    def test_an_unrelated_unmet_item_still_sends_the_stage_back(self):
        _rc, s = self.run_engine({"plan": [self.plan()], "write": [WRITE, WRITE],
                                 "review": [review_with(["The settings page does not save the volume"]), CLEAN]})
        self.assertEqual([c[0] for c in s.calls].count("worker"), 2)

    def test_unchecked_items_in_the_ledger_never_reach_the_verifier_or_the_writer(self):
        items = [
            {"what": "Record the plan's follow-up issues about stale layer prose and bead wording", "kind": "checkable", "source": ""},
            {
                "what": "The follow-up bead for importing the chosen prefabs and adding object rows exists",
                "kind": "checkable",
                "source": "",
            },
        ]
        rc, s = self.run_engine({"plan": [self.plan()], "write": [WRITE], "review": [dict(CLEAN, unchecked=items)]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer"])  # no verify call, no fix round
        self.assertEqual([u["what"] for u in self.eng.unverified], [items[1]["what"]])  # the deferral lands for the owner
        self.assertEqual(self.eng.verified[0]["why"], "the engine does this at land")

    def test_an_unrelated_checkable_item_is_still_verified(self):
        item = {"what": "The volume slider saves its value across restarts on every platform", "kind": "checkable", "source": ""}
        e = make_engine(self.wt, store=self.store, attrs={"plan_data": self.plan()})
        self.assertEqual(e.routing.ledger_route(item["what"]), "")
        self.assertEqual(e.routing.engine_steps([dict(item)]), [item])

    def test_a_deferred_case_the_plan_forgot_to_list_is_listed(self):
        plan = dict(PLAN, cases=[self.DEFER], leftovers=[])
        rc, _s = self.run_engine({"plan": [plan], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([lo["title"] for lo in self.eng.plan_data["leftovers"]], ["Import the chosen prefabs and add object rows"])
        self.assertIn("Import the chosen prefabs and add object rows", self.created())

    def test_a_case_with_nothing_to_prove_it_goes_back_to_the_planner(self):
        bad = dict(PLAN, cases=[{"criterion": "the rows exist", "check": ""}])
        _rc, s = self.run_engine({"plan": [bad, PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual([c[0] for c in s.calls], ["planner", "planner", "worker", "reviewer"])
        self.assertIn("case `the rows exist` has no check", s.prompts[1])
        self.assertEqual(lint.ledger_problems(self.plan()), [])

    def test_ledgered_cases_run_no_command(self):
        e = make_engine(self.wt, store=self.store, attrs={"plan_data": self.plan()})
        self.assertEqual(e.cases.case_checks(), [adhoc(HAS_F)])
        self.assertEqual(planref.plan_checks(self.plan()),
                         [adhoc(HAS_F)] + [c for st in PLAN["stages"] for c in st["checks"] if c != adhoc(HAS_F)])


def review_with(unmet):
    return dict(CLEAN, unmet=list(unmet))


class Inputs(StagesTest):
    """tl-bxk.13.16.3: inputs the criteria need that were not found are the owner's to decide in minute 4."""

    WIN: ClassVar[Any] = {"what": "a Windows PC to run the play test on", "kind": "platform", "path": ""}

    def test_a_missing_input_no_case_defers_is_an_assumption_not_an_ask(self):
        """tl-ntp: tl-7y6.6.15 stopped on study files no worktree can read; now the plan goes on and records it."""
        rc, s = self.run_engine({"plan": [dict(PLAN, unresolved=[self.WIN])], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertIsNone(self.ask())
        self.assertEqual([c[0] for c in s.calls][:2], ["planner", "worker"])
        plan = json.loads((self.eng.run_dir / "plan.json").read_text())
        self.assertEqual(plan["assumptions"], [{"step": "plan", "text": plan["assumptions"][0]["text"], "reversible": True}])
        self.assertIn("Windows PC", plan["assumptions"][0]["text"])
        recs = [json.loads(x) for x in self.eng.log_path.read_text().splitlines()]
        assumed = [r for r in recs if r["kind"] == "assumed"]
        self.assertEqual([r["text"] for r in assumed], [plan["assumptions"][0]["text"]])  # the typed record, the plan's own words
        self.assertTrue(assumed[0]["step"].startswith("n"))
        self.assertFalse(any(r["kind"] == "note" and r["text"].startswith("Assumption: ") for r in recs))  # no prose note any more
        self.assertIn("Windows PC", s.prompts[1])  # the writer reads the plan, assumptions included

    def ask(self):
        p = ident.config_dir() / "asks" / "t-1.json"
        return json.loads(p.read_text()) if p.exists() else None

    def test_a_plan_question_about_missing_inputs_proceeds_to_write_with_an_assumption(self):
        q = dict(PLAN, question="84-self-hosting.md is outside the worktree: which draft do I follow?",
                 options=[{"label": "Wait", "cost": "slow", "answer": "wait", "recommended": True}])
        rc, _s = self.run_engine({"plan": [q], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        got = self.ask()
        assert got is not None
        self.assertFalse(got["blocking"])  # a soft ask: filed for the owner, the run did not wait
        plan = json.loads((self.eng.run_dir / "plan.json").read_text())
        self.assertEqual({"question", "options", "decided", "unresolved"} & set(plan), set())  # the stored plan has none of them
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
        self.assertEqual(sorted(IRREVERSIBLE), ["close_epic", "delete_outside", "push_shared", "spend_money"])
        q = dict(PLAN, question="Push the rewritten history to main?", irreversible="push_shared",
                 options=[{"label": "Push", "cost": "shared", "answer": "push", "recommended": True},
                          {"label": "Hold", "cost": "slow", "answer": "hold", "recommended": False}])
        rc, s = self.run_engine({"plan": [q]})
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in s.calls], ["planner"])
        self.assertIn("Push the rewritten history", must(self.ask())["decision"])

    def test_an_input_a_case_defers_is_no_question(self):
        case = {"criterion": "The play test passes on the Windows PC", "check": "", "proved_by": "leftover",
                "via": "Run the play test on a Windows PC"}
        plan = dict(PLAN, unresolved=[self.WIN], cases=[case], leftovers=[{"title": "Run the play test on a Windows PC", "why": "no PC"}])
        rc, _s = self.run_engine({"plan": [plan], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertIn("inputs not found, their criteria deferred", self.eng.log_path.read_text())

    def test_a_file_that_is_there_after_all_is_dropped(self):
        plan = dict(PLAN, unresolved=[{"what": "the notes file", "kind": "file", "path": "a.txt"}])
        rc, _s = self.run_engine({"plan": [plan], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)

    def test_after_the_owner_answered_the_engine_does_not_ask_again(self):
        ask = dict(WRITE, question="Which format?")
        self.run_engine({"plan": [PLAN], "write": [ask]})
        with self.store.stub(comments=[{"author": "denis", "text": "Use the new format."}]):
            rc, _s = self.run_engine({"plan": [dict(PLAN, unresolved=[self.WIN])], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)

    def test_planner_notes_reach_the_planner_as_text_or_a_repo_file(self):
        _rc, s = self.run_engine(
            {"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, planner_notes="No Windows PC. Godot left main on 2026-10-12."
        )
        self.assertIn("Facts about this factory and project", s.prompts[0])
        self.assertIn("No Windows PC. Godot left main", s.prompts[0])
        (self.wt / "notes.md").write_text("The factory is a Mac only.\n")
        te.sh("git", "add", "-A", cwd=self.wt)
        te.sh("git", "commit", "-qm", "notes", cwd=self.wt)
        te.sh("git", "push", "-q", "origin", "HEAD:main", cwd=self.wt)
        _rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, planner_notes="@notes.md")
        self.assertIn("The factory is a Mac only.", s.prompts[0])
        _rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertNotIn("Facts about this factory", s.prompts[0])


if __name__ == "__main__":
    unittest.main()
