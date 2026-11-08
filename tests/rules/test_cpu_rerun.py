"""The CPU hook stores the first measurement and applies the shared verdict."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from support import cpu_rerun
from support.cpu_rerun import FIRST, PENDING, cpu_failure


def test_cpu_measurements_flow_through_the_item_stash():
    stash = pytest.Stash()
    assert cpu_failure(stash, 2.1, 2, "first call") is None
    assert stash[PENDING] == (2.1, "first call")
    stash[FIRST] = stash[PENDING]
    del stash[PENDING]
    assert cpu_failure(stash, 0.2, 2, "second call") is None
    assert PENDING not in stash
    assert cpu_failure(stash, 2.2, 2, "second call") == (
        "first call; took 2.10 s and 2.20 s of work on two runs, both over its 2.00 s limit")


@pytest.mark.parametrize("other_failure", [False, True])
def test_protocol_retries_only_a_clean_over_budget_call(monkeypatch, other_failure):
    item = SimpleNamespace(stash=pytest.Stash(), ihook=Mock(), nodeid="toy", location=("toy", 0, "toy"), _initrequest=Mock())
    calls = []

    def attempt(node, nextitem):
        calls.append(nextitem)
        assert cpu_failure(node.stash, 2.1 if len(calls) == 1 else 0.2, 2, "first") is None
        return [], [SimpleNamespace(failed=False), SimpleNamespace(failed=other_failure)]

    monkeypatch.setattr(cpu_rerun, "attempt", attempt)
    assert cpu_rerun.pytest_runtest_protocol(item, None)
    assert len(calls) == (1 if other_failure else 2)
    assert item._initrequest.call_count == (0 if other_failure else 1)
    assert item.ihook.pytest_runtest_logreport.call_count == 2
    assert item.ihook.pytest_runtest_logstart.call_count == 1
    assert item.ihook.pytest_runtest_logfinish.call_count == 1
