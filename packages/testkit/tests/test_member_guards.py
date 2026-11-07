"""Member kind classification and limits use the same path and markers as root tests."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tltestkit import member_guards as guards


@pytest.mark.parametrize("path,marked,expected", [
    ("packages/delegate/tests/test_run.py", False, "logic"),
    ("packages/delegate/tests/real/test_run.py", False, "real"),
    ("packages/delegate/tests/test_run.py", True, "real"),
    ("packages/slots/tests/test_run.py", False, "logic"),
    ("tests/delegate/test_run.py", False, None),
])
def test_member_kind(path, marked, expected):
    item = SimpleNamespace(path=Path(path), stash=pytest.Stash(), obj=None,
                           get_closest_marker=lambda name: marked, add_marker=lambda marker: None)
    guards.pytest_collection_modifyitems([item])
    assert item.stash.get(guards.KIND, None) == expected


@pytest.mark.parametrize("kind,duration,skipped,expected", [
    ("logic", 0.1, False, "passed"), ("logic", 3, False, "failed"),
    ("real", 3, False, "passed"), ("real", 16, False, "failed"),
    ("real", 0, True, "skipped"),
])
def test_member_time_report(kind, duration, skipped, expected):
    item = SimpleNamespace(stash=pytest.Stash(), module=SimpleNamespace(), nodeid="member")
    item.stash[guards.KIND] = kind
    item.stash[guards.USED] = duration
    report = SimpleNamespace(skipped=skipped, passed=not skipped, outcome="skipped" if skipped else "passed")
    hook = guards.pytest_runtest_makereport(item, SimpleNamespace(when="call", duration=duration))
    next(hook)
    with pytest.raises(StopIteration):
        hook.send(SimpleNamespace(get_result=lambda: report))
    assert report.outcome == expected
    assert item.stash[guards.SKIPPED] == skipped


@pytest.mark.parametrize("kind,skipped,must_spawn", [
    ("logic", False, False), ("real", False, True), ("real", True, False),
])
def test_member_process_guard_installs_and_checks(monkeypatch, kind, skipped, must_spawn):
    item = SimpleNamespace(stash=pytest.Stash(), nodeid="member")
    item.stash[guards.KIND] = kind
    item.stash[guards.SKIPPED] = skipped
    world = Mock()
    constructor = Mock(return_value=world)
    monkeypatch.setattr(guards.procsim, "Procs", constructor)
    fixture = guards.procs_guard(SimpleNamespace(node=item))
    assert next(fixture) is world
    world.install.assert_called_once()
    with pytest.raises(StopIteration):
        next(fixture)
    constructor.assert_called_once_with("member", guarded=kind == "logic")
    world.check.assert_called_once_with(must_spawn=must_spawn)


@pytest.mark.parametrize("hook", [guards.pytest_runtest_setup, guards.pytest_runtest_call])
def test_root_hooks_do_not_restore_streams(monkeypatch, hook):
    item = SimpleNamespace(stash=pytest.Stash())
    run = hook(item)
    next(run)
    stream = Mock()
    monkeypatch.setattr(guards.sys, "stdout", stream)
    with pytest.raises(StopIteration):
        next(run)
    assert guards.sys.stdout is stream
