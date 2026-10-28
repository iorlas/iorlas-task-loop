"""Stage tests, part 2: the visual (look) stages, resume counting and bead claims. Split from test_stages."""
import json
import shutil
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "task-loop"))
from support import fake_route  # noqa: E402
from support.fakes import as_bead  # noqa: E402
from support import tlbd  # noqa: E402
from support.fakes import FakeBeadStore  # noqa: E402
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
from taskloop.domain.prompts.plan import REPLAN_CAP  # noqa: E402
from support.builders import cfg_with, make_engine  # noqa: E402
import test_engine as te  # noqa: E402
from test_engine import BEAD, CLEAN, FALSE, HAS_F, PLAN, WRITE, engine, lint, tl  # noqa: E402,F401


_REAL_CMD_BLOCK = tl.cmd_block  # te's harness patches it per test; this is the real one
from test_stages import StagesTest  # noqa: E402


class VisualWork(StagesTest):
    """tl-bxk.13.15: the engine renders the writer's shots, a look judge judges, the owner decides taste."""

    SHOT = ("import sys, pathlib\n"
            "out = pathlib.Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)\n"
            "name = sys.argv[2] if len(sys.argv) > 2 else 'screen'\n"
            "(out / (name + '.png')).write_bytes(b'\\x89PNG fake ' + name.encode())\n")
    TABLE = {"v": 1, "methods": [{"method": "ScreenShots", "summary": "the main screen", "timeout_min": 1,
                                  "argv": [sys.executable, "tools/shot.py", "{out}", "{args}"], "args": [{"name": "name", "flag": "", "pattern": "[a-z-]+"}]}]}
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
        (self.wt / "shots.json").write_text(json.dumps({"v": 1, "methods": [{"method": "Evil", "argv": ["touch", "pwned"]}]}))
        e = engine.Engine("t-1", str(self.wt), cfg_with(engine.load_cfg(str(self.wt)), shot_table="shots.json"), store=self.store)
        self.assertEqual(list(e.shot_methods()), ["ScreenShots"])

    def test_a_missing_table_is_warned_once_and_the_old_way_stands(self):
        e = engine.Engine("t-1", str(self.wt), cfg_with(engine.load_cfg(str(self.wt)), shot_table="nowhere.json"), store=self.store)
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
        e = make_engine(self.wt, cfg={"shot_table": "shots.json"}, store=self.store, attrs={"rendered_names": {"main.png"}})
        e.evidence_dir.mkdir(parents=True, exist_ok=True)
        (e.evidence_dir / "writer.png").write_bytes(b"x")
        (e.evidence_dir / "main.png").write_bytes(b"x")
        self.assertEqual(e.shots(), ["main.png"])

    @te.POSIX_CHECK
    def test_a_failed_shot_command_is_a_defect_even_if_it_left_a_picture(self):
        self.TABLE["methods"][0]["argv"] = [sys.executable, "-c", "import sys, runpy; sys.argv = ['shot.py'] + sys.argv[1:]; "
                                            "runpy.run_path('tools/shot.py', run_name='__main__'); sys.exit(3)", "{out}", "{args}"]
        try:
            base = Path(self.tmp.name, "base-files")
            (base / "shots.json").write_text(json.dumps(self.TABLE))
            te.sh("git", "commit", "-qam", "failing shot", cwd=base)
            te.sh("git", "push", "-q", "origin", "HEAD:main", cwd=base)
            te.sh("git", "pull", "-q", "origin", "main", cwd=self.wt)
            rc, s = self.go({"plan": [PLAN], "write": [self.write(), self.write()], "review": [CLEAN]})
        finally:
            self.TABLE["methods"][0]["argv"] = [sys.executable, "tools/shot.py", "{out}", "{args}"]
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
        e = make_engine(self.wt, store=self.store, attrs={
            "look_done": 1,
            "look_prev": [{"why": "x", "where": ""}],
            "rendered_names": {"a.png"},
            "last_reqs": self.SHOTS,
            "render_stale": True,
            "plan_data": dict(PLAN),
            "branch": "task/t-1",
            })
        e.git("checkout", "-q", "-b", "task/t-1")
        e.save_checkpoint(stage=0, rounds=0, n=1, feedback="", step="write")
        ck = json.loads(e.checkpoint_path().read_text())
        self.assertEqual((ck["look_done"], ck["rendered"], ck["render_stale"]), (1, ["a.png"], True))
        again = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)), store=self.store)
        again.reset(as_bead(BEAD))
        again.resume_point()
        self.assertEqual((again.look_done, again.rendered_names, again.render_stale), (1, {"a.png"}, True))

    def test_a_non_visual_repo_gets_none_of_it(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertNotIn("look-objective:", s.prompts[0])

    def test_the_gallery_data_lands_in_the_owner_look_beads_metadata(self):
        e = make_engine(self.wt, store=self.store, attrs={
            "plan_data": dict(PLAN, cases=[{"criterion": "it reads well", "check": "", "class": "taste"}]),
            "look_paths": ["design/look-reviews/t-1/main.png"],
            "look_notes": ["the main screen shows"],
            })
        sent = []
        old = {"metadata": {"looks": [
            {"id": "t-0#1", "bead": "t-0", "title": "other", "shots": [], "status": "open"},
            {"id": "t-1#1", "bead": "t-1", "title": "it reads well", "shots": [], "status": "good"}], "keep": "me"}}
        with self.store.stub(show=old), \
                self.store.stub(bd_fn=lambda *a, **k: sent.append(a) or mock.Mock(returncode=0, stdout="", stderr="")):
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
        with self.store.stub(show=old), \
                self.store.stub(bd_fn=lambda *a, **k: sent.append(a) or mock.Mock(returncode=0, stdout="", stderr="")):
            e.write_looks("lk-1")
        entry = json.loads(sent[0][3])["looks"][-1]
        self.assertEqual((entry["id"], entry["bead"], entry["title"], entry["status"]), ("t-1#1", "t-1", "it reads well", "open"))
        self.assertEqual(entry["note"], "the main screen shows")
        self.assertEqual(entry["shots"], [{"path": "design/look-reviews/t-1/main.png", "role": "after", "label": "main"}])


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
        with self.store.stub(comments=[{"author": "denis", "text": "Use the new format."}]):
            rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, max_replans=0)
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(s.calls[0][0], "planner")  # it amended
        self.assertEqual((self.eng.planned, self.eng.plan_log[-1]["counted"]), (1, False))

    def test_an_edit_with_no_ask_still_counts(self):
        # who edited the bead is not known: a comment from a sibling agent must not lift the limit
        self.run_engine({"plan": [PLAN], "write": [dict(WRITE, question="Which format?")]}, max_replans=1)
        path = tl.config_dir() / "asks" / "t-1.json"
        path.unlink()
        with self.store.stub(show=dict(BEAD, description="Also say hi.")):
            rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, max_replans=1)
        self.assertEqual(self.eng.plan_log[-1]["counted"], True)

    def test_a_failed_plan_still_counts_and_the_limit_still_stops(self):
        flag = dict(WRITE, bad_checks=[{"cmd": FALSE, "why": "never passes"}])
        bad = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[FALSE])])
        rc, s = self.run_engine({"plan": [bad, bad], "write": [flag, flag]}, max_replans=1)
        self.assertEqual(rc, 2)
        self.assertTrue(self.blocked and self.blocked[0].startswith(REPLAN_CAP))

    def test_a_rebase_onto_a_new_base_starts_the_plan_count_again(self):
        self.behind_branch()
        e = make_engine(self.wt, store=self.store, attrs={"planned": 3, "plan_log": [{"mode": "plan", "why": "x"}] * 3})
        e.git("checkout", "-q", "task/t-1")
        self.assertEqual(e.rebase_onto_base(), "rebased")
        self.assertEqual((e.planned, e.rebase_resets), (0, 1))
        self.assertEqual(e.plan_log[-1]["counted"], False)  # the history stays, with a note
        self.assertEqual(e.rebase_onto_base(), "")  # nothing behind now

    def test_the_count_starts_again_after_a_rebase_at_most_twice_per_bead(self):
        e = make_engine(self.wt, store=self.store, attrs={"rebase_resets": engine.MAX_REBASE_RESETS, "planned": 3})
        self.behind_branch()
        e.git("checkout", "-q", "task/t-1")
        self.assertEqual(e.rebase_onto_base(), "rebased")
        self.assertEqual(e.planned, 3)  # a bead stuck for a real reason still reaches the limit while main moves

    def test_a_branch_that_conflicts_with_main_starts_again_fresh_and_nothing_is_counted(self):
        self.behind_branch(conflict=True)
        with self.store.stub(comments=[{"author": "denis", "text": "Use the new format."}]):
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
        e = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)), store=self.store)
        e.reset(as_bead(BEAD))
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
        e = make_engine(self.wt, store=self.store, attrs={"branch": "task/t-1"})
        e.git("checkout", "-q", "task/t-1")
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
        e = make_engine(self.wt, store=self.store, attrs={
            "branch": "task/t-1", "unverified": [{"what": "x"}], "look_paths": ["p.png"], "fixes": 2, "replans": 2, "rendered_names": {"a.png"},
            "verify_answer": "Use the old format"})
        e.git("checkout", "-q", "task/t-1")
        e.handoff["rounds"] = [{"r": 1}]
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
        import loop_env
        with self.store.stub(show=parked), mock.patch.object(tl, "live_actors", return_value={"tl-2be89f88"}), \
                self.store.stub(comments=comments), mock.patch.object(loop_env, "running", return_value={}):
            ok, why = engine.reclaim("t-1", str(self.wt), store=self.store)
        self.assertTrue(ok, why)
        self.assertEqual(why, "reopened")
        self.assertEqual(self.store.calls[0], ("update", "t-1", "--status", "open", "--if-assignee", "tl-2be89f88", "--assignee", ""))

    def test_a_parked_bead_with_an_engine_still_on_it_is_a_live_claim(self):
        parked = {"id": "t-1", "status": "blocked", "assignee": "tl-2be89f88", "lease_expires_at": "", "dependencies": []}
        import loop_env
        with self.store.stub(show=parked), mock.patch.object(tl, "live_actors", return_value=set()), \
                mock.patch.object(loop_env, "running", return_value={"t-1": "s2"}):
            ok, why = engine.reclaim("t-1", str(self.wt), store=self.store)
        self.assertFalse(ok)
        self.assertIn("a live claim", why)

    def test_a_working_bead_of_a_live_actor_is_still_a_live_claim(self):
        busy = {"id": "t-1", "status": "in_progress", "assignee": "tl-2be89f88", "lease_expires_at": "", "dependencies": []}
        with self.store.stub(show=busy), mock.patch.object(tl, "live_actors", return_value={"tl-2be89f88"}):
            ok, why = engine.reclaim("t-1", str(self.wt), store=self.store)
        self.assertFalse(ok)
        self.assertIn("a live claim", why)

    @te.no_repo
    def test_parking_a_bead_lets_go_of_its_claim(self):
        for holder, expect in (("tl-2be89f88", ("update", "t-1", "--status", "blocked", "--assignee", "")),
                               ("denis", ("update", "t-1", "--status", "blocked")), ("", ("update", "t-1", "--status", "blocked"))):
            store = FakeBeadStore().put({"id": "t-1", "assignee": holder})
            with tlbd.bd_boundary(store=store), \
                    mock.patch.object(tl, "event"), mock.patch.object(tl, "provenance"):
                self.assertEqual(real_cmd_block(mock.Mock(id="t-1", why="stuck")), 0)
            self.assertEqual(store.said("update")[0], expect, holder)  # a person's own claim stays theirs

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
        e = make_engine(self.wt, cfg=dict(reflect=True), store=self.store, attrs={
            "route": "/fake/route.py",
            "sessions": [{"node": "plan"}],
            })
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


if __name__ == "__main__":
    unittest.main()
