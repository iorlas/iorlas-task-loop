"""tl-7y6.7.3: the loop's pick leaves a parked bead alone while its text is unchanged, with a typed skip reason."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

# isort: split
from taskloop.app.asks import parks
from taskloop.app.loop.queue import QueueRule
from taskloop.contracts.bead import Bead
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.ids import BeadId
from taskloop.contracts.kinds import Kind
from taskloop.contracts.parks import ParkStore
from taskloop.contracts.paths import ConfigDir


def bead(desc="do it"):
    return Bead(id=BeadId("t-1"), title="t", status="open", description=desc, acceptance_criteria="- works")


class Pick(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = ConfigDir(Path(self.tmp.name))

    def rank(self, b):
        rule = QueueRule(mock.Mock(), EngineConfig(), {}, lambda _b: "", parked=lambda x: parks.skip_of(self.cfg, x))
        return rule.rank([b], "")

    def test_a_bead_with_no_question_behind_it_is_taken(self):
        q = self.rank(bead())
        self.assertEqual(([r.bead.id for r in q.ranked], q.skipped), (["t-1"], []))

    def test_a_run_that_ended_on_a_question_keeps_the_bead_off_the_queue_until_its_text_changes(self):
        parks.ended(self.cfg, bead(), Kind.ASK_STUCK, "run-1", 1.0)
        q = self.rank(bead())
        self.assertEqual((q.ranked, [(s.bead, s.skip.kind) for s in q.skipped]), ([], [("t-1", "parked")]))
        self.assertIn("unchanged", q.skipped[0].skip.why)
        self.assertEqual([r.bead.id for r in self.rank(bead("do it, and mind the header")).ranked], ["t-1"])

    def test_two_runs_on_one_text_is_a_hard_skip_and_a_landed_run_clears_it(self):
        parks.ended(self.cfg, bead(), Kind.ASK_STUCK, "run-1", 1.0)
        parks.ended(self.cfg, bead(), Kind.ASK_BUDGET, "run-2", 2.0)
        self.assertEqual([s.skip.kind for s in self.rank(bead()).skipped], ["capped"])
        parks.ended(self.cfg, bead(), Kind.LANDED, "run-3", 3.0)
        self.assertIsNone(ParkStore(self.cfg).get(BeadId("t-1")))

    def test_a_pause_or_a_fault_is_no_question(self):
        for k in (Kind.PAUSE_NETWORK, Kind.FAULT_INFRA, Kind.WAIT_ASK, Kind.OWNER_PARK):
            parks.ended(self.cfg, bead(), k, "run-1", 1.0)
        self.assertIsNone(ParkStore(self.cfg).get(BeadId("t-1")))
