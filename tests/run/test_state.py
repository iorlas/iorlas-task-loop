"""RunState and its one writer: every field survives a park, adding one is one edit, and nothing else writes the record."""
import json
import sys
import typing
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.fake_beads import FakeBeads
from support.fakegit import ScriptedGit
from support.memstores import fake_stores

from taskloop.app.land.state import LandState
from taskloop.app.look.state import LOOK_FIELDS, LookState
from taskloop.app.review.state import ReviewLive
from taskloop.app.run.sections import checkpoint_hooks, restarted
from taskloop.app.run.state import STATE_ONLY, StateAttrs, attr_names, carries_state, state_names
from taskloop.app.write.state import WriteState
from tlkernel import fence, wire
from tlkernel.checkpoint import BriefSnap, Checkpoint, Handoff, PlanStep, RunState, WriterSession
from tlkernel.ids import BeadId
from tlkernel.review import (
    ReviewState,
    Unfiled,
)
from tlkernel.run import Round
from tlpipeline.api import KEEP_FOR_ACTIVE, LATE, Checkpoints, Resume, ReviewGlue
from tlpipeline.testing import FakeHeadHistory

ROOT = Path(__file__).resolve().parents[2]
# a value that is not the default, for each field: the park test fails on a new field until it is listed here
SAMPLE: dict[str, Any] = {
    "plan_data": {"summary": "s", "stages": []},
    "brief_hash": "b",
    "snap": BriefSnap(fields={"title": "t"}, issue_type="task", deps=[], comments=[]),
    "planner_ref": "ref",
    "planned": 2,
    "replans": 1,
    "fixes": 1,
    "extra": 1,
    "rebase_resets": 1,
    "plan_log": [PlanStep(mode="plan", why="w")],
    "done": ["g"],
    "accepted": [0],
    "accepted_new": ["f.txt"],
    "denials": ["rm"],
    "writer": WriterSession(seen=["a"], last_stage=True),
    "writer_family": "codex",
    "look_notes": ["n"],
    "look_unjudged": {"i": "why"},
    "look_done": 1,
    "rendered_names": ["a.png"],
    "last_reqs": [{"method": "m"}],
    "render_stale": True,
    "handoff": Handoff(rounds=[Round(stage="s", round=1, kind="k", writer="w", open=["o"])], seen_lows=["l"]),
    "stage_tree": "T",
    "pending_land_validation": "red",
    "leftovers": [{"title": "later", "why": "w", "key": "t-1|leftover|later", "origin": "plan"}],
    "followup_ids": {"t-1|leftover|done": "fk-1"},
}


class HeadGit(ScriptedGit):
    def __init__(self, host: Host) -> None:
        super().__init__()
        self.host = host

    def rev_parse(self, d: str, rev: str) -> str:
        return self.host.head


@carries_state
class Host(StateAttrs, SimpleNamespace):
    def __init__(self) -> None:
        self.state = RunState()
        self.dry = False
        self.bead, self.stores = BeadId("t-1"), fake_stores()
        self.store, self.claim = FakeBeads(), fence.offline(BeadId("t-1"))
        self.checkpoints = Checkpoints(self, checkpoint_hooks(lambda: self.state))
        self.run_id = "t-1-20260101-000000"
        self.review = ReviewLive()
        self.review.unchecked = [{"what": "u", "kind": "", "source": "", "why": "", "proof_round": False}]
        self.review.unverified = [{"what": "v", "kind": "", "why": "", "source": ""}]
        self.filed, self.unfiled = [], []
        self.look = LookState(lambda: self.state)
        self.write = WriteState()
        self.task_branch, self.land_state, self.head = "task/t-1", LandState(), "h0"

    @property
    def git(self) -> HeadGit:
        return HeadGit(self)

    wt = "/wt"

    checkout = SimpleNamespace(branch_now=lambda: "task/t-1")


def stored(h: Host) -> Checkpoint:
    ck = h.checkpoints.read()
    assert ck is not None
    return ck


