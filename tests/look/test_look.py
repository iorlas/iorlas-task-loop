"""tl-bxk.10.23: look and feel. A visual change saves screenshots; the agent judges them; the land keeps them as artifacts
(never in the repo) and files an owner-look bead for the owner's later round."""
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import engine_case as T
from support import gitq
from support.engine_case import engine
from support.fakes import must_bead
from support.plans import BEAD, CLEAN, PLAN, WRITE, verdict
from support.spawn import port_git, real_spawner
from support.who import who

from taskloop.app.look import shots
from taskloop.app.look.owner_look import OwnerLook
from taskloop.app.pipeline.closing import Closer
from tlkernel import answers, wire
from tlkernel.artifact import ArtifactMeta
from tlkernel.config import RepoProfile, VisualConfig
from tlkernel.env import snapshot
from tlkernel.ids import BeadId
from tltestkit import fake_route

VISUAL = {"include": ["*.txt"], "exclude": ["docs/**"]}
LOOK_ASK = "Whether smiles-front.png matches the rung B ladder image. Only the owner can judge the look."


def kept_one(run="RUN"):
    """The one picture the run's store lists, as Pictures.show_pictures returns it."""
    meta = ArtifactMeta(name="home-screen.png", caption="c", role="result", kind="png", size=8, sha256="0" * 64, created=1.0)
    return mock.patch.object(shots.Pictures, "show_pictures", return_value=[(f"artifact:repo/t-1/{run}/look-1/home-screen.png", meta)])


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
        assert all(shots.visual_hit(vp, [p]) for p in yes)
        assert not any(shots.visual_hit(vp, [p]) for p in no)
        assert not shots.visual_hit({}, yes)

    def test_a_visual_stage_brief_asks_for_screenshots_and_a_logic_only_reason(self):
        rc, s = self.go({"plan": [PLAN], "write": [WRITE], "review": [dict(CLEAN)]}, first_shot=1, visual_paths=VISUAL)
        assert rc == 0, self.blocked
        write, review = s.prompts[1], s.prompts[2]
        assert "screenshot of every changed screen or state" in write
        assert str(self.eng.evidence_dir) in write
        assert "logic_only" in write
        assert "home-screen.png" in review
        assert "done-when" in review

    def test_no_rules_without_visual_paths(self):
        rc, s = self.go({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        assert rc == 0, self.blocked
        assert "screenshot of every changed" not in s.prompts[1]
        assert "changes how something looks" not in s.prompts[2]
        assert self.creates() == []
        item = {"what": LOOK_ASK, "kind": "requirement"}  # no rule: the owner is asked as before
        rc, _ = self.go({"plan": [PLAN], "write": [WRITE], "review": [dict(CLEAN, unchecked=[item])],
                         "verify": [{"items": [verdict(1, "open", why="a person must look")]}]})
        assert rc == 2
        assert self.ask()["kind"] == "decision"


    def test_no_screenshot_and_no_reason_is_a_warning_never_a_send_back(self):
        rc, s = self.go({"plan": [PLAN], "write": [WRITE], "review": [dict(CLEAN)]}, first_shot=2, visual_paths=VISUAL)
        assert rc == 0, self.blocked
        assert [c[0] for c in s.calls] == ["planner", "worker", "reviewer"]
        assert "saved no screenshot" in self.eng.log_path.read_text()

    def test_a_logic_only_reason_is_shown_to_the_reviewer_and_stands(self):
        w = dict(WRITE, logic_only="only the save format changes; no screen differs")
        rc, s = self.go({"plan": [PLAN], "write": [w], "review": [dict(CLEAN)]}, visual_paths=VISUAL)
        assert rc == 0, self.blocked
        assert [c[0] for c in s.calls] == ["planner", "worker", "reviewer"]
        assert "only the save format changes" in s.prompts[2]
        assert self.creates() == []  # no screenshots, no owner-look bead

    def test_a_look_item_is_never_asked_and_a_mismatch_goes_to_the_writer(self):
        item = {"what": LOOK_ASK, "kind": "other"}
        r = dict(CLEAN, unchecked=[item], look="front smile matches")
        rc, s = self.go({"plan": [PLAN], "write": [WRITE, WRITE], "review": [r, CLEAN], "verify": [
            {"items": [verdict(1, "open", why="I cannot tell the rung")]}]}, first_shot=1, visual_paths=VISUAL)
        assert rc == 0, self.blocked
        assert self.ask() is None
        assert "never open" in s.prompts[3]
        assert "open each one and name the file" in s.prompts[4]
        assert ("label", "add", "t-1", "needs-owner-check") not in [c[:4] for c in self.bd_calls]
        # a mismatch: one fix round, no ask
        self.bd_calls.clear()
        rc, s = self.go({"plan": [PLAN], "write": [WRITE, WRITE], "review": [r, CLEAN], "verify": [
            {"items": [verdict(1, "wrong", why="the smile is flat against rung B")]}]}, first_shot=1, visual_paths=VISUAL)
        assert rc == 0, self.blocked
        assert "the smile is flat against rung B" in s.prompts[4]
        assert self.ask() is None

    def test_a_look_item_with_no_screenshots_is_a_defect_not_an_ask(self):
        item = {"what": LOOK_ASK, "kind": "other"}
        w = dict(WRITE, logic_only="no screen differs")
        _rc, s = self.go({"plan": [PLAN], "write": [w, w], "review": [dict(CLEAN, unchecked=[item]), CLEAN],
                         "verify": [{"items": [verdict(1, "open", why="nothing to look at")]}]}, visual_paths=VISUAL)
        assert self.ask() is None
        assert "no screenshot to judge the look from" in s.prompts[4]

    def test_land_keeps_the_screenshots_as_artifacts_not_in_the_repo_and_files_the_owner_look_bead(self):
        bead = dict(BEAD, parent="t-0")
        r = dict(CLEAN, look="The home screen shows the new button, matching the reference.")
        with kept_one():
            rc, _s = self.go({"plan": [PLAN], "write": [WRITE], "review": [r]}, first_shot=1, bead=bead, visual_paths=VISUAL)
        assert rc == 0, self.blocked
        tree = gitq.git("ls-tree", "-r", "--name-only", "origin/main", cwd=str(self.wt))
        assert "home-screen.png" not in tree  # pyrefly: ignore[unsupported-operation]
        (c,) = self.creates()
        assert c[1] == "Look review: Add f"
        assert c[c.index("--labels") + 1] == "owner-look"
        assert c[c.index("--parent") + 1] == "t-0"
        assert "related:t-1" in c
        assert "--no-inherit-labels" in c
        body = c[c.index("--description") + 1]
        assert "[home-screen.png](/api/artifact?repo=repo&bead=t-1&run=RUN&stage=look&attempt=1&name=home-screen.png)" in body
        assert "design/" not in body
        assert "matching the reference" in body


    def test_a_profile_that_still_sets_evidence_dir_is_refused(self):
        with pytest.raises(Exception) as cm:
            wire.load(RepoProfile, {"engine": {"evidence_dir": "design/look-reviews"}})
        assert "evidence_dir" in str(cm.value)

    def test_a_non_visual_answer_needs_no_look_field_and_a_visual_one_does(self):
        w = {k: v for k, v in WRITE.items() if k != "logic_only"}
        r = {k: v for k, v in CLEAN.items() if k != "look"}
        assert answers.check("write", False, w) == []
        assert answers.check("review", False, r) == []
        assert answers.check("write", True, w) == ["WriteAnswerLook.logic_only: missing"]
        assert answers.check("review", True, r) == ["ReviewAnswerLook.look: missing"]
        assert answers.check("write", True, WRITE) == []
        assert "logic_only" not in answers.schema_for("write")["properties"]  # the shared contract is not changed

    def test_a_settled_look_item_must_name_a_screenshot(self):
        item = {"what": LOOK_ASK, "kind": "other"}
        r = dict(CLEAN, unchecked=[item], look="ok")
        rc, s = self.go({"plan": [PLAN], "write": [WRITE, WRITE], "review": [r, CLEAN], "verify": [
            {"items": [verdict(1, "settled", evidence="looks fine to me")]}]}, first_shot=1, visual_paths=VISUAL)
        assert rc == 0, self.blocked
        assert self.ask() is None
        assert "names no screenshot file" in s.prompts[4]  # back to the writer once
        rc, s = self.go({"plan": [PLAN], "write": [WRITE], "review": [r], "verify": [
            {"items": [verdict(1, "settled", evidence="home-screen.png shows the button")]}]}, first_shot=1,
            visual_paths=VISUAL)
        assert rc == 0, self.blocked
        assert [c[0] for c in s.calls] == ["planner", "worker", "reviewer", "reviewer"]

    def test_an_open_look_item_goes_back_once_then_the_run_moves_on_and_the_bead_says_so(self):
        item = {"what": LOOK_ASK, "kind": "other"}
        r = dict(CLEAN, unchecked=[item], look="front smile")
        opn = {"items": [verdict(1, "open", why="cannot tell the rung")]}
        rc, s = self.go({"plan": [PLAN], "write": [WRITE, WRITE], "review": [r, r], "verify": [opn, opn]},
                        first_shot=1, visual_paths=VISUAL)
        assert rc == 0, self.blocked
        assert self.ask() is None
        assert len([c for c in s.calls if c[0] == "worker"]) == 2  # one fix round, not more
        (c,) = self.creates()
        assert "agent could not judge: cannot tell the rung" in c[c.index("--description") + 1]

    def test_a_re_land_updates_the_owner_look_bead_instead_of_filing_again(self):
        bead = dict(BEAD, parent="t-0")
        with kept_one():
            rc, _s = self.go({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, first_shot=1, bead=bead,
                            visual_paths=VISUAL)
            assert rc == 0, self.blocked
            self.bd_calls.clear()
            self.eng.look.notes, self.eng.look.filed = ["second look"], False  # a later run
            self.store.put({"id": "t-9", "labels": ["owner-look"], "dependencies": [{"id": "t-1", "type": "related"}]})
            self.eng.owner_look.file_owner_look()
        assert self.creates() == []
        (u,) = [c for c in self.bd_calls if c[0] == "update"]
        assert u[1] == "t-9"
        assert "second look" in u[3]

    def test_the_look_survives_a_crash_after_the_land(self):
        with (mock.patch.object(Closer, "close"), mock.patch.object(OwnerLook, "file_owner_look", side_effect=SystemExit),
              pytest.raises(SystemExit)):  # the process died after the push: no close, the checkpoint stays
            self.go({"plan": [PLAN], "write": [WRITE], "review": [dict(CLEAN, look="matches")]}, first_shot=1,
                    visual_paths=VISUAL)
        assert self.creates() == []
        eng2 = engine.Engine(
            BeadId("t-1"), str(self.wt), self.eng.cfg, store=self.store, env=snapshot(), spawner=real_spawner(), git=port_git(), who=who()
        )
        eng2.tree.reset(must_bead(BEAD))
        eng2.bead_title = "Add f"
        eng2.resume.point()
        assert eng2.look.notes == ["matches"]
        with kept_one(), self.store.stub(show=BEAD):  # the pictures are the store's, so a restart finds them where they were
            eng2.owner_look.file_owner_look()
        assert len(self.creates()) == 1
