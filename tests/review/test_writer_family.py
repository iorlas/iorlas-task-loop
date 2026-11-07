"""Writer family pins apply only to worker calls; final review remains mandatory with review off. A stop of the pin pauses the run."""
import sys
from pathlib import Path
from typing import Any

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support import engine_case as T
from support.engine_case import adhoc

from tltestkit import fake_route
from tltestkit.plans import BEAD, CLEAN, HAS_F, PLAN, WRITE, verdict

CASE = {"criterion": "the file f.txt exists", "check": adhoc(HAS_F), "class": "test"}
COVERED = dict(PLAN, cases=[CASE, *PLAN["cases"]])


def flag(argv, name):
    return [argv[i + 1] for i, x in enumerate(argv) if x == name]


class WriterFamily(Case):
    eng: Any
    store: Any
    setup_method: Any = T.EngineTest.setup_method
    teardown_method: Any = T.EngineTest.teardown_method
    fake_bd: Any = T.EngineTest.fake_bd
    run_engine: Any = T.EngineTest.run_engine
    ask: Any = T.EngineTest.ask

    def go(self, answers, bead=BEAD, **cfg):
        with self.store.stub(show=bead):
            return self.run_engine(answers, **cfg)

    def test_every_worker_call_carries_the_pin_and_no_other_role_does(self):
        rc, s = self.go({"plan": [COVERED], "write": [WRITE], "review": [CLEAN]}, bead=dict(BEAD, labels=["writer-family:openai"]))
        assert rc == 0
        by_role = {(r.role, n): r.prefer for r, n in zip(s.requests, s.nodes, strict=True)}
        assert by_role[("worker", "write")] == "openai"
        assert {k: v for k, v in by_role.items() if k[0] != "worker"} == {("planner", "plan"): "", ("reviewer", "review"): ""}

    def test_no_pin_no_flag(self):
        rc, s = self.go({"plan": [COVERED], "write": [WRITE], "review": [CLEAN]})
        assert (rc, [flag(a, "--only-family") for a in s.argvs]) == (0, [[], [], []])

    def test_a_bead_label_is_forwarded_as_prefer(self):
        _, s = self.go({"plan": [COVERED], "write": [WRITE], "review": [CLEAN]}, bead=dict(BEAD, labels=["visual", "writer-family:xai"]))
        assert [r.prefer for r, n in zip(s.requests, s.nodes, strict=True) if n == "write"] == ["xai"]

    def test_pinned_writer_with_review_off_still_gets_unpinned_final_review(self):
        """The worker is pinned; planner, final reviewer and reflect retain their own routing policy."""
        rc, s = self.go({"plan": [COVERED], "write": [WRITE], "review": [CLEAN], "reflect": [{"worth": False, "notes": []}]}, review="off",
                        bead=dict(BEAD, labels=["writer-family:openai"]), reflect=True)
        table = [(r.role, n, r.prefer) for r, n in zip(s.requests, s.nodes, strict=True)]
        assert rc == 0
        assert s.nodes == ["plan", "write", "review", "reflect"]
        for role, node, fam in table:
            if role == "worker":
                assert (node, fam) == ("write", "openai")
            else:
                assert (role, node) in {("planner", "plan"), ("reviewer", "review"), ("reviewer", "reflect")}
                assert fam == ""
        assert "verify" not in s.nodes
        assert not any("opus" in " ".join(a).lower() for a in s.argvs)

    def visual_run(self, **cfg):
        gap = {"what": "f.txt exists on a clean checkout", "kind": "checkable"}
        bead = dict(BEAD, labels=["ui"])
        return self.go({"plan": [COVERED], "write": [dict(WRITE, unchecked=[gap])], "review": [dict(CLEAN, unchecked=[gap])],
                        "verify": [{"items": [verdict(1, "settled", evidence="\"x\"")]}]},
                       bead=bead, **cfg)

    def test_a_visual_bead_with_the_review_off_skips_verify_and_look_and_the_close_names_it(self):
        rc, s = self.visual_run(review="off")
        assert rc == 0
        assert s.nodes == ["plan", "write", "review"]
        assert not any("claude" in " ".join(flag(a, "--only-family") + flag(a, "--authored-by")) for a in s.argvs)
        said = [c[3] for c in self.store.said("comments", "add") if "verify and look did not run because review is off" in c[3]]
        assert len(said) == 1
        assert "f.txt exists on a clean checkout" in said[0]
        made = [c for c in self.store.calls if c[0] == "create"]
        assert len(made) == 1
        assert "follow-up" in made[0][made[0].index("--labels") + 1].split(",")
        assert "verify and look were skipped" in " ".join(made[0])

    def test_a_visual_bead_with_the_review_on_still_runs_verify(self):
        rc, s = self.visual_run(review="on")
        assert rc == 0
        assert s.nodes == ["plan", "write", "review", "verify"]

    def test_a_pin_delegate_cannot_place_pauses_the_bead_and_says_the_reason(self):
        none = fake_route.stop_answer("no_lane", say="openai logged out")
        rc, _ = self.go({"plan": [COVERED], "write": [none]}, bead=dict(BEAD, labels=["writer-family:openai"]))
        assert rc == 2
        said = [c[3] for c in self.store.said("comments", "add") if "paused" in c[3]]
        assert said
        assert all("no ready lane of the pinned writer family (openai) for write (no_lane): openai logged out" in x for x in said)
