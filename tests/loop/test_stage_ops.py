"""Loop side effects preserve admission, chore ordering and handover failure semantics."""
from unittest.mock import Mock, call

import pytest

from taskloop.app.loop import stages
from tlkernel.procport import Ran
from tlkernel.run import ReexecNote


@pytest.mark.parametrize("admitted,code,expected", [
    (False, 0, (False, "held")),
    (True, 0, (True, "claimed by another session")),
    (True, 1, (False, "claimed by another session")),
])
def test_claim_only_takes_admitted_beads(admitted, code, expected):
    take = Mock(return_value=code)
    assert stages.claim(lambda: (admitted, "held"), take) == expected
    assert take.call_count == int(admitted)


@pytest.mark.parametrize("present", [False, True])
def test_reload_note_is_consumed_even_when_absent(present):
    rec = ReexecNote(run="run", bead="bead", step="step", to="new", frm="old", from_dir="install", t=12)
    ports = Mock()
    ports.read.return_value = rec if present else None
    note = stages.reload_note(ports.read, ports.drop)
    assert ports.mock_calls == [call.read(), call.drop()]
    assert note == (stages.ReloadNote(run="run", to="new", frm="old", from_dir="install", t=12) if present else None)


@pytest.mark.parametrize("has_store", [False, True])
def test_chores_continue_after_optional_failures_and_keep_output(has_store):
    ports = Mock()
    cfg, store = object(), object()
    ports.config.return_value = cfg
    ports.reflect.side_effect = ValueError("reflect failed")
    ports.backup.side_effect = ValueError("backup failed")
    ports.nightly.return_value = iter(["saved"])
    stages.chores(ports.lanes, ports.config, ports.sweep, ports.wake, ports.reflect, ports.backup, ports.disk,
                  store if has_store else None, ports.nightly, ports.say)
    expected = [call.lanes(), call.config(), call.sweep(cfg), call.wake(cfg), call.reflect(),
                call.say("loop: reflect digest: reflect failed"), call.backup(), call.say("loop: db backup: backup failed"),
                call.disk()]
    if has_store:
        expected += [call.nightly(store), call.say("saved")]
    assert ports.mock_calls == expected


def test_nightly_failure_is_reported():
    say = Mock()
    stages.chores(Mock(), Mock(), Mock(), Mock(), Mock(), Mock(), Mock(), object(),
                  Mock(side_effect=ValueError("failed")), say)
    say.assert_called_once_with("loop: bd backup: failed")


@pytest.mark.parametrize("system,exit_code,raises,expected", [
    ("Linux", 0, False, None), ("Darwin", 0, False, 42),
    ("Darwin", 1, False, None), ("Darwin", 0, True, None),
])
def test_memory_probe_only_parses_successful_mac_output(system, exit_code, raises, expected):
    spawner, parse = Mock(), Mock(return_value=42)
    spawner.run.return_value = Ran(exit=exit_code, out="pages")
    if raises:
        spawner.run.side_effect = OSError("missing")
    assert stages.available_mb(lambda: system, spawner, parse) == expected
    assert parse.call_count == int(expected == 42)
    assert spawner.run.call_count == int(system == "Darwin")


def test_stop_grace_is_shared():
    child = Mock()
    stages.stop_now(child)
    stages.stop_tree(child)
    assert child.mock_calls == [call.stop_async(300.0), call.stop(300.0)]


def test_exec_failure_restores_repo_after_flushing_and_closing(monkeypatch):
    ports = Mock()
    ports.argv.return_value = ["uv", "script"]
    ports.environ.return_value = {"handover": "state"}
    ports.execve.side_effect = OSError("exec failed")
    monkeypatch.setattr(stages.os, "chdir", ports.chdir)
    monkeypatch.setattr(stages.os, "execve", ports.execve)
    monkeypatch.setattr(stages.sys, "stdout", ports.stdout)
    monkeypatch.setattr(stages.sys, "stderr", ports.stderr)
    monkeypatch.setattr(stages, "close_held", ports.close)
    with pytest.raises(OSError, match="exec failed"):
        stages.exec_into("repo", "start", ports.argv, ports.environ)
    assert ports.mock_calls == [call.chdir("start"), call.stdout.flush(), call.stderr.flush(), call.close(), call.argv(),
                                call.environ(), call.execve("uv", ["uv", "script"], {"handover": "state"}), call.chdir("repo")]


