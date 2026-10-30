"""One RunOutcome and one sealed Fault union: an unknown outcome is an error, each Fault variant has one action, an ask needs a spec."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

# isort: split
from support.narrow import must

from taskloop.app.loop import verdict as vd
from taskloop.contracts.checks import RoundVerdict, round_verdict_of
from taskloop.contracts.enums import Outcome, Result
from taskloop.domain import outcome as oc
from taskloop.domain.asks import specs as askspecs
from taskloop.domain.outcome import Action, Infra, Kind, Owner, Task

EXPECT = {Infra: Action.RETRY, Task: Action.ASK, Owner: Action.HOLD}


class FaultTable(unittest.TestCase):
    def test_each_variant_has_exactly_one_action(self):
        self.assertEqual({v: v.action for v in EXPECT}, EXPECT)

    def test_every_kind_maps_to_one_variant_and_finishes_to_none(self):
        for k in Kind:
            f = oc.fault_of(k)
            if k in oc.FINISH:
                self.assertIsNone(f, k)
            else:
                self.assertIsInstance(f, (Infra, Task, Owner), k)
                self.assertEqual(must(f).kind, k)

    def test_variant_by_family(self):
        for k in oc.ASKS:
            self.assertIsInstance(oc.fault_of(k), Task, k)
        for k in (*oc.PAUSES, *oc.FAULTS, Kind.CUT):
            self.assertIsInstance(oc.fault_of(k), Infra, k)
        for k in (Kind.OWNER_PARK, Kind.WAIT_ASK):
            self.assertIsInstance(oc.fault_of(k), Owner, k)

    def test_action_agrees_with_the_policy_row(self):
        for k in Kind:
            f = oc.fault_of(k)
            if f is not None:
                self.assertEqual(f.action is Action.ASK, oc.POLICY[k].makes_ask, k)
                self.assertEqual(f.action is Action.ASK, oc.POLICY[k].bd == "block", k)


class RunOutcomeRecord(unittest.TestCase):
    def test_unknown_kind_or_newer_version_is_an_error_not_a_default(self):
        with self.assertRaises(ValueError):
            oc.load("nope", detail="x")
        with self.assertRaises(ValueError):
            oc.load("fault_infra", v=9, detail="y")
        self.assertEqual(oc.load("pause_lane").kind, Kind.PAUSE_LANE)

    def test_an_ask_without_a_spec_cannot_be_built(self):
        for k in oc.ASKS:
            with self.assertRaises(ValueError):
                oc.make(k, "why")
            self.assertIs(must(oc.make(k, "why", spec=askspecs.missing_criteria()).spec).ask_class, askspecs.missing_criteria().ask_class)

    def test_a_non_ask_carries_no_spec(self):
        with self.assertRaises(ValueError):
            oc.make(Kind.FAULT_INFRA, "x", spec=askspecs.missing_criteria())

    def test_the_trace_word_follows_the_kind_alone(self):
        want = {Kind.LANDED: Outcome.LANDED, Kind.DONE: Outcome.DONE, Kind.PAUSE_KILLED: Outcome.FAILED,
                Kind.FAULT_INFRA: Outcome.FAILED, Kind.PAUSE_LANE: Outcome.BLOCKED, Kind.WAIT_ASK: Outcome.BLOCKED}
        for k, w in want.items():
            self.assertIs(oc.make(k, "x", spec=None).word, w, k)


class RoundVerdictUnion(unittest.TestCase):
    def test_a_stored_word_is_one_of_three_or_not_a_round_at_all(self):
        self.assertEqual([round_verdict_of(w) for w in ("red", "unverified", "green")],
                         [RoundVerdict.RED, RoundVerdict.UNVERIFIED, RoundVerdict.GREEN])
        for w in ("", "failed", "paused", "Red"):
            self.assertIsNone(round_verdict_of(w), w)


class OutcomeFile(unittest.TestCase):
    def test_a_file_of_the_old_shape_or_an_unknown_outcome_is_a_failure_that_names_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            for name, text in (("old.json", '{"v": 1, "outcome": "landed", "bead": "t-1"}'),
                               ("odd.json", '{"v": 2, "outcome": "wat", "bead": "t-1"}'), ("torn.json", "{")):
                f = Path(d, name)
                f.write_text(text)
                v, gave = vd.read(f, 0, Path(d, "x.log"))
                self.assertIs(v.outcome, Result.FAILED, name)
                self.assertFalse(gave, name)
                self.assertIn(str(f), v.why, name)
            ok = Path(d, "ok.json")
            ok.write_text('{"v": 2, "outcome": "paused", "bead": "t-1", "kind": "pause_network", "retry_after": 5.0}')
            v, gave = vd.read(ok, 0, Path(d, "x.log"))
            self.assertEqual((v.outcome, v.kind, v.retry_after, gave), (Result.PAUSED, "pause_network", 5.0, True))
