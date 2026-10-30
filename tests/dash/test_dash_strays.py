"""The dashboard's stray rows come from the reconcile sweep's rule: a claim with no live run, and whether its lease ended."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.contracts.bead import Bead
from taskloop.contracts.ids import BeadId
from taskloop_dash.readers.observed import strays_of

NOW = 1793318400.0  # 2026-10-30T00:00:00Z
ENDED, RUNNING = "2026-10-29T23:00:00Z", "2026-10-30T01:00:00Z"


def slot(i: str, name: str, status: str = "in_progress", who: str = "tl-x", ends: str = ENDED, **meta: str) -> Bead:
    return Bead(id=BeadId(i), title=f"slot h {name}", status=status, assignee=who, lease_expires_at=ends, labels=["slot"],
                metadata={"held_gen": "4", **meta})


class Strays(unittest.TestCase):
    def test_a_claimed_slot_with_no_live_run_is_a_stray_and_says_if_its_lease_ended(self):
        got = strays_of([], [slot("sb-1", "s1"), slot("sb-2", "s2", ends=RUNNING)], {}, NOW)
        self.assertEqual([(s.ref, s.expired, s.gen) for s in got], [("sb-1", True, 4), ("sb-2", False, 4)])
        self.assertEqual(got[0].why, "claimed by tl-x, no live run (lease ended)")

    def test_a_free_slot_and_a_held_slot_are_no_stray(self):
        got = strays_of([], [slot("sb-1", "s1", status="open", who=""), slot("sb-2", "s2", hold_until=str(int(NOW) + 60))], {}, NOW)
        self.assertEqual(got, [])

    def test_a_bead_held_by_an_engine_actor_without_a_live_run_is_a_stray_a_hand_claim_is_not(self):
        beads = [Bead(id=BeadId("a-1"), title="", status="in_progress", assignee="tl-x", lease_expires_at=ENDED),
                 Bead(id=BeadId("a-2"), title="", status="in_progress", assignee="denis", lease_expires_at=ENDED)]
        self.assertEqual([s.ref for s in strays_of(beads, [], {}, NOW)], ["a-1"])


if __name__ == "__main__":
    unittest.main()
