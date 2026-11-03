"""One slot table: the count follows the base ref profile, not the working tree; the dash and `tl status` list the same slots."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.dashlogs import T, bead
from support.fakes import FakeBeadStore
from support.who import who

from taskloop.adapters.ident import hostname
from taskloop.app.wire import brief
from taskloop.app.wire.slots import slot_source, slot_table
from taskloop.contracts.ports import Git
from taskloop.contracts.slottable import WORKTREE, LiveSlot, SlotSource, build_slot_table
from taskloop_dash.views import floor
from taskloop_dash.views.world import ProjectIn

NOW = T + 600


def slot_bead(name, status="open", **meta):
    return bead(f"s-{name}", f"slot {hostname()} {name}", status, labels=["slot"], assignee="tl-x" if status != "open" else "",
                metadata=meta)


def git_with(count_on_base, sha="abc1234"):
    git = mock.Mock(spec=Git)
    git.rev_parse.return_value = sha
    git.show.return_value = f'{{"slots": {{"count": {count_on_base}}}}}'
    return git


class SlotTableSource(unittest.TestCase):
    def test_a_stale_working_tree_count_loses_to_the_base_ref(self):
        stale = '{"slots": {"count": 2}}'
        with mock.patch.object(Path, "read_text", return_value=stale), mock.patch.object(Path, "iterdir", return_value=iter(())):
            table = slot_table("/repo", who(), git_with(4), NOW, store=FakeBeadStore())
        self.assertEqual((table.configured, [v.id for v in table.slots], table.source, table.source_sha),
                         (4, ["s1", "s2", "s3", "s4"], "origin/main", "abc1234"))
        self.assertEqual(len(table.slots), table.configured)

    def test_without_a_resolvable_base_the_working_tree_is_the_source_and_says_so(self):
        git = mock.Mock(spec=Git)
        git.rev_parse.return_value = ""
        with mock.patch.object(Path, "read_text", return_value='{"slots": {"count": 2}}'), \
                mock.patch.object(Path, "iterdir", return_value=iter(())):
            src = slot_source("/repo", git)
        self.assertEqual((src.count, src.source, src.sha), (2, WORKTREE, ""))


class SlotTableStates(unittest.TestCase):
    def table(self, beads, live=None, dirs=None, count=4, targets=()):
        return build_slot_table(beads, count, live or {}, dirs, NOW, "origin/main", "abc", targets)

    def states(self, **kw):
        return {v.id: v.state for v in self.table(**kw).slots}

    def test_state_is_computed_from_now_not_from_raw_marks(self):
        beads = [slot_bead("s1", hold_until=NOW + 60, held_by="denis", held_why="by hand\nmore"),
                 slot_bead("s2", hold_until=NOW - 60, held_by="denis")]
        got = {v.id: v for v in self.table(beads=beads).slots}
        self.assertEqual((got["s1"].state, got["s1"].held_reason, got["s1"].held_until), ("held", "by hand", NOW + 60))
        self.assertEqual(got["s2"].state, "free")

    def test_every_state(self):
        beads = [slot_bead("s1", "in_progress"), slot_bead("s2", "in_progress", held_bead="b-1"), slot_bead("s3", "in_progress"),
                 slot_bead("s5")]
        live = {"s1": LiveSlot(run="r1", bead="b-9", pid=7)}
        got = self.states(beads=beads, live=live, dirs={"s1", "s2", "s5"}, count=4, targets=["b-1"])
        self.assertEqual(got, {"s1": "running", "s2": "setup", "s3": "dead", "s4": "free", "s5": "retiring"})

    def test_a_stray_claim_is_claimed_and_a_configured_slot_without_a_bead_is_free(self):
        got = self.states(beads=[slot_bead("s1", "in_progress")], count=2)
        self.assertEqual(got, {"s1": "claimed", "s2": "free"})

    def test_the_live_run_names_its_holder_and_pid(self):
        v = self.table(beads=[], live={"s1": LiveSlot(run="r1", bead="b-1", pid=42)}).slots[0]
        self.assertEqual((v.state, v.holder, v.bead, v.pid), ("running", "r1", "b-1", 42))


class OneSetOfSlots(unittest.TestCase):
    """Held, free and a stray claim: `tl status` and the dash list the same slot ids in the same states."""

    def setUp(self):
        self.beads = [slot_bead("s1", hold_until=NOW + 900, held_by="denis", held_why="testing"), slot_bead("s3", "in_progress")]
        self.store = FakeBeadStore()
        for b in self.beads:
            self.store.put(b)

    def test_status_lines_and_dash_lanes_agree(self):
        git = git_with(3)
        entries = [SimpleNamespace(name=n, is_dir=lambda: True) for n in ("s1", "s3")]
        with mock.patch.object(Path, "read_text", return_value="{}"), mock.patch.object(Path, "iterdir", return_value=iter(entries)), \
                mock.patch("taskloop.app.wire.slots.bd_store", return_value=self.store):
            table = slot_table("/repo", who(), git, NOW)
            with mock.patch.object(Path, "iterdir", return_value=iter(entries)):
                lines = brief.slot_lines("/repo", who(), NOW, git)
        src = SlotSource(count=3, source="origin/main", sha="abc1234", dirs=frozenset({"s1", "s3"}))
        project = ProjectIn(id="p", name="p", beads=[], slots=self.beads, slot_source=src)
        lanes = {s.id: s.state for s in floor.slots_of(project, {}, NOW)}
        self.assertEqual(lanes, {"s1": "held", "s2": "free", "s3": "idle"})
        self.assertEqual([(v.id, v.state) for v in table.slots], [("s1", "held"), ("s2", "free"), ("s3", "claimed")])
        self.assertEqual([x.split(":")[0] for x in lines[:3]], list(lanes))
        self.assertIn("slots.count 3 from origin/main abc1234", lines[-1])


if __name__ == "__main__":
    unittest.main()
