"""The config and answer readers admit only typed engine-check requests."""
import pytest

from tlkernel import answers, wire
from tlkernel.config import ConfigError, load
from tltestkit.plans import WRITE


def test_request_config_defaults_and_reader():
    assert load({}).engine.max_run_checks == 2
    check = {'id': 'build', 'argv': ['build']}
    assert not load({'engine': {'checks': [check]}}).engine.checks[0].requestable
    cfg = load({'engine': {'max_run_checks': 1, 'checks': [{**check, 'requestable': True}]}}).engine
    assert cfg.max_run_checks == 1 and cfg.checks[0].requestable


@pytest.mark.parametrize('bad', ['true', 1, None, []])
def test_requestable_refuses_mistyped_values(bad):
    with pytest.raises(ConfigError, match='requestable'):
        load({'engine': {'checks': [{'id': 'build', 'argv': ['build'], 'requestable': bad}]}})


@pytest.mark.parametrize('engine', [{'max_run_check': 2}, {'max_run_checks': '2'}, {'max_run_checks': True}])
def test_cap_refuses_unknown_key_and_mistyped_values(engine):
    with pytest.raises(ConfigError):
        load({'engine': engine})


def test_answer_request_defaults_schema_and_reader():
    base = {k: v for k, v in WRITE.items() if k not in ('run_checks', 'logic_only')}
    assert wire.load(answers.WriteAnswer, base).run_checks == []
    assert wire.load(answers.WriteAnswer, {**base, 'run_checks': ['build']}).run_checks == ['build']
    assert answers.check('write', False, {**base, 'run_checks': [1]})
    assert 'run_checks' in answers.sent_schema('write')['required']


def test_requestable_refuses_unknown_spelling():
    with pytest.raises(ConfigError, match='requestible'):
        load({'engine': {'checks': [{'id': 'build', 'argv': ['build'], 'requestible': True}]}})
