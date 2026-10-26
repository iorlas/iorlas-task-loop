"""tl-bxk.10.23: look and feel. A visual change saves screenshots; the agent judges them; the land keeps them in the repo
and files an owner-look bead for the owner's later round."""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "task-loop"))
import fake_route  # noqa: E402
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
import test_engine as T  # noqa: E402
from test_engine import BEAD, CLEAN, PLAN, WRITE, engine, tl, verdict  # noqa: E402

VISUAL = {"include": ["*.txt"], "exclude": ["docs/**"]}
LOOK_ASK = "Whether smiles-front.png matches the rung B ladder image. Only the owner can judge the look."


class Shooting(fake_route.Script):
    """The fake writer also saves a screenshot, from its `shots`-th write on (class attribute: 0 = never)."""
    first_shot = 0

    def reply(self, role, prompt, schema, cwd, *a, **kw):
        if role == "worker" and self.first_shot and sum(c[0] == "worker" for c in self.calls) + 1 >= self.first_shot:
            d = Path(cwd, ".task", "t-1", "evidence")
            d.mkdir(parents=True, exist_ok=True)
            (d / "home-screen.png").write_bytes(b"PNG fake")
        return super().reply(role, prompt, schema, cwd, *a, **kw)


class LookTest(unittest.TestCase):
    setUp, tearDown, commit_base_cfg, fake_bd, run_engine = (
        T.EngineTest.setUp, T.EngineTest.tearDown, T.EngineTest.commit_base_cfg, T.EngineTest.fake_bd,
        T.EngineTest.run_engine)

    def go(self, answers, first_shot=0, bead=BEAD, **cfg):
        script = type("S", (Shooting,), {"first_shot": first_shot})
        with mock.patch.object(fake_route, "Script", script), mock.patch.object(tl, "show", return_value=bead):
            return self.run_engine(answers, **cfg)

    def creates(self):
        return [c for c in self.bd_calls if c[0] == "create"]

    def test_glob_include_exclude(self):
        vp = {"include": ["client/Assets/Features/**", "client/Assets/**/*.{uss,uxml}", "client/Assets/*.asset"],
              "exclude": ["client/Assets/Tests/**", "**/*.md", "**/*.meta"]}
        yes = ["client/Assets/Features/Live/LiveScreen.cs", "client/Assets/Kit/a/b.uss", "client/Assets/x.asset"]
        no = ["client/Assets/Tests/Features/T.cs", "client/Assets/Features/README.md", "client/Assets/Features/A.cs.meta",
              "client/Assets/Kit/a/b.cs", "client/Assets/sub/x.asset", "tools/x.py"]
        self.assertTrue(all(engine.visual_hit(vp, [p]) for p in yes))
        self.assertFalse(any(engine.visual_hit(vp, [p]) for p in no))
        self.assertFalse(engine.visual_hit({}, yes))

    def test_a_visual_stage_brief_asks_for_screenshots_and_a_logic_only_reason(self):
        rc, s = self.go({"plan": [PLAN], "write": [WRITE], "review": [dict(CLEAN)]}, first_shot=1, visual_paths=VISUAL)
        self.assertEqual(rc, 0, self.blocked)
        write, review = s.prompts[1], s.prompts[2]
        self.assertIn("screenshot of every changed screen or state", write)
        self.assertIn(str(self.eng.evidence_dir), write)
        self.assertIn("logic_only", write)
        self.assertIn("home-screen.png", review)
        self.assertIn("done-when", review)

    def test_no_rules_without_visual_paths(self):
        rc, s = self.go({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertNotIn("screenshot of every changed", s.prompts[1])
        self.assertNotIn("changes how something looks", s.prompts[2])
        self.assertEqual(self.creates(), [])
        item = {"what": LOOK_ASK, "kind": "requirement"}  # no rule: the owner is asked as before
        rc, _ = self.go({"plan": [PLAN], "write": [WRITE], "review": [dict(CLEAN, unchecked=[item])],
                         "verify": [{"items": [verdict(1, "open", why="a person must look")]}]})
        self.assertEqual(rc, 2)
        self.assertEqual(self.ask()["kind"], "verify")

    ask = T.EngineTest.ask

    def test_no_screenshot_and_no_reason_is_a_medium_finding(self):
        rc, s = self.go({"plan": [PLAN], "write": [WRITE, WRITE], "review": [dict(CLEAN), dict(CLEAN)]}, first_shot=2,
                        visual_paths=VISUAL)
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer", "worker", "reviewer"])
        self.assertIn("saved no screenshot", s.prompts[3])  # the writer is told, with the finding's fix
        self.assertIn("[medium]", " ".join(c[3] for c in self.bd_calls if c[:2] == ("comments", "add")))

    def test_a_logic_only_reason_is_shown_to_the_reviewer_and_stands(self):
        w = dict(WRITE, logic_only="only the save format changes; no screen differs")
        rc, s = self.go({"plan": [PLAN], "write": [w], "review": [dict(CLEAN)]}, visual_paths=VISUAL)
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer"])
        self.assertIn("only the save format changes", s.prompts[2])
        self.assertEqual(self.creates(), [])  # no screenshots, no owner-look bead

    def test_a_look_item_is_never_asked_and_a_mismatch_goes_to_the_writer(self):
        item = {"what": LOOK_ASK, "kind": "other"}
        r = dict(CLEAN, unchecked=[item], look="front smile matches")
        rc, s = self.go({"plan": [PLAN], "write": [WRITE, WRITE], "review": [r, CLEAN], "verify": [
            {"items": [verdict(1, "open", why="I cannot tell the rung")]}]}, first_shot=1, visual_paths=VISUAL)
        self.assertEqual(rc, 0, self.blocked)
        self.assertIsNone(self.ask())
        self.assertIn("never open", s.prompts[3])
        self.assertIn("open each one and name the file", s.prompts[4])
        self.assertNotIn(("label", "add", "t-1", "needs-owner-check"), [c[:4] for c in self.bd_calls])
        # a mismatch: one fix round, no ask
        self.bd_calls.clear()
        rc, s = self.go({"plan": [PLAN], "write": [WRITE, WRITE], "review": [r, CLEAN], "verify": [
            {"items": [verdict(1, "wrong", why="the smile is flat against rung B")]}]}, first_shot=1, visual_paths=VISUAL)
        self.assertEqual(rc, 0, self.blocked)
        self.assertIn("the smile is flat against rung B", s.prompts[4])
        self.assertIsNone(self.ask())

    def test_a_look_item_with_no_screenshots_is_a_defect_not_an_ask(self):
        item = {"what": LOOK_ASK, "kind": "other"}
        w = dict(WRITE, logic_only="no screen differs")
        rc, s = self.go({"plan": [PLAN], "write": [w, w], "review": [dict(CLEAN, unchecked=[item]), CLEAN],
                         "verify": [{"items": [verdict(1, "open", why="nothing to look at")]}]}, visual_paths=VISUAL)
        self.assertIsNone(self.ask())
        self.assertIn("no screenshot to judge the look from", s.prompts[4])

    def test_land_commits_the_screenshots_and_files_the_owner_look_bead(self):
        bead = dict(BEAD, parent="t-0")
        r = dict(CLEAN, look="The home screen shows the new button, matching the reference.")
        rc, s = self.go({"plan": [PLAN], "write": [WRITE], "review": [r]}, first_shot=1, bead=bead,
                        visual_paths=VISUAL, evidence_dir="design/look-reviews")
        self.assertEqual(rc, 0, self.blocked)
        shot = "design/look-reviews/t-1/home-screen.png"
        self.assertEqual(tl.git("show", "origin/main:" + shot, cwd=str(self.wt)), "PNG fake")
        (c,) = self.creates()
        self.assertEqual(c[1], "Look review: Add f")
        self.assertEqual(c[c.index("--labels") + 1], "owner-look")
        self.assertEqual(c[c.index("--parent") + 1], "t-0")
        self.assertIn("related:t-1", c)
        self.assertIn("--no-inherit-labels", c)
        body = c[c.index("--description") + 1]
        self.assertIn(shot, body)
        self.assertIn("matching the reference", body)

    def test_a_non_visual_answer_needs_no_look_field_and_a_visual_one_does(self):
        w = {k: v for k, v in WRITE.items() if k != "logic_only"}
        r = {k: v for k, v in CLEAN.items() if k != "look"}
        self.assertEqual(engine.validate(w, engine.schema_for("write")), [])
        self.assertEqual(engine.validate(r, engine.schema_for("review")), [])
        self.assertEqual(engine.schema_for("write"), engine.SCHEMAS["write"])
        self.assertEqual(engine.validate(w, engine.schema_for("write", True)), ["$.logic_only: missing"])
        self.assertEqual(engine.validate(r, engine.schema_for("review", True)), ["$.look: missing"])
        self.assertEqual(engine.validate(WRITE, engine.schema_for("write", True)), [])
        self.assertNotIn("logic_only", engine.SCHEMAS["write"]["properties"])  # the shared contract is not changed

    def test_a_settled_look_item_must_name_a_screenshot(self):
        item = {"what": LOOK_ASK, "kind": "other"}
        r = dict(CLEAN, unchecked=[item], look="ok")
        rc, s = self.go({"plan": [PLAN], "write": [WRITE, WRITE], "review": [r, CLEAN], "verify": [
            {"items": [verdict(1, "settled", evidence="looks fine to me")]}]}, first_shot=1, visual_paths=VISUAL)
        self.assertEqual(rc, 0, self.blocked)
        self.assertIsNone(self.ask())
        self.assertIn("names no screenshot file", s.prompts[4])  # back to the writer once
        rc, s = self.go({"plan": [PLAN], "write": [WRITE], "review": [r], "verify": [
            {"items": [verdict(1, "settled", evidence="home-screen.png shows the button")]}]}, first_shot=1,
            visual_paths=VISUAL)
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer", "reviewer"])

    def test_an_open_look_item_goes_back_once_then_the_run_moves_on_and_the_bead_says_so(self):
        item = {"what": LOOK_ASK, "kind": "other"}
        r = dict(CLEAN, unchecked=[item], look="front smile")
        opn = {"items": [verdict(1, "open", why="cannot tell the rung")]}
        rc, s = self.go({"plan": [PLAN], "write": [WRITE, WRITE], "review": [r, r], "verify": [opn, opn]},
                        first_shot=1, visual_paths=VISUAL, evidence_dir="design/look-reviews")
        self.assertEqual(rc, 0, self.blocked)
        self.assertIsNone(self.ask())
        self.assertEqual(len([c for c in s.calls if c[0] == "worker"]), 2)  # one fix round, not more
        (c,) = self.creates()
        self.assertIn("agent could not judge: cannot tell the rung", c[c.index("--description") + 1])

    def test_a_re_land_updates_the_owner_look_bead_instead_of_filing_again(self):
        bead = dict(BEAD, parent="t-0")
        rc, s = self.go({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, first_shot=1, bead=bead,
                        visual_paths=VISUAL, evidence_dir="design/look-reviews")
        self.assertEqual(rc, 0, self.blocked)
        self.bd_calls.clear()
        self.eng.look_notes, self.eng.look_filed = ["second look"], False  # a later run
        rows = [{"id": "t-9"}]
        shows = {"t-9": {"id": "t-9", "dependencies": [{"id": "t-1", "dependency_type": "related"}]}}
        real = self.fake_bd
        def bd(*a, **kw):
            r = real(*a, **kw)
            if a[0] == "list":
                r.stdout = json.dumps(rows)
            return r
        with mock.patch.object(tl, "bd", side_effect=bd), mock.patch.object(tl, "show", side_effect=lambda i, **k: shows.get(i, {})):
            self.eng.file_owner_look()
        self.assertEqual(self.creates(), [])
        (u,) = [c for c in self.bd_calls if c[0] == "update"]
        self.assertEqual(u[1], "t-9")
        self.assertIn("second look", u[3])

    def test_the_look_survives_a_crash_after_the_land(self):
        with mock.patch.object(engine.Engine, "close"), mock.patch.object(engine.Engine, "file_owner_look",
                                                                          side_effect=SystemExit):
            with self.assertRaises(SystemExit):  # the process died after the push: no close, the checkpoint stays
                self.go({"plan": [PLAN], "write": [WRITE], "review": [dict(CLEAN, look="matches")]}, first_shot=1,
                        visual_paths=VISUAL, evidence_dir="design/look-reviews")
        self.assertEqual(self.creates(), [])
        saved = json.loads(self.eng.checkpoint_path().read_text())
        self.assertEqual(saved["look_paths"], ["design/look-reviews/t-1/home-screen.png"])
        eng2 = engine.Engine("t-1", str(self.wt), dict(self.eng.cfg))
        eng2.reset(BEAD)
        eng2.bead_title = "Add f"
        eng2.resume_point()
        self.assertEqual(eng2.look_paths, saved["look_paths"])
        self.assertEqual(eng2.look_notes, ["matches"])
        with mock.patch.object(tl, "show", return_value=BEAD):
            eng2.file_owner_look()
        self.assertEqual(len(self.creates()), 1)

    def test_the_epic_is_found_by_walking_the_parents(self):
        self.eng = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        self.eng.bead_parent = "t-3"
        shows = {"t-3": {"id": "t-3", "issue_type": "feature", "parent": "t-2"},
                 "t-2": {"id": "t-2", "issue_type": "epic", "parent": "t-0"}}
        with mock.patch.object(tl, "show", side_effect=lambda i, **k: shows.get(i, {})):
            self.assertEqual(self.eng.look_epic(), "t-2")
        with mock.patch.object(tl, "show", side_effect=lambda i, **k: {}):
            self.assertEqual(self.eng.look_epic(), "t-3")

    def test_shots_are_images_capped_and_sized(self):
        self.eng = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        d = self.eng.evidence_dir
        d.mkdir(parents=True, exist_ok=True)
        (d / "a.png").write_bytes(b"x")
        (d / "b.gif").write_bytes(b"x")
        (d / "big.jpg").write_bytes(b"x" * (engine.MAX_SHOT_BYTES + 1))
        self.assertEqual(self.eng.shots(), ["a.png"])
        for i in range(25):
            (d / ("m%02d.png" % i)).write_bytes(b"x")
        self.assertEqual(len(self.eng.shots()), engine.MAX_SHOTS)

    def test_no_lfs_means_no_copy(self):
        self.eng = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        Path(self.wt, ".gitattributes").write_text("*.png filter=lfs diff=lfs merge=lfs -text\n")
        with mock.patch.object(self.eng, "sh", return_value=(1, "")):
            self.assertFalse(self.eng.lfs_ok(["a.png"]))
        with mock.patch.object(self.eng, "sh", return_value=(0, "")):
            self.assertTrue(self.eng.lfs_ok(["a.png"]))
        self.assertTrue(self.eng.lfs_ok(["a.jpg"]))

    def test_the_dashboard_counts_owner_look_as_waits_on_you(self):
        sys.path.insert(0, str(T.ROOT / "skills" / "task-loop"))
        from dash import graph
        self.assertIn("owner-look", graph.OWNER_LABELS)


if __name__ == "__main__":
    unittest.main()
