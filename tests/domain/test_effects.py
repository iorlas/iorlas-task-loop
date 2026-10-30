"""EFFECTS: plan_close is a table by outcome kind; keys name an effect once per (bead, run, kind)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

# isort: split
from taskloop.domain import effects as fx
from taskloop.domain import outcome as oc
from taskloop.domain.asks import specs as askspecs

Kind = oc.Kind
REL = fx.ReleaseSlot("task/t-1", 3)
HEAD = [fx.SaveBranch(), fx.RecordRun()]
TAIL = [fx.FileNotes(), fx.Reflect()]


def done(kind: oc.Kind) -> oc.RunOutcome:
    return oc.make(kind, "why", sha="abc" if kind is Kind.LANDED else "",
                   spec=askspecs.external_fact(["x"]) if kind in oc.ASKS else None)


def plan(kind: oc.Kind, dry: bool = False) -> list[fx.Effect]:
    return fx.plan_close(done(kind), dry=dry, branch="task/t-1", slot_gen=3)


class PlanTable(unittest.TestCase):
    def test_landed(self):
        self.assertEqual(plan(Kind.LANDED), [*HEAD, *TAIL, fx.CloseBead(landed=True), REL])

    def test_done_with_nothing_to_land(self):
        self.assertEqual(plan(Kind.DONE), [*HEAD, *TAIL, fx.CloseBead(landed=False), REL])

    def test_failed_leaves_the_bead_open(self):
        for k in (Kind.FAULT_ENGINE, Kind.FAULT_LAND, Kind.FAULT_CRASHED, Kind.FAULT_PLAN):
            self.assertEqual(plan(k), [*HEAD, *TAIL, fx.LeaveBead(), REL], k)

    def test_paused_leaves_the_bead_open(self):
        for k in oc.PAUSES:
            self.assertEqual(plan(k), [*HEAD, *TAIL, fx.LeaveBead(), REL], k)
        self.assertEqual(plan(Kind.OWNER_PARK), [*HEAD, *TAIL, fx.LeaveBead(), REL])

    def test_ask_raises_then_blocks(self):
        for k in oc.ASKS:
            self.assertEqual(plan(k), [*HEAD, fx.RaiseAsk(), *TAIL, fx.BlockBead(), REL], k)

    def test_an_open_ask_says_why_and_frees_the_slot(self):
        self.assertEqual(plan(Kind.WAIT_ASK), [*HEAD, fx.NoteWait(), REL])

    def test_dry_run_touches_no_bead_and_no_slot(self):
        for k in Kind:
            self.assertEqual(plan(k, dry=True), [*HEAD, fx.NoteDry()], k)

    def test_every_kind_plans_one_bead_effect_at_most_and_no_repeat(self):
        for k in Kind:
            p = plan(k)
            self.assertEqual(len(p), len(set(p)), k)
            self.assertLessEqual(sum(isinstance(x, fx.CloseBead | fx.BlockBead | fx.LeaveBead) for x in p), 1, k)
            self.assertIsInstance(p[-1], fx.ReleaseSlot)


class Keys(unittest.TestCase):
    def test_a_key_is_bead_run_kind(self):
        self.assertEqual(fx.key_of("t-1", "r1", fx.CloseBead(landed=True)), "t-1/r1/close_bead")

    def test_a_plan_has_distinct_keys(self):
        for k in Kind:
            keys = [fx.key_of("t-1", "r1", x) for x in plan(k)]
            self.assertEqual(len(keys), len(set(keys)), k)

    def test_every_effect_class_has_a_name(self):
        self.assertEqual(len(set(fx.NAMES.values())), len(fx.NAMES))
