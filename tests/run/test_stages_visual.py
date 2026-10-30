"""Stage tests, part 2: the visual (look) stages, resume counting and bead claims. Split from test_stages."""
import json
import subprocess
import sys
import time
import unittest
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import engine_case as te
from support import (
    fake_route,
    procsim,
)
from support.builders import cfg_with, make_engine, plan_of
from support.checkpoints import read_ck
from support.engine_case import BEAD, CLEAN, FALSE, HAS_F, PLAN, WRITE, engine, lint  # noqa: F401
from support.fakes import (
    FakeBeadStore,
    must_bead,
)
from support.spawn import real_spawner

from run.test_stages import StagesTest
from taskloop.adapters import gitrepo, ident
from taskloop.app.land.rebase import MAX_REBASE_RESETS
from taskloop.app.run import (
    entry,
    outcomes,
)
from taskloop.app.run import running as wrunning
from taskloop.app.track import verbs
from taskloop.app.wire import slots as wslots
from taskloop.contracts.checkpoint import Defect
from taskloop.contracts.env import snapshot
from taskloop.contracts.ids import BeadId
from taskloop.contracts.run import Round
from taskloop.domain.prompts.plan import REPLAN_CAP


class VisualWork(StagesTest):
    """tl-bxk.13.15: the engine renders the writer's shots, a look judge judges, the owner decides taste."""

    @staticmethod
    def shot(code):
        """The repo's shot tool as a procsim fake: `shot-tool OUT [NAME]` saves OUT/NAME.png, then exits `code`."""
        def run(cwd, env):
            out, name = Path(procsim.argv()[1]), (procsim.argv()[2:3] or ["screen"])[0]
            out.mkdir(parents=True, exist_ok=True)
            (out / (name + ".png")).write_bytes(b"\x89PNG fake " + name.encode())
            return code, ""
        return run

    TABLE: ClassVar[Any] = {
        "v": 1,
        "methods": [
            {
                "method": "ScreenShots",
                "summary": "the main screen",
                "timeout_min": 1,
                "argv": ["shot-tool", "{out}", "{args}"],
                "args": [{"name": "name", "flag": "", "pattern": "[a-z-]+"}],
            }
        ],
    }
    VIS: ClassVar[Any] = {"include": ["f.txt"]}

    def setUp(self):
        super().setUp()
        procsim.fake("shot-tool", self.shot(0), args=True)
        procsim.fake("shot-tool-fails", self.shot(3), args=True)
        base = Path(self.tmp.name, "base-files")
        te.sh("git", "clone", "-q", str(Path(self.tmp.name, "o.git")), str(base), cwd=self.tmp.name)
        (base / "shots.json").write_text(json.dumps(self.TABLE))
        te.sh("git", "add", "-A", cwd=base)
        te.sh("git", "commit", "-qm", "shot table", cwd=base)
        te.sh("git", "push", "-q", "origin", "HEAD:main", cwd=base)
        te.sh("git", "pull", "-q", "origin", "main", cwd=self.wt)

    def go(self, answers, table="shots.json", **cfg):
        raw = {"visual_paths": self.VIS, "shot_table": table}
        return self.run_engine(answers, raw=raw, **cfg)

    SHOTS: ClassVar[Any] = [{"method": "ScreenShots", "args": [{"name": "name", "value": "main"}], "names": ["main screen"]}]

    @staticmethod
    def judged(*defects, summary="the main screen shows"):
        return {"findings": [{"item": "general", "verdict": "defect", "where": w, "why": y} for w, y in defects] or
                [{"item": "general", "verdict": "pass", "where": "", "why": "fine"}], "summary": summary}

    def write(self, **kw):
        return dict(WRITE, **dict({"shots": self.SHOTS}, **kw))

    def roles(self, s):
        return [c[0] for c in s.calls]

    def test_a_look_judge_with_no_lane_leaves_the_pictures_unjudged_and_the_bead_unparked(self):
        late = te.stop("no_lane", at=time.time() + 3600, family="xai", lane="GROK", say="no lane")
        rc, s = self.go({"plan": [PLAN], "write": [self.write()], "look": [late], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertIn("the look judge had no lane", self.eng.log_path.read_text())
        self.assertIn("look judge, round 1", self.eng.look_unjudged)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer", "reviewer"])  # the judge's one try, then the review

    def test_a_login_or_a_crash_is_not_swallowed_by_the_look_judge(self):
        out = te.stop("logged_out", family="claude", lane="CLAUDE", say="logged out")
        _rc, _s = self.go({"plan": [PLAN], "write": [self.write()], "look": [out, out]})
        self.assertIn("paused", self.eng.why)

    def test_the_judge_from_the_writers_family_is_not_taken(self):
        rc, _s = self.go({"plan": [PLAN], "write": [self.write()], "look": [self.judged()], "review": [CLEAN]},
                        j_extra={"look": [{"flag": "same_family"}]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertIn("no lane for the look judge", " ".join(self.eng.look_notes))

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
        _rc, s = self.go({"plan": [PLAN], "write": [self.write()], "look": [self.judged()], "review": [CLEAN]})
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
        self.assertEqual(
            self.roles(s), ["planner", "worker", "worker", "reviewer", "reviewer"]
        )  # the second write, then the judge, then the review
        self.assertIn("named no shots and gave no logic_only reason", s.prompts[2])
        self.assertIn("ScreenShots: the main screen", s.prompts[2])  # the table is in the question
        self.assertEqual(self.eng.stats["rounds"], 0)  # not a send-back round
        self.assertIn("shots_contract", self.eng.log_path.read_text())
        self.assertTrue((self.eng.evidence_dir / "main.png").is_file())  # the second answer's shots were rendered

    def test_a_logic_only_reason_or_shots_need_no_second_ask(self):
        _rc, s = self.go({"plan": [PLAN], "write": [dict(WRITE, logic_only="a rename: nothing on screen differs")], "review": [CLEAN]})
        self.assertEqual(self.roles(s), ["planner", "worker", "reviewer"])
        _rc, s = self.go({"plan": [PLAN], "write": [self.write()], "look": [self.judged()], "review": [CLEAN]})
        self.assertEqual(self.roles(s).count("worker"), 1)

    def test_a_writer_that_still_names_nothing_gets_a_warning_from_the_review_not_a_send_back(self):
        _rc, s = self.go({"plan": [PLAN], "write": [WRITE, WRITE, WRITE, WRITE], "review": [CLEAN, CLEAN]})
        self.assertIn("asked for no shots", self.eng.log_path.read_text())
        self.assertEqual(sum(1 for t in s.prompts if "named no shots and gave no logic_only reason" in t), 1)  # asked once, not again

    def test_the_planner_is_told_the_rule_and_the_repos_shot_methods(self):
        base = Path(self.tmp.name, "base-files")
        (base / "lifesim.json").write_text((Path(__file__).resolve().parents[1] / "fixtures" / "lifesim_shot_table.json").read_text())
        te.sh("git", "add", "-A", cwd=base)
        te.sh("git", "commit", "-qm", "lifesim table", cwd=base)
        te.sh("git", "push", "-q", "origin", "HEAD:main", cwd=base)
        te.sh("git", "pull", "-q", "origin", "main", cwd=self.wt)
        _rc, s = self.go({"plan": [PLAN], "write": [self.write()], "review": [CLEAN]}, table="lifesim.json")
        planner = s.prompts[0]
        self.assertIn("changes how something looks", planner)
        self.assertIn("logic_only", planner)
        self.assertIn("(f.txt)", planner)  # the visual paths
        self.assertIn("- BuildShots: Build mode: flat, drag, undo", planner)
        self.assertIn("- PoseShots: Every declared body slot", planner)
        self.assertNotIn("Diagnostic records", planner)  # a line per method, not the whole summary

    def test_without_a_shot_table_a_visual_stage_works_the_old_way(self):
        _rc, s = self.go({"plan": [PLAN], "write": [WRITE, WRITE], "review": [CLEAN, CLEAN]}, table="")
        self.assertIn("Save a screenshot of every changed", s.prompts[1])
        self.assertNotIn("You cannot render it here", s.prompts[1])
        self.assertNotIn("look", list(self.eng.run_dir.glob("look-*.json")))

    def test_the_table_is_read_from_the_base_branch_not_the_working_copy(self):
        (self.wt / "shots.json").write_text(json.dumps({"v": 1, "methods": [{"method": "Evil", "argv": ["touch", "pwned"]}]}))
        cfg = cfg_with(wslots.load_cfg(str(self.wt)), shot_table="shots.json")
        e = engine.Engine(BeadId("t-1"), str(self.wt), cfg, store=self.store, env=snapshot(), spawner=real_spawner())
        self.assertEqual(list(e.pictures.shot_methods()), ["ScreenShots"])

    def test_a_missing_table_is_warned_once_and_the_old_way_stands(self):
        cfg = cfg_with(wslots.load_cfg(str(self.wt)), shot_table="nowhere.json")
        e = engine.Engine(BeadId("t-1"), str(self.wt), cfg, store=self.store, env=snapshot(), spawner=real_spawner())
        self.assertEqual(e.pictures.shot_methods(), {})
        self.assertEqual(e.pictures.shot_methods(), {})

    def test_look_and_taste_cases_have_no_command_and_run_nothing(self):
        cases = [{"criterion": "the picker shows", "check": "", "class": "look-objective"},
                 {"criterion": "it reads well", "check": "", "class": "taste"}]
        rc, s = self.go({"plan": [dict(PLAN, cases=cases)], "write": [self.write()], "look": [self.judged()], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertIn("the picker shows", s.prompts[2])  # the judge judges the look-objective item
        self.assertNotIn("it reads well", s.prompts[2])
        self.assertEqual(self.eng.cases.case_checks(), [])

    def test_the_planner_is_told_the_classes_and_to_assume_a_missing_reference(self):
        _rc, s = self.go({"plan": [PLAN], "write": [self.write()], "look": [self.judged()], "review": [CLEAN]})
        plan_prompt = s.prompts[0]
        self.assertIn("look-objective:", plan_prompt)
        self.assertIn("Never invent one as a check", plan_prompt)
        self.assertIn("assume the look", plan_prompt)  # no reference image in the task

    def test_a_visual_repo_without_a_shot_table_is_told_nothing_of_classes(self):
        _rc, s = self.go({"plan": [PLAN], "write": [WRITE, WRITE], "review": [CLEAN, CLEAN]}, table="")
        self.assertNotIn("look-objective:", s.prompts[0])

    TWO: ClassVar[Any] = dict(PLAN, stages=[PLAN["stages"][0], dict(PLAN["stages"][0], goal="add g")],
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
        e = make_engine(self.wt, cfg={"shot_table": "shots.json"}, store=self.store, attrs={"rendered_names": ["main.png"]})
        e.evidence_dir.mkdir(parents=True, exist_ok=True)
        (e.evidence_dir / "writer.png").write_bytes(b"x")
        (e.evidence_dir / "main.png").write_bytes(b"x")
        self.assertEqual(e.pictures.shots(), ["main.png"])

    @te.POSIX_CHECK
    def test_a_failed_shot_command_is_a_defect_even_if_it_left_a_picture(self):
        self.TABLE["methods"][0]["argv"] = ["shot-tool-fails", "{out}", "{args}"]
        try:
            base = Path(self.tmp.name, "base-files")
            (base / "shots.json").write_text(json.dumps(self.TABLE))
            te.sh("git", "commit", "-qam", "failing shot", cwd=base)
            te.sh("git", "push", "-q", "origin", "HEAD:main", cwd=base)
            te.sh("git", "pull", "-q", "origin", "main", cwd=self.wt)
            _rc, s = self.go({"plan": [PLAN], "write": [self.write(), self.write()], "review": [CLEAN]})
        finally:
            self.TABLE["methods"][0]["argv"] = ["shot-tool", "{out}", "{args}"]
        self.assertEqual(self.roles(s)[:3], ["planner", "worker", "worker"])  # no judge call: the render failed
        self.assertIn("failed (exit 3)", s.prompts[2])

    def test_pictures_made_before_a_later_fix_are_rendered_again_before_the_land(self):
        red_once = procsim.fake("red-on-d2", lambda cwd, env: (1 if procsim.f_txt(cwd) == "d2" else 0, ""))  # red after the first write
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[red_once])])
        rc, _s = self.go(
            {
                "plan": [plan],
                "write": [self.write(), self.write(shots=[], logic_only="nothing on screen changed")],
                "look": [self.judged()],
                "review": [CLEAN],
            },
            look_rounds=1,
        )
        self.assertEqual(rc, 0, self.blocked)
        self.assertIn("rendering the last shots again", self.eng.log_path.read_text())
        self.assertEqual(self.eng.render_stale, False)

    def test_a_resumed_stage_keeps_its_render_rounds(self):
        e = make_engine(self.wt, store=self.store, attrs={
            "look_done": 1,
            "look_prev": [Defect(item="i", why="x")],
            "rendered_names": ["a.png"],
            "last_reqs": self.SHOTS,
            "render_stale": True,
            "plan_data": dict(PLAN),
            "branch": "task/t-1",
            })
        e.git("checkout", "-q", "-b", "task/t-1")
        e.checkpoints.save(stage=0, rounds=0, n=1, feedback="", step="write")
        ck = read_ck(e).state
        self.assertEqual((ck.look_done, sorted(ck.rendered_names), ck.render_stale), (1, ["a.png"], True))
        again = engine.Engine(BeadId("t-1"), str(self.wt), wslots.load_cfg(str(self.wt)), store=self.store, env=snapshot(),
            spawner=real_spawner())
        again.tree.reset(must_bead(BEAD))
        again.resume.point()
        self.assertEqual((again.look_done, again.rendered_names, again.render_stale), (1, ["a.png"], True))

    def test_a_non_visual_repo_gets_none_of_it(self):
        _rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertNotIn("look-objective:", s.prompts[0])

    def test_the_gallery_data_lands_in_the_owner_look_beads_metadata(self):
        e = make_engine(self.wt, store=self.store, attrs={
            "plan_data": dict(PLAN, cases=[{"criterion": "it reads well", "check": "", "class": "taste"}]),
            "look_paths": ["main.png"],
            "look_notes": ["the main screen shows"],
            })
        sent = []
        old = {"metadata": {"looks": [
            {"id": "t-0#1", "bead": "t-0", "title": "other", "shots": [], "status": "open"},
            {"id": "t-1#1", "bead": "t-1", "title": "it reads well", "shots": [], "status": "good"}], "keep": "me"}}
        with self.store.stub(show=old), \
                self.store.stub(bd_fn=lambda *a, **k: sent.append(a) or mock.Mock(returncode=0, stdout="", stderr="")):
            e.owner_look.write_looks(BeadId("lk-1"))
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
            e.owner_look.write_looks(BeadId("lk-1"))
        entry = json.loads(sent[0][3])["looks"][-1]
        self.assertEqual((entry["id"], entry["bead"], entry["title"], entry["status"]), ("t-1#1", "t-1", "it reads well", "open"))
        self.assertEqual(entry["note"], "the main screen shows")
        self.assertEqual(entry["shots"], [{"path": "artifact:t-1/main.png", "role": "after", "label": "main"}])


class ResumeCount(StagesTest):
    """tl-19i: the re-plan limit counts failed plans on one base, never the owner's answer; a branch that conflicts with main starts
    again."""

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
        self.assertEqual((self.eng.planned, self.eng.plan_log[-1].counted), (1, False))

    def test_an_edit_with_no_ask_still_counts(self):
        # who edited the bead is not known: a comment from a sibling agent must not lift the limit
        self.run_engine({"plan": [PLAN], "write": [dict(WRITE, question="Which format?")]}, max_replans=1)
        path = ident.config_dir() / "asks" / "t-1.json"
        path.unlink()
        with self.store.stub(show=dict(BEAD, description="Also say hi.")):
            _rc, _s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, max_replans=1)
        self.assertEqual(self.eng.plan_log[-1].counted, True)

    def test_a_failed_plan_still_counts_and_the_limit_still_stops(self):
        flag = dict(WRITE, bad_checks=[{"cmd": FALSE, "why": "never passes"}])
        bad = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[FALSE])])
        rc, _s = self.run_engine({"plan": [bad, bad], "write": [flag, flag]}, max_replans=1)
        self.assertEqual(rc, 2)
        self.assertTrue(self.blocked and self.blocked[0].startswith(REPLAN_CAP))

    def test_a_rebase_onto_a_new_base_starts_the_plan_count_again(self):
        self.behind_branch()
        e = make_engine(self.wt, store=self.store, attrs={"planned": 3, "plan_log": [{"mode": "plan", "why": "x"}] * 3})
        e.git("checkout", "-q", "task/t-1")
        self.assertEqual(e.rebase.onto_base(), "rebased")
        self.assertEqual((e.planned, e.rebase_resets), (0, 1))
        self.assertEqual(e.plan_log[-1].counted, False)  # the history stays, with a note
        self.assertEqual(e.rebase.onto_base(), "")  # nothing behind now

    def test_the_count_starts_again_after_a_rebase_at_most_twice_per_bead(self):
        e = make_engine(self.wt, store=self.store, attrs={"rebase_resets": MAX_REBASE_RESETS, "planned": 3})
        self.behind_branch()
        e.git("checkout", "-q", "task/t-1")
        self.assertEqual(e.rebase.onto_base(), "rebased")
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
        out = subprocess.run(
            ["git", "branch", "--list", "task/t-1-stale-*"], cwd=self.wt, capture_output=True, text=True, check=False
        ).stdout
        self.assertIn("task/t-1-stale-", out)  # the earlier work is kept
        shown = subprocess.run(["git", "show", "origin/main:a.txt"], cwd=self.wt, capture_output=True, text=True, check=False).stdout
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
            te.sh("git", "commit", "-qm", f"wip (t-1): {n}", cwd=self.wt)
        base = Path(self.tmp.name, "base-moves")
        te.sh("git", "clone", "-q", str(Path(self.tmp.name, "o.git")), str(base), cwd=self.tmp.name)
        for f in files:
            (base / f).write_text(main + "\n")
        te.sh("git", "add", "-A", cwd=base)
        te.sh("git", "commit", "-qm", "main moves", cwd=base)
        te.sh("git", "push", "-q", "origin", "HEAD:main", cwd=base)
        e = engine.Engine(BeadId("t-1"), str(self.wt), wslots.load_cfg(str(self.wt)), store=self.store, env=snapshot(),
            spawner=real_spawner())
        e.tree.reset(must_bead(BEAD))
        e.plan_data = plan_of(PLAN)
        e.checkpoints.save(stage=0, rounds=0, n=1, feedback="", step="write")
        te.sh("git", "checkout", "-q", "--detach", "origin/main", cwd=self.wt)

    def last_trace(self):
        return json.loads((ident.config_dir() / "traces.jsonl").read_text().splitlines()[-1])

    def test_wip_commits_that_conflict_only_unsquashed_are_squashed_and_rebase_without_a_fix(self):
        self.wip_branch(["step 1", "step 2", "step 3", "main moved on"], "main moved on")
        rc, s = self.run_engine({"write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["worker", "reviewer"])  # no fix round, no plan
        text = self.eng.log_path.read_text()
        self.assertIn("squashed the branch's wip commits into one", text)
        self.assertNotIn("resume_conflict", text)
        self.assertFalse(self.last_trace()["salvaged"])
        self.assertEqual(gitrepo.git("show", "origin/main:a.txt", cwd=str(self.wt)), "main moved on")
        self.assertEqual(
            subprocess.run(
                ["git", "branch", "--list", "task/t-1-stale-*"], cwd=self.wt, capture_output=True, text=True, check=False
            ).stdout,
            "",
        )

    def test_a_resume_conflict_in_more_than_ten_files_starts_again_as_before(self):
        files = [f"c{n}.txt" for n in range(11)]
        self.wip_branch(["mine 1", "mine 2"], "theirs", files=files)
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer"])
        self.assertIn("resume_conflict", self.eng.log_path.read_text())
        self.assertFalse(self.last_trace()["salvaged"])
        out = subprocess.run(
            ["git", "branch", "--list", "task/t-1-stale-*"], cwd=self.wt, capture_output=True, text=True, check=False
        ).stdout
        self.assertIn("task/t-1-stale-", out)
        stale = out.split()[-1]
        self.assertEqual(gitrepo.git("show", stale + ":c0.txt", cwd=str(self.wt)), "mine 2")  # the work is kept whole

    def test_exactly_ten_conflicted_files_are_still_fixed(self):
        files = [f"c{n}.txt" for n in range(10)]
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
        self.assertEqual([c[0] for c in s.calls], ["worker", "reviewer", "worker", "reviewer"])  # the conflict fix, then the stage; no plan
        self.assertIn("conflict", s.prompts[0])
        self.assertNotIn("resume_conflict", self.eng.log_path.read_text())
        self.assertTrue(self.last_trace()["salvaged"])
        self.assertEqual(gitrepo.git("show", "origin/main:c0.txt", cwd=str(self.wt)), "merged")
        self.assertEqual(self.eng.fixes, 0)  # the land's two fix rounds are its own
        stale = subprocess.run(["git", "branch", "--list", "task/t-1-stale-*"], cwd=self.wt, capture_output=True, text=True, check=False)
        self.assertEqual(stale.stdout, "")

    def test_a_conflict_fix_that_does_not_resolve_it_restores_the_branch_and_starts_again(self):
        self.wip_branch(["mine 1", "mine 2"], "theirs")
        rc, _s = self.run_engine({"plan": [PLAN], "write": [WRITE] * 3, "review": [CLEAN]}, max_check_tries=1, max_rounds=1)
        self.assertEqual(rc, 0, self.blocked)
        self.assertIn("resume_conflict", self.eng.log_path.read_text())
        self.assertFalse(self.last_trace()["salvaged"])
        out = subprocess.run(
            ["git", "branch", "--list", "task/t-1-stale-*"], cwd=self.wt, capture_output=True, text=True, check=False
        ).stdout
        stale = out.split()[-1]
        self.assertEqual(gitrepo.git("show", stale + ":a.txt", cwd=str(self.wt)), "mine 2")  # the original work, not a half-fixed rebase
        self.assertEqual(self.eng.fixes, 0)

    def test_a_branch_that_cannot_be_kept_aside_is_not_reset(self):
        self.behind_branch(conflict=True)
        e = make_engine(self.wt, store=self.store, attrs={"branch": "task/t-1"})
        e.git("checkout", "-q", "task/t-1")
        before = e.git("rev-parse", "HEAD")
        real = e.sh
        patch = mock.patch.object(e, "sh", new=lambda cmd, **kw: (1, "refused") if cmd[:3] == ["git", "branch", "-m"] else real(cmd, **kw))
        patch.start()
        self.addCleanup(patch.stop)
        self.assertFalse(e.restart.again("x"))
        self.assertEqual(e.git("rev-parse", "HEAD"), before)  # the work is where it was
        e.sh = real
        e.git("checkout", "-q", "--detach")
        self.assertFalse(e.restart.again("x"))  # detached: nothing renamed or reset

    def test_a_fresh_start_clears_what_the_old_attempt_left(self):
        self.behind_branch(conflict=True)
        e = make_engine(
            self.wt,
            store=self.store,
            attrs={
                "branch": "task/t-1",
                "unverified": [{"what": "x"}],
                "look_paths": ["p.png"],
                "fixes": 2,
                "replans": 2,
                "rendered_names": ["a.png"],
                "verify_answer": "Use the old format",
            },
        )
        e.git("checkout", "-q", "task/t-1")
        e.handoff.rounds = [Round(stage="s", round=1, kind="k")]
        self.assertTrue(e.restart.again("x"))
        self.assertEqual((e.unverified, e.look_paths, e.handoff.rounds, e.fixes, e.replans, e.rendered_names), ([], [], [], 0, 0, []))
        self.assertEqual(e.verify_answer, "Use the old format")  # the owner's word still goes to the planner


class Claims(StagesTest):
    """tl-159, tl-wjj, tl-05s."""

    def test_a_parked_bead_whose_actor_is_live_elsewhere_can_be_taken_over(self):
        parked = {
            "id": "t-1",
            "status": "blocked",
            "assignee": "tl-2be89f88",
            "lease_expires_at": "2999-01-01T00:00:00Z",
            "dependencies": [],
        }
        comments = [{"text": "Blocked: stuck: re-planned 3 times", "created_at": "1", "author": "engine"}]
        with self.store.stub(show=parked), \
                self.store.stub(comments=comments), mock.patch.object(wrunning, "running", return_value={}):
            ok, why = entry.admit("t-1", str(self.wt), store=self.store)
        self.assertTrue(ok, why)
        self.assertEqual(why, "reopened")
        self.assertEqual(self.store.calls[0], ("update", "t-1", "--status", "open", "--if-assignee", "tl-2be89f88", "--assignee", ""))

    def test_a_parked_bead_with_an_engine_still_on_it_is_a_live_claim(self):
        parked = {"id": "t-1", "status": "blocked", "assignee": "tl-2be89f88", "lease_expires_at": "", "dependencies": []}
        with self.store.stub(show=parked), \
                mock.patch.object(wrunning, "running", return_value={"t-1": "s2"}):
            ok, why = entry.admit("t-1", str(self.wt), store=self.store)
        self.assertFalse(ok)
        self.assertIn("a live claim", why)

    def test_a_working_bead_that_is_still_claimed_after_the_sweep_is_a_live_claim(self):
        busy = {"id": "t-1", "status": "in_progress", "assignee": "tl-2be89f88", "lease_expires_at": "", "dependencies": []}
        with self.store.stub(show=busy):
            ok, why = entry.admit("t-1", str(self.wt), store=self.store)
        self.assertFalse(ok)
        self.assertIn("a live claim", why)

    @te.no_repo
    def test_parking_a_bead_lets_go_of_its_claim(self):
        for holder, expect in (("tl-2be89f88", ("update", "t-1", "--status", "blocked", "--assignee", "")),
                               ("denis", ("update", "t-1", "--status", "blocked")), ("", ("update", "t-1", "--status", "blocked"))):
            store = FakeBeadStore().put({"id": "t-1", "assignee": holder})
            self.assertEqual(verbs.block(BeadId("t-1"), "stuck", store), 0)
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

    REFLECTION: ClassVar[Any] = {
        "went_well": ["the plan was right at once"],
        "wasted": ["2 min waiting for a lane"],
        "change": ["engine: none"],
        "went_badly": [
            {
                "what": "the review sent the same finding back twice",
                "cause": "prompt",
                "session": "ref-review",
                "evidence": "2 reviews, same file:line",
            }
        ],
    }

    def test_a_run_ends_with_a_reflection_in_the_trace_and_the_bead_comment(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN], "reflect": [self.REFLECTION]}, reflect=True)
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer", "reviewer"])  # the reflection is the last call
        self.assertIn("Bead t-1: Add f", s.prompts[3])
        self.assertIn("session ref-write", s.prompts[3])  # the sessions to cite
        last = json.loads((ident.config_dir() / "traces.jsonl").read_text().splitlines()[-1])
        self.assertEqual(last["reflection"]["went_badly"][0]["cause"], "prompt")
        self.assertEqual(last["reflection"]["went_badly"][0]["session"], "ref-review")
        comment = next(c[3] for c in self.bd_calls if c[:2] == ("comments", "add") and c[3].startswith("Reflect (engine)"))
        self.assertIn("reflection: badly: [prompt] the review sent the same finding back twice (session ref-review)", comment)
        self.assertLess(comment.index("reflection:"), comment.index("filed="))  # first: the view of the last run clips at 400 characters
        self.assertEqual(last["stats"]["tokens_in"], sum(s["tokens"]["in"] for s in last["sessions"] if s["node"] != "reflect"))

    def test_a_reflection_that_fails_changes_nothing(self):
        crash = fake_route.NO_ANSWER
        rc, _s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN], "reflect": [crash, crash, crash]}, reflect=True)
        self.assertEqual(rc, 0, self.blocked)
        last = json.loads((ident.config_dir() / "traces.jsonl").read_text().splitlines()[-1])
        self.assertEqual((last["outcome"], last["reflection"]), ("landed", None))
        self.assertTrue(self.closed and self.closed[0].startswith("merged"))

    def test_no_reflection_for_a_paused_run_or_when_switched_off(self):
        _rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})  # reflect off in the harness
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer"])
        e = make_engine(self.wt, cfg={"reflect": True}, store=self.store, attrs={
            "route": "/fake/route.py",
            "sessions": [{"node": "plan"}],
            })
        self.assertIsNone(e.reflector.reflect_run("failed", "failed: x"))  # a run that only planned
        e.sessions = [{"node": "plan"}, {"node": "write"}]
        self.assertIsNone(e.reflector.reflect_run("blocked", "paused: no lane for write until 04:00"))
        e.stop_pending = True
        self.assertIsNone(e.reflector.reflect_run("landed", ""))  # a stop is on its way
        e.stop_pending = False
        self.assertIsNone(e.reflector.reflect_run("failed", "failed: infrastructure: bad_request"))
        e.dry = True
        self.assertIsNone(e.reflector.reflect_run("landed", ""))

    @te.no_repo
    def test_the_reflection_text_names_cause_and_session(self):
        text = outcomes.reflection_text(self.REFLECTION)
        self.assertIn("[prompt]", text)
        self.assertIn("(session ref-review)", text)
        self.assertEqual(outcomes.reflection_text(None), "")
        self.assertIn("badly: none", outcomes.reflection_text(dict(self.REFLECTION, went_badly=[])))


if __name__ == "__main__":
    unittest.main()