class Fields(Case):
    def test_the_sample_names_every_field_so_a_new_one_cannot_pass_unnoticed(self):
        assert set(SAMPLE) == set(state_names())

    def test_the_engine_declares_every_field_with_the_type_the_state_holds(self):
        declared, held = typing.get_type_hints(StateAttrs), typing.get_type_hints(RunState)
        assert declared == {k: held[k] for k in attr_names()}
        assert set(attr_names()) == set(state_names()) - set(LOOK_FIELDS) - set(STATE_ONLY)
        assert not set(LOOK_FIELDS) & set(declared)  # the look stage's fields are `engine.look`, not engine attributes
        assert not hasattr(StateAttrs, "__getattr__")  # an attribute the state lacks is an error, not an Any

    def test_the_engine_reads_and_writes_every_field_through_the_state(self):
        h = Host()
        for name in attr_names():
            setattr(h, name, SAMPLE[name])
            assert getattr(h.state, name) is SAMPLE[name], name

    def test_the_look_stage_reads_and_writes_its_fields_through_the_same_state(self):
        h = Host()
        for name, attr in zip(LOOK_FIELDS, ("notes", "unjudged", "done", "rendered", "last_reqs"), strict=True):
            setattr(h.look, attr, SAMPLE[name])
            assert getattr(h.state, name) is SAMPLE[name], name
        h.state = RunState()  # a task that starts again replaces the state: the look view follows it
        assert h.look.done == 0

    def test_the_dump_holds_every_field_and_nothing_else(self):
        dump = RunState().dump()
        assert set(dump) == set(wire.names(RunState))
        assert set(dump["review"]) == set(wire.names(ReviewState))

    def test_a_dump_loads_back_to_the_same_state(self):
        s = RunState(**SAMPLE)
        assert RunState.from_dump(s.dump()) == s


class Park(Case):
    """Everything that survives a park: saved by the one writer, handed back by the resume."""

    def parked(self) -> tuple[Host, Host]:
        a = Host()
        for name in state_names():
            setattr(a.state, name, SAMPLE[name])
        a.filed, a.unfiled = ["x"], [Unfiled(title="t", why="w")]
        a.checkpoints.save(step="write", stage=1, rounds=2, n=3, feedback="fb")
        b = Host()
        b.stores = a.stores
        return a, b

    def test_every_field_but_the_run_s_own_comes_back_after_a_park(self):
        a, b = self.parked()
        snap = BriefSnap(fields={"now": "1"}, issue_type="", deps=[], comments=[])
        b.state.snap, b.state.brief_hash, b.state.plan_data = snap, "now", None
        ck = stored(b)
        Resume(b, b, b, FakeHeadHistory(), ReviewGlue(b), state_names()).restore(ck, late=True)
        kept = set(KEEP_FOR_ACTIVE)
        for name in state_names():
            if name in kept:
                continue
            want = a.state.pending_land_validation if name == "pending_land_validation" else getattr(a.state, name)
            assert getattr(b.state, name) == want, name
        assert (b.snap, b.brief_hash) == (snap, "now")  # the bead as it is now, not as it was planned
        assert (b.review.unverified, b.filed, b.unfiled) == (a.review.unverified, a.filed, a.unfiled)  # the ReviewState folds them in

    def test_an_edit_from_outside_hands_back_only_what_every_resume_keeps(self):
        _a, b = self.parked()
        Resume(b, b, b, FakeHeadHistory(), ReviewGlue(b), state_names()).restore(stored(b), late=False)
        for name in LATE:
            assert getattr(b.state, name) == getattr(RunState(), name), name
        assert (b.filed, b.unfiled) == ([], [])  # filed titles are the late ones too

    def test_a_pending_land_validation_parks_at_land_verify_red(self):
        a, _ = self.parked()
        ck = stored(a)
        assert (ck.step, ck.feedback) == ("land-verify-red", "red")

    def test_close_keeps_the_head_and_the_filed_titles(self):
        a, _ = self.parked()
        a.head = "h9"
        a.filed.append("y")
        a.checkpoints.close()
        ck = stored(a)
        assert (ck.closed, ck.head, ck.state.review.filed) == (True, "h9", ["x", "y"])

    def test_a_red_gate_at_land_parks_the_next_run_at_gate_red(self):
        a, _ = self.parked()
        a.state.pending_land_validation = ""
        a.checkpoints.save(step="land")
        a.checkpoints.close("gate red on the rebased tree")
        assert stored(a).step == "gate-red"

    def test_refused_follow_ups_are_kept_beside_the_filed_ones(self):
        a, _ = self.parked()
        a.checkpoints.keep_filed([{"title": "t2", "why": "lint"}])
        assert [u.title for u in stored(a).state.review.unfiled] == ["t", "t2"]

    def test_drop_removes_the_record(self):
        a, _ = self.parked()
        a.checkpoints.drop()
        assert a.checkpoints.read() is None

    def test_pending_followups_survive_an_immediate_crash_and_a_fresh_start(self):
        a = Host()
        a.checkpoints.save(step="write", stage=2)
        a.leftovers.append({"title": "later", "why": "w"})
        a.checkpoints.keep_pending("review")
        ck = stored(a)
        assert (ck.step, ck.stage) == ("write", 2)
        b = Host()
        b.stores = a.stores
        Resume(b, b, b, FakeHeadHistory(), ReviewGlue(b), state_names()).restore(ck, late=False)
        assert b.leftovers == a.leftovers
        assert b.leftovers[0]["origin"] == "review"
        assert restarted(b.state).leftovers == a.leftovers


