"""tl-bxk.10.33.8 (SLOTRELEASE): a run that ends parked on an owner's ask holds no slot while it waits."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

from loop.test_loop import LoopBase, rec


class ParkedAskFreesItsSlot(LoopBase):
    def test_a_parked_run_leaves_every_slot_bead_open_and_unmarked(self):
        bd = self.beads({"x-1": [rec("parked", asked=True)]})
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual([(b["status"], b["assignee"], (b.get("metadata") or {}).get("held_by", "")) for b in bd.slots.values()],
                         [("open", "", "")] * len(bd.slots))
        self.assertEqual(bd.beads["x-1"]["status"], "blocked")  # the bead waits on the owner; no slot waits with it

    def test_the_next_bead_takes_the_slot_the_parked_one_left(self):
        self.beads({"x-1": [rec("parked", asked=True)], "x-2": [rec("landed")]}, slots=1)
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual(self.started, [("x-1", "s1"), ("x-2", "s1")])


if __name__ == "__main__":
    unittest.main()
