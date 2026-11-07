"""Branch saving and slot release use only their supplied capabilities."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from support.pipeline_ports import FakeLandCleanup, FakeSlotting

from taskloop.app.pipeline.closing_branch import ReleaseSlot, SaveBranch
from tlkernel import fence
from tlkernel.enums import Outcome
from tlkernel.ids import BeadId
from tlkernel.slots import Checkout


@pytest.mark.parametrize('outcome', [Outcome.LANDED, Outcome.DONE, Outcome.FAILED])
def test_release_leaves_slot_and_retries_only_landed(outcome):
    slotting, cleanup = FakeSlotting(), FakeLandCleanup()
    host = Mock(claim=fence.offline(BeadId('t-1')), wt='worktree')
    host.git.checkouts.return_value = [Checkout(path='repo', branch='main', main=True)]
    ReleaseSlot(host, slotting, cleanup).run('task/t-1', outcome)
    assert slotting.calls == [(outcome, 'task/t-1')]
    assert cleanup.calls == (['repo'] if outcome is Outcome.LANDED else [])


def test_fenced_slot_is_untouched(monkeypatch):
    slotting, cleanup = FakeSlotting(), FakeLandCleanup()
    host = Mock(claim=SimpleNamespace(slot_bead='slot'))
    monkeypatch.setattr('taskloop.app.pipeline.closing_branch.fence.stale', lambda *args: True)
    ReleaseSlot(host, slotting, cleanup).run('task/t-1', Outcome.LANDED)
    assert slotting.calls == cleanup.calls == []


def test_save_aborts_rebase_commits_work_and_closes_checkpoint():
    host = Mock(branch='task/t-1', wt='worktree')
    host.git.branch.return_value = 'task/t-1'
    host.git.rebasing.return_value = True
    host.git.dirty.return_value = True
    host.tree.wip.return_value = True
    saved = Mock()
    SaveBranch(host, saved).run(Outcome.FAILED, 'failed')
    host.git.rebase_abort.assert_called_once_with('worktree')
    host.tree.wip.assert_called_once_with(Outcome.FAILED)
    saved.assert_called_once_with()
    host.checkpoints.close.assert_called_once_with('failed')
