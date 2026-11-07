"""One RunOutcome and one sealed Fault union: an unknown outcome is an error, each Fault variant has one action, an ask needs a spec."""
import sys
from pathlib import Path

import pytest

from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

# isort: split
from taskloop.app.loop import verdict as vd
from tlkernel import askspecs
from tlkernel import runoutcome as oc
from tlkernel.checks import RoundVerdict, round_verdict_of
from tlkernel.enums import Outcome, Result
from tlkernel.kinds import ASKS, FAULTS, FINISH, PAUSES, Action, Infra, Kind, Owner, Task, fault_of
from tltestkit.narrow import must

EXPECT = {Infra: Action.RETRY, Task: Action.ASK, Owner: Action.HOLD}


class FaultTable(Case):
    def test_each_variant_has_exactly_one_action(self):
        assert {v: v.action for v in EXPECT} == EXPECT

    def test_every_kind_maps_to_one_variant_and_finishes_to_none(self):
        for k in Kind:
            f = fault_of(k)
            if k in FINISH or k is Kind.STAGE:
                assert f is None, k
            else:
                assert isinstance(f, (Infra, Task, Owner)), k
                assert must(f).kind == k

    def test_variant_by_family(self):
        for k in ASKS:
            assert isinstance(fault_of(k), Task), k
        for k in (*PAUSES, *FAULTS, Kind.CUT):
            assert isinstance(fault_of(k), Infra), k
        for k in (Kind.OWNER_PARK, Kind.WAIT_ASK):
            assert isinstance(fault_of(k), Owner), k

    def test_action_agrees_with_the_policy_row(self):
        for k in Kind:
            f = fault_of(k)
            if f is not None:
                assert (f.action is Action.ASK) == oc.POLICY[k].makes_ask, k
                assert (f.action is Action.ASK) == (oc.POLICY[k].bd == "block"), k


class RunOutcomeRecord(Case):
    def test_unknown_kind_or_newer_version_is_an_error_not_a_default(self):
        with pytest.raises(ValueError):
            oc.load("nope", detail="x")
        with pytest.raises(ValueError):
            oc.load("fault_infra", v=9, detail="y")
        assert oc.load("pause_lane").kind == Kind.PAUSE_LANE

    def test_an_ask_without_a_spec_cannot_be_built(self):
        for k in ASKS:
            with pytest.raises(ValueError):
                oc.make(k, "why")
            assert must(oc.make(k, "why", spec=askspecs.missing_criteria()).spec).ask_class is askspecs.missing_criteria().ask_class

    def test_a_non_ask_carries_no_spec(self):
        with pytest.raises(ValueError):
            oc.make(Kind.FAULT_INFRA, "x", spec=askspecs.missing_criteria())

    def test_the_trace_word_follows_the_kind_alone(self):
        want = {Kind.LANDED: Outcome.LANDED, Kind.DONE: Outcome.DONE, Kind.PAUSE_KILLED: Outcome.FAILED,
                Kind.FAULT_INFRA: Outcome.FAILED, Kind.PAUSE_LANE: Outcome.BLOCKED, Kind.WAIT_ASK: Outcome.BLOCKED}
        for k, w in want.items():
            assert oc.make(k, "x", spec=None).word is w, k


class RoundVerdictUnion(Case):
    def test_a_stored_word_is_one_of_three_or_not_a_round_at_all(self):
        assert (
            [round_verdict_of(w) for w in ("red", "unverified", "green")]
            == [RoundVerdict.RED, RoundVerdict.UNVERIFIED, RoundVerdict.GREEN]
        )
        for w in ("", "failed", "paused", "Red"):
            assert round_verdict_of(w) is None, w


class OutcomeFile(Case):
    def test_a_file_of_the_old_shape_or_an_unknown_outcome_is_a_failure_that_names_the_file(self):
        with TemporaryDirectory() as d:
            for name, text in (("old.json", '{"v": 1, "outcome": "landed", "bead": "t-1"}'),
                               ("odd.json", '{"v": 3, "outcome": "wat", "bead": "t-1"}'), ("torn.json", "{")):
                f = Path(d, name)
                f.write_text(text)
                v, gave = vd.read(f, 0, Path(d, "x.log"))
                assert v.outcome is Result.FAILED, name
                assert not gave, name
                assert str(f) in v.why, name
            ok = Path(d, "ok.json")
            ok.write_text('{"v": 3, "outcome": "paused", "bead": "t-1", "kind": "pause_network"}')
            v, gave = vd.read(ok, 0, Path(d, "x.log"))
            assert (v.outcome, v.kind, gave) == (Result.PAUSED, "pause_network", True)
