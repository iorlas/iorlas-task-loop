"""The loop's take on fake slot and park ports (app/loop/ports.py): no slot, no worktree, no park store."""
import ast
from pathlib import Path
from unittest import mock

import pytest
import support.paths  # noqa: F401

from taskloop.app.loop import take
from taskloop.app.loop import verdict as vd
from taskloop.app.loop.run import Where
from taskloop.app.loop.take import Taker
from taskloop.contracts.bead import Bead
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.enums import Result
from taskloop.contracts.ids import BeadId
from taskloop.contracts.slots import SlotFail


class FakeSlots:
    def __init__(self, *fails: SlotFail | None, base_ok: bool = False) -> None:
        self.fails, self.base_ok, self.calls = list(fails), base_ok, []

    def ready_for(self, slot: str, bead: str) -> None:
        self.calls.append((slot, bead))
        fail = self.fails.pop(0) if self.fails else None
        if fail:
            raise fail

    def sets_up_at_base(self, slot: str) -> bool:
        return self.base_ok


class FakeParks:
    def __init__(self, *held: str) -> None:
        self.parked = set(held)

    def held(self, b: Bead) -> bool:
        return b.id in self.parked


def parts(slots: FakeSlots, parks: FakeParks | None = None) -> tuple[Taker, mock.Mock, mock.Mock]:
    env, run = mock.Mock(pid=7, slots=slots, asks=parks or FakeParks()), mock.Mock()
    env.now.return_value = 1.0
    return Taker(env, run, lambda: mock.Mock(pause_retry=60), lambda text: None, mock.Mock(), {}), env, run


def taker(slots: FakeSlots) -> Taker:
    return parts(slots)[0]


def test_a_broken_slot_is_reset_once_more_before_it_counts_as_a_fault():
    slots = FakeSlots(SlotFail("slot_broken", "dirty"))
    assert taker(slots).prepare("s1", "t-1") is None
    assert slots.calls == [("s1", "t-1")] * 2


def test_a_slot_that_stays_broken_fails_the_bead_before_the_engine_and_unclaims_it():
    t, env, _ = parts(FakeSlots(SlotFail("slot_broken", "dirty"), SlotFail("slot_broken", "still dirty")))
    v = t.prepare("s1", "t-1")
    assert v is not None and v.pre_engine and v.outcome is Result.FAILED
    env.store.unclaim.assert_called_once()


def test_a_bead_pinned_by_a_live_run_is_taken_not_failed():
    v = taker(FakeSlots(SlotFail("bead_pinned", "a run holds it"))).prepare("s1", "t-1")
    assert v is not None and v.outcome is Result.TAKEN


@pytest.mark.parametrize(("base_ok", "kind"), [(True, vd.SETUP_OWN_TREE), (False, "transient_infrastructure")])
def test_a_failed_setup_is_the_beads_own_tree_only_when_the_base_sets_up(base_ok, kind):
    v = taker(FakeSlots(SlotFail("transient", "setup exited 1", setup=True), base_ok=base_ok)).prepare("s1", "t-1")
    assert v is not None and v.kind == kind


def test_a_parked_bead_is_not_claimed():
    t, env, run = parts(FakeSlots(), FakeParks("t-1"))
    run.run.side_effect = AssertionError("a parked bead must not run")
    taken = t.attempt_all([Bead(id=BeadId("t-1"), title="x", status="open")], Where("s1", "d", None, 0.0), True, EngineConfig(),
                          mock.Mock(), mock.Mock())
    assert taken.verdict is None
    env.claim.assert_not_called()


def test_take_imports_no_stage_package():
    tree = ast.parse(Path(take.__file__).read_text())
    stages = {"asks", "slots", "release", "land", "checks", "plan", "write", "review", "look", "run", "report", "doctor"}
    named = {n.module.split(".")[2] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module
             and n.module.startswith("taskloop.app.") and n.module.split(".")[2] in stages}
    assert named == set()


def test_no_loop_module_imports_a_stage_package_but_its_adapters():
    stages = {"asks", "slots", "release", "land", "checks", "plan", "write", "review", "look", "run", "report", "doctor"}
    for path in Path(take.__file__).parent.glob("*.py"):
        if path.name == "stages.py":
            continue
        tree = ast.parse(path.read_text())
        named = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module
                 and n.module.startswith("taskloop.app.") and n.module.split(".")[2] in stages}
        assert named == set(), path.name
