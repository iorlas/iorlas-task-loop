"""Requested checks use the normal executor without entering the round's red streak."""
from unittest.mock import Mock

import support.paths  # noqa: F401

from taskloop.app.checks.step import StageChecks
from tlgate.domain.writer_split import WriterSplit
from tlkernel.checks import CheckResult, CheckRun
from tlkernel.config import CheckSpec, EngineConfig
from tlkernel.ids import CheckId


def test_requested_checks_keep_limits_executor_and_separate_log_block():
    host = Mock()
    host.assert_tree = Mock()
    cfg = EngineConfig(check_wall_min=3, checks=[
        CheckSpec(id=CheckId('build'), argv=['build'], requestable=True, wall_min=7),
        CheckSpec(id=CheckId('test'), argv=['test'], requestable=True)])
    host.checker.host.cfg = cfg
    host.checker.round = 4
    host.checker.run_items.side_effect = [CheckRun(round=i, results=[CheckResult(
        id=CheckId(cid), cmd=cid, group='tests', exit=rc, status='failed' if rc else 'passed', tail='output')])
        for i, cid, rc in [(3, 'build', 1), (4, 'test', 0)]]
    got = StageChecks(host).requested([CheckId('build'), CheckId('test')], 'stage', round=1)
    assert [r.exit for r in got.results] == [1, 0]
    calls = host.checker.run_items.call_args_list
    assert [call.args[0][0].wall_min for call in calls] == [7, 3]
    assert all(call.kwargs == {'everything': True} for call in calls)
    host.checker.run.assert_not_called()
    host.checker.host.steps.begin.assert_called_once_with('checks', 'requested checks: stage', requested=True, round=1)
    host.checker.host.checklog.round.assert_called_once_with(host.checker.host.steps.id, got)
    host.assert_tree.assert_called_once_with('checks', 'after')


def test_requestable_checks_are_engine_only_even_if_fast_or_writer_true():
    cfg = EngineConfig(checks=[CheckSpec(id=CheckId('build'), argv=['build'], requestable=True, writer=True)])
    assert WriterSplit(cfg, {'build': 0.01}).engine_only('build')
