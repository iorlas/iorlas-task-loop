"""Land-stack command decisions stay in the land node."""
import argparse
from unittest import mock

import pytest

from taskloop.app.land import stack
from tlkernel.env import Env


@pytest.mark.parametrize(('value', 'flag'), [('topic', '--bead'), ('=x', '--supersede'), ('topic=', '--bead')])
def test_invalid_pairs_keep_the_exact_error(value, flag):
    with pytest.raises(SystemExit) as raised:
        stack.pairs([value], flag)
    assert str(raised.value) == f"land-stack: {flag} wants ITEM=VALUE, got {value!r}"


@pytest.mark.parametrize(('rc', 'reason', 'lines', 'why'), [
    (0, '', ['land-stack landed 1 (run run-id)'], '1 delivered'),
    (75, 'lock busy', ['land-stack: lock busy', 'land-stack stopped, exit 75 (run run-id)'], 'lock busy'),
    (1, '', ['land-stack stopped, exit 1 (run run-id)'], 'exit 1'),
])
def test_result_lines_and_terminal_answer(workdir, rc, reason, lines, why):
    args = argparse.Namespace(profile_change=None, repo=str(workdir), bead=[], supersede=[], items=['topic'],
                              base='main', method='squash', wait_min=None, jobs=4)
    who, git, store, finish = mock.Mock(), mock.Mock(), mock.Mock(), mock.Mock()
    git.checkouts.return_value = []
    with (mock.patch.object(stack, 'RunLocator') as locator,
          mock.patch.object(stack, 'real_stores'), mock.patch.object(stack, 'RunLog'),
          mock.patch.object(stack, 'lock_path'), mock.patch.object(stack, 'Stack') as delivery,
          mock.patch.object(stack.time, 'time', return_value=123)):
        locator.return_value.create.return_value.run = 'run-id'
        delivery.return_value.run.return_value = rc
        delivery.return_value.failure_reason = reason
        delivery.return_value.last = 'sha'
        assert stack.run_stack(args, who, git, mock.Mock(), store, ['tl'], record=mock.Mock(),
                               slot=mock.Mock(), slot_base=mock.Mock(return_value='main'), finish=finish,
                               env=Env()) == (rc, lines)
    finish.assert_called_once_with('run-id', 123, why, 'sha', rc == 0)


def test_unmatched_item_is_refused_before_run_creation(workdir):
    args = argparse.Namespace(profile_change=None, repo=str(workdir), bead=['other=tl-1'], supersede=[], items=['topic'])
    with mock.patch.object(stack, 'RunLocator') as locator, pytest.raises(SystemExit) as raised:
        stack.run_stack(args, mock.Mock(), mock.Mock(), mock.Mock(), mock.Mock(), ['tl'], record=mock.Mock(),
                        slot=mock.Mock(), slot_base=mock.Mock(), finish=mock.Mock(), env=Env())
    assert str(raised.value) == 'land-stack: --bead other=... matches no item; the items given are: topic'
    locator.assert_not_called()
