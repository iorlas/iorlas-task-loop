"""EFFECTS: the interpreter applies each effect once; a kill between any two effects resumes at the first unapplied one."""
import sys
from pathlib import Path

import pytest

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

# isort: split
from taskloop.domain import effects as fx
from taskloop.domain.interpret import MemoryLedger, interpret
from tlkernel import runoutcome as oc
from tlkernel.kinds import Kind

PLAN = fx.plan_close(oc.make(Kind.LANDED, sha="abc"), dry=False, branch="task/t-1", slot_gen=2)


class Killed(Exception):
    pass


class Applier:
    def __init__(self, kill_at: int | None = None) -> None:
        self.done: list[fx.Effect] = []
        self.kill_at = kill_at

    def __call__(self, e: fx.Effect) -> None:
        if self.kill_at is not None and len(self.done) == self.kill_at:
            raise Killed
        self.done.append(e)


class Once(Case):
    def test_a_plan_applies_in_order(self):
        a = Applier()
        assert interpret("t-1", "r1", PLAN, MemoryLedger(), a) == PLAN
        assert a.done == PLAN

    def test_a_second_call_applies_nothing(self):
        led, a = MemoryLedger(), Applier()
        interpret("t-1", "r1", PLAN, led, a)
        assert interpret("t-1", "r1", PLAN, led, a) == []
        assert a.done == PLAN

    def test_a_kill_between_every_pair_of_effects_resumes_at_the_first_unapplied(self):
        for n in range(len(PLAN)):  # killed before effect n ran
            led = MemoryLedger()
            first = Applier(kill_at=n)
            with pytest.raises(Killed):
                interpret("t-1", "r1", PLAN, led, first)
            assert first.done == PLAN[:n], n
            second = Applier()
            assert interpret("t-1", "r1", PLAN, led, second) == PLAN[n:], n
            assert first.done + second.done == PLAN, n  # every effect exactly once

    def test_another_run_of_the_same_bead_is_not_skipped(self):
        led, a = MemoryLedger(), Applier()
        interpret("t-1", "r1", PLAN, led, a)
        interpret("t-1", "r2", PLAN, led, a)
        assert a.done == PLAN + PLAN

    def test_another_bead_is_not_skipped(self):
        led, a = MemoryLedger(), Applier()
        interpret("t-1", "r1", PLAN, led, a)
        interpret("t-2", "r1", PLAN, led, a)
        assert len(a.done) == 2 * len(PLAN)