class OneWriter(Case):
    def test_nothing_but_the_writer_writes_a_checkpoint(self):
        """The record is written only by tlpipeline/checkpoints.py (and the stores that hold it): no other src or engine code opens it."""
        hits = []
        for path in [*ROOT.joinpath("src").rglob("*.py"), *ROOT.joinpath("skills/task-loop").glob("*.py")]:
            rel = path.relative_to(ROOT).as_posix()
            text = path.read_text(encoding="utf-8")
            if ("stores.checkpoints" in text or "checkpoints.of(" in text or "cfg.checkpoint(" in text) and rel not in OK:
                hits.append(rel)
        assert hits == []


OK = {"tlpipeline/checkpoints.py", "src/taskloop/stores/books.py", "src/taskloop/stores/real.py",
      "src/taskloop/app/run/shared.py"}  # shared.py: the sibling's plan is read (siblings()), never written


class OldCheckpoint(Case):
    """A checkpoint written before the look stage's fields became `engine.look` (tests/fixtures/checkpoint_v3_look.json, dumped by that
    code): at the current envelope version, the look stage sees its fields and saving writes them back as they were."""

    def test_an_old_checkpoint_gives_the_look_stage_its_fields_and_saves_them_back(self):
        old = json.loads((ROOT / "tests" / "fixtures" / "checkpoint_v3_look.json").read_text(encoding="utf-8"))
        old["v"] = Checkpoint.V  # this test covers the look fields; foreign envelope versions are refused separately
        old["state"]["writer"].pop("delegate", None)
        old["state"]["writer"].pop("ctx", None)
        ck = wire.load(Checkpoint, old)
        h = Host()
        Resume(h, h, h, FakeHeadHistory(), ReviewGlue(h), state_names()).restore(ck, late=True)
        assert (h.look.notes, h.look.unjudged, h.look.done) == (
            ["the main screen shows the list"], {"look judge, round 2": "no lane: busy"}, 2)
        reqs = [{"method": "Shots", "names": ["home.png"]}]
        assert (h.look.rendered, h.look.last_reqs, h.render_stale) == (["home.png", "list.png"], reqs, True)
        h.checkpoints.save(step="write", stage=1)
        saved = wire.dump(stored(h))["state"]
        names = (*LOOK_FIELDS, "render_stale")
        assert {k: saved[k] for k in names} == {k: old["state"][k] for k in names}


def test_restart_keeps_exactly_the_eight_section_fields():
    state = RunState(**SAMPLE)
    state.review = ReviewState(filed=["old-attempt"])
    kept = {"extra", "rebase_resets", "brief_hash", "snap", "planner_ref",
            "pending_land_validation", "leftovers", "followup_ids"}
    fresh = restarted(state)
    for name in wire.names(RunState):
        assert getattr(fresh, name) == getattr(state if name in kept else RunState(), name), name


@pytest.mark.parametrize("step", ["write", "plan", "land"])
def test_save_hook_follows_replaced_state_and_pins_pending_validation(step: str):
    host = Host()
    host.state = RunState(pending_land_validation="validate the new base")
    host.checkpoints.save(step=step, feedback="old feedback")
    assert (stored(host).step, stored(host).feedback) == ("land-verify-red", "validate the new base")
    host.state.pending_land_validation = ""
    host.checkpoints.save(step=step, feedback="old feedback")
    assert (stored(host).step, stored(host).feedback) == (step, "old feedback")
