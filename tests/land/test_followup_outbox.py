"""Follow-up creation survives a kill and a disposable run checkpoint, using only fakes."""
import sys
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from taskloop.adapters import beadtools
from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support.fake_beads import FakeBeads
from support.fakegit import FakeGit
from support.memstores import fake_stores

from taskloop.adapters.bd import BdRun, BdStore
from taskloop.app.land.closing import LandFollowUps
from taskloop.app.land.followups import file_follow_ups
from taskloop.app.land.host import LandState
from taskloop.app.look.state import LookState
from taskloop.app.review.state import ReviewLive
from taskloop.app.run.state import StateAttrs, carries_state
from taskloop.stores.runlog import RunLog
from tlkernel import fence
from tlkernel.bead import BdError
from tlkernel.beadsport import BdFailure
from tlkernel.checkpoint import RunState
from tlkernel.enums import Outcome
from tlkernel.followkeys import FollowKey
from tlkernel.ids import BeadId
from tlpipeline.api import Checkpoints, FileNotes
from tltestkit.narrow import must


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
    intake_per_day = 0

    def __init__(self):
        self.state = RunState()
        self.dry = False
        self.bead, self.run_id = BeadId("t-1"), "r"
        self.store, self.stores = FakeBeads(), fake_stores()
        self.claim = fence.offline(self.bead)
        self.checkpoints = Checkpoints(self)
        self.review = ReviewLive()
        self.land_state = LandState()
        self.look = LookState(lambda: self.state)
        self.filed, self.unfiled = [], []
        self.stats = {"rounds": 1}
        self.log = RunLog(self.stores.run_log(self.run_id))
        self.owner_look, self.judge, self.pictures = OwnerLook(), Judge(), Pictures()
        self.comment, self.warn = mock.Mock(), mock.Mock()
        self.git, self.wt, self.task_branch = FakeGit(rev_parse="head"), "/wt", "task/t-1"
        self.checkout = SimpleNamespace(branch_now=lambda: self.task_branch)


class FollowupOutbox(Case):
    def host(self):
        h = Host()
        h.checkpoints.save(step="write")
        h.leftovers = [{"title": "later", "why": "w", "category": "logic", "file": "a.py"}]
        h.checkpoints.keep_pending("review")
        return h

    def test_with_an_intake_budget_the_follow_up_is_deferred_and_labelled_from_review(self):
        h = self.host()
        h.intake_per_day = 3
        assert file_follow_ups(h) == []
        (made,) = h.store.beads.values()
        assert (made.status, "from-review" in made.labels) == ("deferred", True)

    def test_without_an_intake_budget_the_follow_up_stays_open_and_unlabelled(self):
        h = self.host()
        assert file_follow_ups(h) == []
        (made,) = h.store.beads.values()
        assert (made.status, "from-review" in made.labels) == ("open", False)

    def test_kill_after_create_before_checkpoint_resolves_even_a_closed_bead(self):
        h = self.host()
        with mock.patch.object(h.checkpoints, "keep_filed", side_effect=Killed), pytest.raises(Killed):
            file_follow_ups(h)
        made = next(iter(h.store.beads))
        h.store.close(made, "done")
        b = Host()
        b.store, b.stores = h.store, h.stores
        assert file_follow_ups(b) == []
        assert len(b.store.beads) == 1
        key = str(FollowKey.of(b.bead, h.leftovers[0]))
        assert must(b.checkpoints.read()).state.followup_ids[key] == made

    def test_refused_queue_survives_checkpoint_deletion_and_retries_by_key(self):
        h = self.host()
        h.store.refuse_create = [BdError(kind="other", text="offline")]
        assert len(file_follow_ups(h)) == 1
        h.warn.assert_called()
        h.checkpoints.drop()
        b = Host()
        b.store, b.stores = h.store, h.stores
        assert file_follow_ups(b) == []
        assert len(b.store.beads) == 1
        assert must(b.stores.followups.of(b.bead).need()).pending == []

    def test_failed_lookup_keeps_the_outbox_and_does_not_create(self):
        h = self.host()
        with mock.patch.object(h.store, "find", side_effect=BdFailure(BdError(kind="other", text="offline"))):
            assert len(file_follow_ups(h)) == 1
        assert h.store.beads == {}
        assert len(must(h.stores.followups.of(h.bead).need()).pending) == 1

    def test_malformed_successful_lookup_keeps_pending_work_without_creating(self):
        for output in ("truncated", '{"issues": []}', '[{"id": "t-2"}, {}]'):
            with self.subTest(output=output):
                h = self.host()
                calls: list[list[str]] = []

                def run(argv: list[str], cwd: str | None, output: str = output, calls: list[list[str]] = calls) -> BdRun:
                    calls.append(argv[3:-1])
                    return BdRun(0, output, "")

                with mock.patch.object(h, "store", BdStore("x", exe="bd", run=run)):
                    assert file_follow_ups(h) == h.leftovers
                assert len(calls) == 1
                assert calls[0][:4] == ["list", "-n", "0", "--all"]
                assert "--label" in calls[0]
                assert (h.filed, h.followup_ids) == ([], {})
                assert len(must(h.stores.followups.of(h.bead).need()).pending) == 1

    def test_file_notes_reports_and_warns_about_required_work_in_the_outbox(self):
        h = self.host()
        h.leftovers = []  # only the durable queue knows what still needs filing
        h.store.refuse_create = [BdError(kind="other", text="offline")]
        notes = FileNotes(h, LandFollowUps(lambda: file_follow_ups(h)), beadtools.attempt).run(Outcome.FAILED)
        assert (notes.filed, notes.unfiled) == (0, 1)
        assert any("durable outbox" in call.args[0] for call in h.warn.call_args_list)
        assert len(must(h.stores.followups.of(h.bead).need()).pending) == 1

    def test_over_cap_items_remain_for_the_next_run(self):
        h = self.host()
        h.leftovers += [{"title": f"later {n}", "why": "w"} for n in range(3)]
        file_follow_ups(h)
        assert len(h.store.beads) == 3
        assert len(must(h.stores.followups.of(h.bead).need()).pending) == 1
        h.checkpoints.drop()
        b = Host()
        b.store, b.stores = h.store, h.stores
        file_follow_ups(b)
        assert len(b.store.beads) == 4
        assert must(b.stores.followups.of(b.bead).need()).pending == []
