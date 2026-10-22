"""tl-bxk.10.23: look and feel. A visual change saves screenshots; the agent judges them; the land keeps them in the repo
and files an owner-look bead for the owner's later round."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_engine as T  # noqa: E402
from test_engine import BEAD, CLEAN, PLAN, WRITE, engine, tl, verdict  # noqa: E402

VISUAL = {"include": ["*.txt"], "exclude": ["docs/**"]}
LOOK_ASK = "Whether smiles-front.png matches the rung B ladder image. Only the owner can judge the look."


class Shooting(T.DelegateScript):
    """The fake writer also saves a screenshot, from its `shots`-th write on (class attribute: 0 = never)."""
    first_shot = 0

    def __call__(self, route, role, prompt, schema, cwd, *a, **kw):
        if role == "worker" and self.first_shot and sum(c[0] == "worker" for c in self.calls) + 1 >= self.first_shot:
            d = Path(cwd, ".task", "t-1", "evidence")
            d.mkdir(parents=True, exist_ok=True)
            (d / "home-screen.png").write_bytes(b"PNG fake")
        return super().__call__(route, role, prompt, schema, cwd, *a, **kw)


class LookTest(unittest.TestCase):
    setUp, tearDown, commit_base_cfg, fake_bd, run_engine = (
        T.EngineTest.setUp, T.EngineTest.tearDown, T.EngineTest.commit_base_cfg, T.EngineTest.fake_bd,
        T.EngineTest.run_engine)

    def go(self, answers, first_shot=0, bead=BEAD, **cfg):
        script = type("S", (Shooting,), {"first_shot": first_shot})
        with mock.patch.object(T, "DelegateScript", script), mock.patch.object(tl, "show", return_value=bead):
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
        rc, s = self.go({"plan": [PLAN], "write": [WRITE], "review": [r], "verify": [
            {"items": [verdict(1, "open", why="I cannot tell the rung")]}]}, first_shot=1, visual_paths=VISUAL)
        self.assertEqual(rc, 0, self.blocked)
        self.assertIsNone(self.ask())
        self.assertIn("never open", s.prompts[3])
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

    def test_the_dashboard_counts_owner_look_as_waits_on_you(self):
        sys.path.insert(0, str(T.ROOT / "skills" / "task-loop"))
        from dash import graph
        self.assertIn("owner-look", graph.OWNER_LABELS)


if __name__ == "__main__":
    unittest.main()
