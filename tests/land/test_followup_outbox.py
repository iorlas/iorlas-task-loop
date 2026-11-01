"""Follow-up creation survives a kill and a disposable run checkpoint, using only fakes."""
import sys
import unittest
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.fake_beads import FakeBeads
from support.fakegit import FakeGit
from support.narrow import must

from taskloop.app.land.followups import file_follow_ups
from taskloop.app.run.closer_notes import FileNotes
from taskloop.app.run.state import Checkpoints, StateAttrs, carries_state
from taskloop.contracts import fence
from taskloop.contracts.bead import BdError
from taskloop.contracts.checkpoint import RunState
from taskloop.contracts.enums import Outcome
from taskloop.contracts.ids import BeadId
from taskloop.contracts.ports import BdFailure
from taskloop.domain.review.followups import FollowKey
from taskloop.stores.memory import fake_stores
from taskloop.stores.runlog import RunLog


class Killed(BaseException):
    pass


class OwnerLook:
    def unverified_text(self) -> str:
        return ""

    def file_owner_look(self) -> None:
        pass


class Judge:
    def is_look(self, u: Mapping[str, str]) -> bool:
        return False


class Pictures:
    def keep_evidence(self) -> list[Path]:
        return []


@carries_state
class Host(StateAttrs):
    def __init__(self):
        self.state = RunState()
        self.dry = False
        self.bead, self.run_id = BeadId("t-1"), "r"
        self.store, self.stores = FakeBeads(), fake_stores()
        self.claim = fence.offline(self.bead)
        self.checkpoints = Checkpoints(self)
        self.unchecked, self.unverified, self.filed, self.unfiled = [], [], [], []
        self.stats = {"rounds": 1}
        self.log = RunLog(self.stores.run_log(self.run_id))
        self.owner_look, self.judge, self.pictures = OwnerLook(), Judge(), Pictures()
        self.comment, self.warn = mock.Mock(), mock.Mock()
        self.git, self.wt, self.task_branch = FakeGit(rev_parse="head"), "/wt", "task/t-1"
        self.checkout = SimpleNamespace(branch_now=lambda: self.task_branch)


class FollowupOutbox(unittest.TestCase):
    def host(self):
        h = Host()
        h.checkpoints.save(step="write")
        h.leftovers = [{"title": "later", "why": "w", "category": "logic", "file": "a.py"}]
        h.checkpoints.keep_pending("review")
        return h

    def test_kill_after_create_before_checkpoint_resolves_even_a_closed_bead(self):
        h = self.host()
        with mock.patch.object(h.checkpoints, "keep_filed", side_effect=Killed), self.assertRaises(Killed):
            file_follow_ups(h)
        made = next(iter(h.store.beads))
        h.store.close(made, "done")
        b = Host()
        b.store, b.stores = h.store, h.stores
        self.assertEqual(file_follow_ups(b), [])
        self.assertEqual(len(b.store.beads), 1)
        key = str(FollowKey.of(b.bead, h.leftovers[0]))
        self.assertEqual(must(b.checkpoints.read()).state.followup_ids[key], made)

    def test_refused_queue_survives_checkpoint_deletion_and_retries_by_key(self):
        h = self.host()
        h.store.refuse_create = [BdError(kind="other", text="offline")]
        self.assertEqual(len(file_follow_ups(h)), 1)
        h.warn.assert_called()
        h.checkpoints.drop()
        b = Host()
        b.store, b.stores = h.store, h.stores
        self.assertEqual(file_follow_ups(b), [])
        self.assertEqual(len(b.store.beads), 1)
        self.assertEqual(must(b.stores.followups.of(b.bead).need()).pending, [])

    def test_failed_lookup_keeps_the_outbox_and_does_not_create(self):
        h = self.host()
        with mock.patch.object(h.store, "find", side_effect=BdFailure(BdError(kind="other", text="offline"))):
            self.assertEqual(len(file_follow_ups(h)), 1)
        self.assertEqual(h.store.beads, {})
        self.assertEqual(len(must(h.stores.followups.of(h.bead).need()).pending), 1)

    def test_file_notes_reports_and_warns_about_required_work_in_the_outbox(self):
        h = self.host()
        h.leftovers = []  # only the durable queue knows what still needs filing
        h.store.refuse_create = [BdError(kind="other", text="offline")]
        notes = FileNotes(h).run(Outcome.FAILED)
        self.assertEqual((notes.filed, notes.unfiled), (0, 1))
        self.assertTrue(any("durable outbox" in call.args[0] for call in h.warn.call_args_list))
        self.assertEqual(len(must(h.stores.followups.of(h.bead).need()).pending), 1)

    def test_over_cap_items_remain_for_the_next_run(self):
        h = self.host()
        h.leftovers += [{"title": f"later {n}", "why": "w"} for n in range(3)]
        file_follow_ups(h)
        self.assertEqual(len(h.store.beads), 3)
        self.assertEqual(len(must(h.stores.followups.of(h.bead).need()).pending), 1)
        h.checkpoints.drop()
        b = Host()
        b.store, b.stores = h.store, h.stores
        file_follow_ups(b)
        self.assertEqual(len(b.store.beads), 4)
        self.assertEqual(must(b.stores.followups.of(b.bead).need()).pending, [])
