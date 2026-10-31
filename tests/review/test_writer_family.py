"""engine.writer_family [openai] with the review off: every worker call carries --only-family openai, no call of the loop reaches the
claude family except the planner and reflect roles, and a stop of the pin is a paused run with the reason in words."""
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support import engine_case as T
from support import fake_route
from support.engine_case import BEAD, CLEAN, HAS_F, PLAN, WRITE, adhoc

CASE = {"criterion": "the file f.txt exists", "check": adhoc(HAS_F), "class": "test"}
COVERED = dict(PLAN, cases=[CASE])


def flag(argv, name):
    return [argv[i + 1] for i, x in enumerate(argv) if x == name]


class WriterFamily(unittest.TestCase):
    eng: Any
    store: Any
    setUp: Any = T.EngineTest.setUp
    tearDown: Any = T.EngineTest.tearDown
    fake_bd: Any = T.EngineTest.fake_bd
    run_engine: Any = T.EngineTest.run_engine
    ask: Any = T.EngineTest.ask

    def go(self, answers, bead=BEAD, **cfg):
        with self.store.stub(show=bead):
            return self.run_engine(answers, **cfg)

    def test_every_worker_call_carries_the_pin_and_no_other_role_does(self):
        rc, s = self.go({"plan": [COVERED], "write": [WRITE], "review": [CLEAN]}, writer_family=["openai"])
        self.assertEqual(rc, 0)
        by_role = {(a[3], n): flag(a, "--only-family") for a, n in zip(s.argvs, s.nodes, strict=True)}
        self.assertEqual(by_role[("worker", "write")], ["openai"])
        self.assertEqual({k: v for k, v in by_role.items() if k[0] != "worker"}, {("planner", "plan"): [], ("reviewer", "review"): []})

    def test_no_pin_no_flag(self):
        rc, s = self.go({"plan": [COVERED], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual((rc, [flag(a, "--only-family") for a in s.argvs]), (0, [[], [], []]))

    def test_a_bead_label_overrides_the_profile(self):
        _, s = self.go({"plan": [COVERED], "write": [WRITE], "review": [CLEAN]}, bead=dict(BEAD, labels=["visual", "writer-family:xai"]),
                       writer_family=["openai"])
        self.assertEqual([flag(a, "--only-family") for a, n in zip(s.argvs, s.nodes, strict=True) if n == "write"], [["xai"]])

    def test_pinned_to_openai_with_the_review_off_the_claude_family_is_reached_by_the_planner_and_reflect_only(self):
        """The call-argv/role table of a whole run. The worker is pinned, so delegate cannot answer it with claude; the reviewer role
        is not called at all (review off), so the only roles left that delegate may place on claude are planner and reflect, and
        none of the argvs names a claude family or a model (no --premium, no Opus)."""
        rc, s = self.go({"plan": [COVERED], "write": [WRITE], "reflect": [{"worth": False, "notes": []}]}, review="off",
                        writer_family=["openai"], reflect=True)
        table = [(a[3], n, flag(a, "--only-family"), flag(a, "--authored-by"), "--premium" in a)
                 for a, n in zip(s.argvs, s.nodes, strict=True)]
        self.assertEqual(rc, 0)
        self.assertEqual(s.nodes, ["plan", "write", "reflect"])
        for role, node, fam, authored, premium in table:
            self.assertNotIn("claude", fam + authored)
            self.assertFalse(premium)
            if role == "worker":
                self.assertEqual((node, fam), ("write", ["openai"]))
            else:
                self.assertIn((role, node), {("planner", "plan"), ("reviewer", "reflect")})  # the reviewer role only as the reflect call
        self.assertNotIn("review", s.nodes)
        self.assertNotIn("verify", s.nodes)
        self.assertFalse(any("opus" in " ".join(a).lower() for a in s.argvs))

    def test_a_pin_delegate_cannot_place_pauses_the_bead_and_says_the_reason(self):
        none = fake_route.stop_answer("no_lane", say="openai logged out")
        rc, _ = self.go({"plan": [COVERED], "write": [none]}, writer_family=["openai"])
        self.assertEqual(rc, 2)
        said = [c[3] for c in self.store.said("comments", "add") if "paused" in c[3]]
        self.assertTrue(said)
        self.assertTrue(all("no ready lane of the pinned writer family (openai) for write (no_lane): openai logged out" in x for x in said))


if __name__ == "__main__":
    unittest.main()
