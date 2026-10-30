"""What the loop reads every pass and what it publishes every pass (O2): the `loop` block and slots.count from the repo's rule,
LoopState with the queue, typed skip reasons, the typed stop."""
import json
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

from loop.test_loop import LoopBase, rec

# isort: split
from support import looptest

from taskloop.app.launch import loop as wloop
from taskloop.app.slots.pool import SlotPool
from taskloop.contracts.config import LoopConfig


class Tune(LoopBase):
    def config(self, **block):
        (self.repo / ".task-loop.json").write_text(json.dumps({"slots": {"count": 2}, "engine": {}, **block}))

    def test_a_loop_block_overrides_a_constant_and_a_missing_key_keeps_the_default(self):
        self.config(loop={"fails_to_stop": 1})
        self.beads({"x-1": [rec("failed")], "x-2": [rec("landed")]})
        self.assertEqual(self.run_loop(), 2)
        self.assertEqual([b for b, _ in self.started], ["x-1"])  # one failure stops it
        self.assertEqual(LoopConfig().fails_to_stop, 2)
        self.assertEqual(LoopConfig().poll, 2)

    def test_a_changed_block_applies_at_the_next_pass(self):
        self.beads({"x-1": [rec("landed")], "x-2": [rec("failed")], "x-3": [rec("landed")]})
        self.during.append(lambda: self.config(loop={"fails_to_stop": 1}))
        self.assertEqual(self.run_loop(), 2)
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-2"])

    @staticmethod
    def meta(bd, slot_bead, meta):
        slot: dict[str, Any] = bd.slots[slot_bead]
        slot["metadata"] = meta

    def pool(self):
        return SlotPool(wloop.build(str(self.repo)).slot_env())

    def test_a_smaller_slots_count_applies_to_the_next_take_and_never_to_a_held_slot(self):
        bd = self.beads({}, slots=2)
        bd.slots["sl-1"].update(status="in_progress", assignee="tl-other")
        self.meta(bd, "sl-1", {"held_by": "tl-other", "held_bead": "x-0"})
        self.config()
        got = self.pool().take_any("t")
        assert got is not None
        self.assertEqual(got[0], "s2")
        bd.slots["sl-2"].update(status="open", assignee="")
        self.meta(bd, "sl-2", {})
        (self.repo / ".task-loop.json").write_text(json.dumps({"slots": {"count": 1}, "engine": {}}))
        self.assertIsNone(self.pool().take_any("t"))  # s2 is beyond the count now; s1 is still its holder's
        self.assertEqual(bd.slots["sl-1"]["assignee"], "tl-other")
        bd.slots["sl-1"].update(status="open", assignee="")
        self.meta(bd, "sl-1", {})
        got = self.pool().take_any("t")
        assert got is not None
        self.assertEqual(got[0], "s1")


class State(LoopBase):
    def test_the_state_is_written_every_pass_with_the_queue(self):
        self.beads({"x-1": [rec("landed")], "x-2": [rec("landed")]})
        seen = []
        self.during.append(lambda: seen.append(looptest.read_state(str(self.repo))))
        self.assertEqual(self.run_loop(), 0)
        st = seen[0]
        assert st is not None
        self.assertEqual([r.bead for r in st.queue if r.skip is None], ["x-1", "x-2"])
        self.assertEqual([r.ahead for r in st.queue], [0, 1])

    def test_a_skipped_bead_carries_a_typed_reason(self):
        self.beads({"x-1": [rec("landed")], "x-2": []})
        self.bd.beads["x-2"]["labels"] = ["needs-info"]
        (self.repo / ".task-loop.json").write_text(
            json.dumps({"slots": {"count": 2}, "engine": {"skip_labels": ["needs-info"]}}))
        seen = []
        self.during.append(lambda: seen.append(looptest.read_state(str(self.repo))))
        self.assertEqual(self.run_loop(), 0)
        st = seen[0]
        assert st is not None
        skipped = [(r, r.skip) for r in st.queue if r.skip is not None]
        self.assertEqual([(r.bead, s.kind) for r, s in skipped], [("x-2", "label")])
        self.assertEqual(skipped[0][0].ahead, -1)


if __name__ == "__main__":
    unittest.main()
