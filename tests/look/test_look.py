"""tl-bxk.10.23: look and feel. A visual change saves screenshots; the agent judges them; the land keeps them as artifacts
(never in the repo) and files an owner-look bead for the owner's later round."""
import os
import sys
import unittest
from pathlib import Path
from typing import Any, cast
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import engine_case as T
from support import fake_route, gitq, homes
from support.builders import make_engine
from support.checkpoints import read_ck
from support.engine_case import BEAD, CLEAN, PLAN, WRITE, engine, verdict
from support.fakes import must_bead
from support.spawn import port_git, real_spawner
from support.who import who

from taskloop.app.look import shots
from taskloop.app.look.owner_look import OwnerLook
from taskloop.app.run.closer import Closer
from taskloop.app.wire import slots as wslots
from taskloop.contracts import answers, wire
from taskloop.contracts.config import RepoProfile, VisualConfig
from taskloop.contracts.env import snapshot
from taskloop.contracts.ids import BeadId

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


class LookTest(T.EngineTest):

    def go(self, answers, first_shot=0, bead=BEAD, **cfg):
        script = type("S", (Shooting,), {"first_shot": first_shot})
        with mock.patch.object(fake_route, "Script", script), self.store.stub(show=bead):
            return self.run_engine(answers, **cfg)

    def creates(self):
        return [c for c in self.bd_calls if c[0] == "create"]

    def test_glob_include_exclude(self):
        vp = VisualConfig(include=["client/Assets/Features/**", "client/Assets/**/*.{uss,uxml}", "client/Assets/*.asset"],
                          exclude=["client/Assets/Tests/**", "**/*.md", "**/*.meta"])
        yes = ["client/Assets/Features/Live/LiveScreen.cs", "client/Assets/Kit/a/b.uss", "client/Assets/x.asset"]
        no = ["client/Assets/Tests/Features/T.cs", "client/Assets/Features/README.md", "client/Assets/Features/A.cs.meta",
              "client/Assets/Kit/a/b.cs", "client/Assets/sub/x.asset", "tools/x.py"]
        self.assertTrue(all(shots.visual_hit(vp, [p]) for p in yes))
        self.assertFalse(any(shots.visual_hit(vp, [p]) for p in no))
        self.assertFalse(shots.visual_hit({}, yes))

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
        self.assertEqual(self.ask()["kind"], "decision")


    def test_no_screenshot_and_no_reason_is_a_warning_never_a_send_back(self):
        rc, s = self.go({"plan": [PLAN], "write": [WRITE], "review": [dict(CLEAN)]}, first_shot=2, visual_paths=VISUAL)
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer"])
        self.assertIn("saved no screenshot", self.eng.log_path.read_text())

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
        _rc, s = self.go({"plan": [PLAN], "write": [w, w], "review": [dict(CLEAN, unchecked=[item]), CLEAN],
                         "verify": [{"items": [verdict(1, "open", why="nothing to look at")]}]}, visual_paths=VISUAL)
        self.assertIsNone(self.ask())
        self.assertIn("no screenshot to judge the look from", s.prompts[4])

    def test_land_keeps_the_screenshots_as_artifacts_not_in_the_repo_and_files_the_owner_look_bead(self):
        bead = dict(BEAD, parent="t-0")
        r = dict(CLEAN, look="The home screen shows the new button, matching the reference.")
        rc, _s = self.go({"plan": [PLAN], "write": [WRITE], "review": [r]}, first_shot=1, bead=bead, visual_paths=VISUAL)
        self.assertEqual(rc, 0, self.blocked)
        tree = gitq.git("ls-tree", "-r", "--name-only", "origin/main", cwd=str(self.wt))
        self.assertNotIn("home-screen.png", tree)  # pyrefly: ignore[unsupported-operation]
        kept = homes.cfg().artifacts(BeadId("t-1"))
        self.assertEqual((kept / "home-screen.png").read_bytes(), b"PNG fake")
        recs = [i.rec for i in self.eng.stores.run_log(self.eng.run_dir.name).read_from().items if i.rec.kind == "artifacts"]
        self.assertIn(["home-screen.png"], [getattr(x, "names", None) for x in recs])
        (c,) = self.creates()
        self.assertEqual(c[1], "Look review: Add f")
        self.assertEqual(c[c.index("--labels") + 1], "owner-look")
        self.assertEqual(c[c.index("--parent") + 1], "t-0")
        self.assertIn("related:t-1", c)
        self.assertIn("--no-inherit-labels", c)
        body = c[c.index("--description") + 1]
        self.assertIn("[home-screen.png](/api/artifact?bead=t-1&name=home-screen.png)", body)
        self.assertNotIn("design/", body)
        self.assertIn("matching the reference", body)

    def test_before_shots_and_references_come_from_other_beads_artifacts_of_the_same_prefix(self):
        self.eng = engine.Engine(
            BeadId("t-1"),
            str(self.wt),
            wslots.load_cfg(str(self.wt), port_git()),
            store=self.store,
            env=snapshot(),
            spawner=real_spawner(),
            git=port_git(), who=who())
        self.eng.run_dir.mkdir(parents=True, exist_ok=True)
        (self.eng.run_dir / "brief.md").write_text("no pictures named")
        root = homes.cfg()
        for bead, data in (("t-0", b"old"), ("t-1", b"mine"), ("zz-9", b"other repo")):
            root.artifacts(BeadId(bead)).mkdir(parents=True)
            (root.artifacts(BeadId(bead)) / "home.png").write_bytes(data)
        os.utime(root.artifacts(BeadId("t-0")) / "home.png", (1, 1))
        root.artifacts(BeadId("t-5")).mkdir(parents=True)
        (root.artifacts(BeadId("t-5")) / "home.png").write_bytes(b"newer")
        self.assertEqual(self.eng.pictures.before_shot("home.png"), root.artifacts(BeadId("t-5")) / "home.png")
        self.assertIsNone(self.eng.pictures.before_shot("nothing.png"))
        text = self.eng.pictures.references_text()
        self.assertIn(str(root.artifacts(BeadId("t-0")) / "home.png"), text)
        self.assertIn(str(root.artifacts(BeadId("t-5")) / "home.png"), text)
        self.assertNotIn("zz-9", text)
        self.assertNotIn(str(root.artifacts(BeadId("t-1"))), text)

    def test_a_profile_that_still_sets_evidence_dir_is_refused(self):
        with self.assertRaises(Exception) as cm:
            wire.load(RepoProfile, {"engine": {"evidence_dir": "design/look-reviews"}})
        self.assertIn("evidence_dir", str(cm.exception))

    def test_a_non_visual_answer_needs_no_look_field_and_a_visual_one_does(self):
        w = {k: v for k, v in WRITE.items() if k != "logic_only"}
        r = {k: v for k, v in CLEAN.items() if k != "look"}
        self.assertEqual(answers.check("write", False, w), [])
        self.assertEqual(answers.check("review", False, r), [])
        self.assertEqual(answers.check("write", True, w), ["WriteAnswerLook.logic_only: missing"])
        self.assertEqual(answers.check("review", True, r), ["ReviewAnswerLook.look: missing"])
        self.assertEqual(answers.check("write", True, WRITE), [])
        self.assertNotIn("logic_only", answers.schema_for("write")["properties"])  # the shared contract is not changed

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
                        first_shot=1, visual_paths=VISUAL)
        self.assertEqual(rc, 0, self.blocked)
        self.assertIsNone(self.ask())
        self.assertEqual(len([c for c in s.calls if c[0] == "worker"]), 2)  # one fix round, not more
        (c,) = self.creates()
        self.assertIn("agent could not judge: cannot tell the rung", c[c.index("--description") + 1])

    def test_a_re_land_updates_the_owner_look_bead_instead_of_filing_again(self):
        bead = dict(BEAD, parent="t-0")
        rc, _s = self.go({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, first_shot=1, bead=bead,
                        visual_paths=VISUAL)
        self.assertEqual(rc, 0, self.blocked)
        self.bd_calls.clear()
        cast(Any, self.eng).look_notes, self.eng.look_filed = ["second look"], False  # a later run
        self.store.put({"id": "t-9", "labels": ["owner-look"], "dependencies": [{"id": "t-1", "type": "related"}]})
        self.eng.owner_look.file_owner_look()
        self.assertEqual(self.creates(), [])
        (u,) = [c for c in self.bd_calls if c[0] == "update"]
        self.assertEqual(u[1], "t-9")
        self.assertIn("second look", u[3])

    def test_the_look_survives_a_crash_after_the_land(self):
        with (mock.patch.object(Closer, "close"), mock.patch.object(OwnerLook, "file_owner_look", side_effect=SystemExit),
              self.assertRaises(SystemExit)):  # the process died after the push: no close, the checkpoint stays
            self.go({"plan": [PLAN], "write": [WRITE], "review": [dict(CLEAN, look="matches")]}, first_shot=1,
                    visual_paths=VISUAL)
        self.assertEqual(self.creates(), [])
        saved = read_ck(self.eng).state
        self.assertEqual(saved.look_paths, ["home-screen.png"])
        eng2 = engine.Engine(
            BeadId("t-1"), str(self.wt), self.eng.cfg, store=self.store, env=snapshot(), spawner=real_spawner(), git=port_git(), who=who()
        )
        eng2.tree.reset(must_bead(BEAD))
        eng2.bead_title = "Add f"
        eng2.resume.point()
        self.assertEqual(eng2.look_paths, saved.look_paths)
        self.assertEqual(eng2.look_notes, ["matches"])
        with self.store.stub(show=BEAD):
            eng2.owner_look.file_owner_look()
        self.assertEqual(len(self.creates()), 1)

    def test_the_epic_is_found_by_walking_the_parents(self):
        self.eng = make_engine(self.wt, store=self.store, attrs={"bead_parent": "t-3"})
        shows = {"t-3": {"id": "t-3", "issue_type": "feature", "parent": "t-2"},
                 "t-2": {"id": "t-2", "issue_type": "epic", "parent": "t-0"}}
        with self.store.stub(show_fn=lambda i, **k: shows.get(i, {})):
            self.assertEqual(self.eng.owner_look.look_epic(), "t-2")
        with self.store.stub(show_fn=lambda i, **k: {}):
            self.assertEqual(self.eng.owner_look.look_epic(), "t-3")

    def test_shots_are_images_capped_and_sized(self):
        self.eng = engine.Engine(
            BeadId("t-1"),
            str(self.wt),
            wslots.load_cfg(str(self.wt), port_git()),
            store=self.store,
            env=snapshot(),
            spawner=real_spawner(),
            git=port_git(), who=who())
        d = self.eng.evidence_dir
        d.mkdir(parents=True, exist_ok=True)
        (d / "a.png").write_bytes(b"x")
        (d / "b.gif").write_bytes(b"x")
        (d / "big.jpg").write_bytes(b"x" * (shots.MAX_SHOT_BYTES + 1))
        self.assertEqual(self.eng.pictures.shots(), ["a.png"])
        for i in range(25):
            (d / (f"m{int(i):02d}.png")).write_bytes(b"x")
        self.assertEqual(len(self.eng.pictures.shots()), shots.MAX_SHOTS)

if __name__ == "__main__":
    unittest.main()
