"""RunState and its one writer: every field survives a park, adding one is one edit, and nothing else writes the record."""
import dataclasses
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402,F401
from taskloop.app.run.resume import KEEP_FOR_ACTIVE, LATE, Resume  # noqa: E402
from taskloop.app.run.state import Checkpoints, StateAttrs, carries_state, state_names  # noqa: E402
from taskloop.contracts.checkpoint import Checkpoint, RunState
from taskloop.contracts.review import Unfiled  # noqa: E402
from taskloop.contracts.review import ReviewState  # noqa: E402
from taskloop.stores.memory import fake_stores  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
# a value that is not the default, for each field: the park test fails on a new field until it is listed here
SAMPLE: dict[str, Any] = {
    "plan_data": {"summary": "s", "stages": []}, "brief_hash": "b", "snap": {"title": "t"}, "planner_ref": "ref", "planned": 2, "replans": 1,
    "fixes": 1, "extra": 1, "rebase_resets": 1, "plan_log": [{"mode": "plan"}], "done": ["g"], "accepted": [0], "accepted_new": ["f.txt"],
    "denials": ["rm"], "writer": {"delegate": "w1", "ctx": 5, "seen": ["a"]}, "writer_family": "codex", "writer_fallback": True,
    "fallback_lane": "L", "writer_said": "said", "look_paths": ["p.png"],
    "look_notes": ["n"], "look_unjudged": {"i": "why"}, "look_done": 1, "look_prev": [{"item": "i"}], "rendered_names": {"a.png"},
    "last_reqs": [{"method": "m"}], "render_stale": True, "handoff": {"rounds": [{"r": 1}], "seen_lows": ["l"]}, "stage_tree": "T",
    "pending_land_validation": "red",
}


@carries_state
class Host(StateAttrs):
    def __init__(self) -> None:
        self.state = RunState()
        self.bead, self.stores = "t-1", fake_stores()
        self.checkpoints = Checkpoints(self)
        self.log_path = Path("t-1-20260101-000000.jsonl")
        self.unchecked = [{"what": "u", "kind": "", "source": "", "why": "", "proof_round": False}]
        self.unverified, self.filed, self.unfiled = [{"what": "v", "kind": "", "why": "", "source": ""}], [], []
        self.look_paths, self.look_notes, self.look_unjudged = [], [], {}
        self.task_branch, self.gate_log, self.head = "task/t-1", None, "h0"

    def git(self, *args: str) -> str:
        return self.head

    checkout = SimpleNamespace(branch_now=lambda: "task/t-1")


def stored(h: Host) -> Checkpoint:
    ck = h.checkpoints.read()
    assert ck is not None
    return ck


class Fields(unittest.TestCase):
    def test_the_sample_names_every_field_so_a_new_one_cannot_pass_unnoticed(self):
        self.assertEqual(set(SAMPLE), set(state_names()))

    def test_the_engine_reads_and_writes_every_field_through_the_state(self):
        h = Host()
        for name in state_names():
            setattr(h, name, SAMPLE[name])
            self.assertIs(getattr(h.state, name), SAMPLE[name], name)

    def test_the_dump_holds_every_field_and_nothing_else(self):
        dump = RunState().dump()
        self.assertEqual(set(dump), {f.name for f in dataclasses.fields(RunState)})
        self.assertEqual(set(dump["review"]), {f.name for f in dataclasses.fields(ReviewState)})

    def test_a_dump_loads_back_to_the_same_state(self):
        s = RunState(**SAMPLE)
        self.assertEqual(RunState.from_dump(s.dump()), s)


class Park(unittest.TestCase):
    """Everything that survives a park: saved by the one writer, handed back by the resume."""

    def parked(self) -> tuple[Host, Host]:
        a = Host()
        for name in state_names():
            setattr(a, name, SAMPLE[name])
        a.filed, a.unfiled = ["x"], [Unfiled(title="t", why="w")]
        a.checkpoints.save(step="write", stage=1, rounds=2, n=3, feedback="fb")
        b = Host()
        b.stores = a.stores
        return a, b

    def test_every_field_but_the_run_s_own_comes_back_after_a_park(self):
        a, b = self.parked()
        b.state.snap, b.state.brief_hash, b.state.plan_data = {"now": 1}, "now", None
        ck = stored(b)
        Resume(b).restore(ck, late=True)
        kept = set(KEEP_FOR_ACTIVE)
        for name in state_names():
            if name in kept:
                continue
            want = a.state.pending_land_validation if name == "pending_land_validation" else getattr(a.state, name)
            self.assertEqual(getattr(b, name), want, name)
        self.assertEqual((b.snap, b.brief_hash), ({"now": 1}, "now"))  # the bead as it is now, not as it was planned
        self.assertEqual((b.unverified, b.filed, b.unfiled), (a.unverified, a.filed, a.unfiled))  # the ReviewState folds them in

    def test_an_edit_from_outside_hands_back_only_what_every_resume_keeps(self):
        a, b = self.parked()
        Resume(b).restore(stored(b), late=False)
        for name in LATE:
            self.assertEqual(getattr(b, name), getattr(RunState(), name), name)
        self.assertEqual((b.filed, b.unfiled), ([], []))  # filed titles are the late ones too
        self.assertEqual(b.look_paths, ["p.png"])

    def test_a_pending_land_validation_parks_at_land_verify_red(self):
        a, _ = self.parked()
        ck = stored(a)
        self.assertEqual((ck.step, ck.feedback), ("land-verify-red", "red"))

    def test_close_keeps_the_head_and_the_filed_titles(self):
        a, _ = self.parked()
        a.head = "h9"
        a.filed.append("y")
        a.checkpoints.close()
        ck = stored(a)
        self.assertEqual((ck.closed, ck.head, ck.state.review.filed), (True, "h9", ["x", "y"]))

    def test_a_red_gate_at_land_parks_the_next_run_at_gate_red(self):
        a, _ = self.parked()
        a.state.pending_land_validation = ""
        a.checkpoints.save(step="land")
        a.checkpoints.close("gate red on the rebased tree")
        self.assertEqual(stored(a).step, "gate-red")

    def test_refused_follow_ups_are_kept_beside_the_filed_ones(self):
        a, _ = self.parked()
        a.checkpoints.keep_filed([{"title": "t2", "why": "lint"}])
        self.assertEqual([u.title for u in stored(a).state.review.unfiled], ["t", "t2"])

    def test_drop_removes_the_record(self):
        a, _ = self.parked()
        a.checkpoints.drop()
        self.assertIsNone(a.checkpoints.read())


class OneWriter(unittest.TestCase):
    def test_nothing_but_the_writer_writes_a_checkpoint(self):
        """The record is written only by app/run/state.py (and the stores that hold it): no other src or engine code opens it."""
        hits = []
        for path in [*ROOT.joinpath("src").rglob("*.py"), *ROOT.joinpath("skills/task-loop").glob("*.py")]:
            rel = path.relative_to(ROOT).as_posix()
            text = path.read_text(encoding="utf-8")
            if ("stores.checkpoints" in text or "checkpoints.of(" in text or "cfg.checkpoint(" in text) and rel not in OK:
                hits.append(rel)
        self.assertEqual(hits, [])


OK = {"src/taskloop/app/run/state.py", "src/taskloop/stores/books.py", "src/taskloop/stores/real.py", "src/taskloop/stores/memory.py",
      "skills/task-loop/engine.py"}  # engine.py: the sibling's plan is read (siblings()), never written


if __name__ == "__main__":
    unittest.main()
