"""Writer requests are bounded engine work, with informational results in the next prompt."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from tlgate.api import WriterSplit
from tlkernel.checks import CheckResult, CheckRun
from tlkernel.config import CheckSpec, EngineConfig
from tlkernel.ids import CheckId
from tltestkit.cfgs import plan_of
from tltestkit.plans import PLAN, WRITE

from tlwork.write.briefing import Briefing
from tlwork.write.check_round import CheckRound
from tlwork.write.progress import progress_of, restore_progress
from tlwork.write.state import StageState
from tlwork.write.write_round import WriteRound


def state():
    s = StageState(plan_of(PLAN), 0, None)
    s.w = dict(WRITE)
    return s


def config(cap=2):
    return EngineConfig(max_run_checks=cap, checks=[
        CheckSpec(id=CheckId('allowed'), argv=['build'], requestable=True),
        CheckSpec(id=CheckId('other'), argv=['other'], requestable=True),
        CheckSpec(id=CheckId('private'), argv=['private'])])


def test_requests_reject_undeclared_private_and_over_cap_and_deduplicate():
    s = state()
    s.w['run_checks'] = ['missing', 'private', 'allowed', 'allowed', 'other']
    WriteRound(SimpleNamespace(cfg=config(1))).requests(s)
    assert s.run_checks == ['allowed']
    assert s.request_feedback.splitlines()[1:] == [
        "run_checks 'missing': undeclared engine check.",
        "run_checks 'private': check is not requestable.",
        "run_checks 'other': engine.max_run_checks exceeded."]


@pytest.mark.parametrize('rc', [0, 1, 124])
def test_requested_output_reaches_next_whole_and_delta_prompt_without_failing_round(rc):
    e, s = Mock(), state()
    e.cfg = config()
    e.checker.split.return_value = WriterSplit(e.cfg, {})
    e.run_dir = Path('/unused')
    e.stage_checks.stoppable.return_value = normal = CheckRun(round=1, results=[])
    e.stage_checks.requested.return_value = CheckRun(round=2, results=[CheckResult(
        id=CheckId('allowed'), cmd='build', group='tests', exit=rc, status='passed' if rc == 0 else 'failed', tail='compiler output')])
    e.checkout.task_diff.return_value = ''
    e.cases.case_checks.return_value = []
    e.cases.rules_text.return_value = ''
    e.judge.look_write.return_value = ''
    e.review.unchecked = []
    e.hand.delta.return_value = None
    e.shared.shared_text.return_value = ''
    e.routing.ledger.return_value.text.return_value = ''
    e.briefing = Briefing(e)
    s.w['run_checks'] = ['allowed']
    WriteRound(e).requests(s)
    out = CheckRound(e).run(s)
    assert out.flow == '' and out.run is normal and s.red == 0
    e.blocked_for.assert_not_called()
    assert e.stage_checks.requested.call_args.args[0] == ['allowed']
    prompt, _ = WriteRound(e).prompts(s, False)
    assert 'Requested engine checks (informational)' in prompt
    assert 'compiler output' in prompt
    assert 'compiler output' in e.hand.delta.call_args.args[6]
    assert 'run_checks' in prompt and 'cannot run requestable engine checks yourself' in prompt


def test_requests_and_feedback_survive_checkpoint_progress():
    s = state()
    s.w['run_checks'] = ['allowed']
    WriteRound(SimpleNamespace(cfg=config())).requests(s)
    s.request_feedback = 'requested output'
    restored = state()
    restore_progress(restored, progress_of(s), 'writer')
    assert restored.run_checks == ['allowed']
    assert restored.request_feedback == 'requested output'
