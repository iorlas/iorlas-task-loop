"""Lifecycle binds independent roles without resolving lazy Engine properties."""
import inspect
from unittest import mock

import pytest

from tlpipeline.lifecycle import Lifecycle


@pytest.mark.parametrize("component", [Lifecycle])
def test_constructor_does_not_resolve_role_members(component):
    class LazyRole:
        def __getattribute__(self, name):
            raise AssertionError(f"constructor resolved {name}")

    parameters = inspect.signature(component).parameters
    roles = [LazyRole() for name, parameter in parameters.items()
             if parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD]
    run = component(*roles, body=mock.Mock(), lease=mock.Mock(), reexecs=mock.Mock(), deadline=mock.Mock())
    assert [run.runtime, run.recovery, run.closing, run.crash] == roles


def test_beat_uses_only_runtime_in_the_existing_order():
    runtime = mock.Mock()
    other_roles = [mock.Mock(spec=[]) for _ in range(3)]
    run = Lifecycle(runtime, *other_roles, body=mock.Mock(), lease=mock.Mock(),
                    reexecs=mock.Mock(), deadline=mock.Mock())
    run.beat()
    assert runtime.mock_calls == [mock.call.records.heartbeat(), mock.call.log.emit(mock.ANY),
                                  mock.call.stuck.tick(), mock.call.requests.at_beat()]
