"""EFFECTS: plan_close is a table by outcome kind; keys name an effect once per (bead, run, kind)."""
import sys
from pathlib import Path

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

# isort: split
from tlkernel import askspecs
from tlkernel import closeeffects as fx
from tlkernel import runoutcome as oc
from tlkernel.kinds import ASKS, FINISH, PAUSES, Kind

REL = fx.ReleaseSlot("task/t-1", 3)
HEAD = [fx.SaveBranch(), fx.RecordRun()]
TAIL = [fx.FileNotes(), fx.Reflect()]
DROP = fx.DropCheckpoint()  # a finished run only: its checkpoint holds the outcome and the keys until the close is whole


def done(kind: Kind) -> oc.RunOutcome:
    return oc.make(kind, "why", sha="abc" if kind is Kind.LANDED else "",
                   spec=askspecs.external_fact(["x"]) if kind in ASKS else None)


def plan(kind: Kind, dry: bool = False) -> list[fx.CloseEffect]:
    return fx.plan_close(done(kind), dry=dry, branch="task/t-1", slot_gen=3)


class PlanTable(Case):
    def test_landed(self):
        assert plan(Kind.LANDED) == [*HEAD, *TAIL, fx.CloseBead(landed=True), REL, DROP]

    def test_done_with_nothing_to_land(self):
        assert plan(Kind.DONE) == [*HEAD, *TAIL, fx.CloseBead(landed=False), REL, DROP]

    def test_noop_asks_once_and_leaves_the_bead_open(self):
        assert plan(Kind.NOOP) == [*HEAD, fx.RaiseAsk(), *TAIL, fx.LeaveBead(), REL]
        end = done(Kind.NOOP)
        assert not end.finished
        assert (end.word, end.rule.loop, end.rule.bd) == ("noop", "parked", "open")
        assert oc.load("noop", detail="nothing to implement").kind == Kind.NOOP

    def test_failed_leaves_the_bead_open(self):
        for k in (Kind.FAULT_ENGINE, Kind.FAULT_LAND, Kind.FAULT_CRASHED, Kind.FAULT_PLAN):
            assert plan(k) == [*HEAD, *TAIL, fx.LeaveBead(), REL], k

    def test_paused_leaves_the_bead_open(self):
        for k in PAUSES:
            assert plan(k) == [*HEAD, *TAIL, fx.LeaveBead(), REL], k
        assert plan(Kind.OWNER_PARK) == [*HEAD, *TAIL, fx.LeaveBead(), REL]

    def test_ask_raises_then_blocks(self):
        for k in ASKS:
            assert plan(k) == [*HEAD, fx.RaiseAsk(), *TAIL, fx.BlockBead(), REL], k

    def test_an_open_ask_says_why_and_frees_the_slot(self):
        assert plan(Kind.WAIT_ASK) == [*HEAD, fx.NoteWait(), REL]

    def test_dry_run_touches_no_bead_and_no_slot(self):
        for k in Kind:
            assert plan(k, dry=True) == [*HEAD, fx.NoteDry(), *([DROP] if k in FINISH else [])], k

    def test_every_kind_plans_one_bead_effect_at_most_and_no_repeat(self):
        for k in Kind:
            p = plan(k)
            assert len(p) == len(set(p)), k
            assert sum(isinstance(x, fx.CloseBead | fx.BlockBead | fx.LeaveBead) for x in p) <= 1, k
            assert isinstance(p[-1], fx.DropCheckpoint if k in FINISH else fx.ReleaseSlot)


class Keys(Case):
    def test_a_key_is_bead_run_kind(self):
        assert fx.key_of("t-1", "r1", fx.CloseBead(landed=True)) == "t-1/r1/close_bead"

    def test_a_plan_has_distinct_keys(self):
        for k in Kind:
            keys = [fx.key_of("t-1", "r1", x) for x in plan(k)]
            assert len(keys) == len(set(keys)), k

    def test_every_effect_class_has_a_name(self):
        assert len(set(fx.NAMES.values())) == len(fx.NAMES)


class LandPlan(Case):
    def test_the_land_records_then_syncs_bd(self):
        assert fx.plan_land("abc") == [fx.RecordLand("abc"), fx.BdSync("abc")]

    def test_the_push_is_no_effect(self):
        assert {type(x).__name__ for x in fx.plan_land("abc")} == {"RecordLand", "BdSync"}
