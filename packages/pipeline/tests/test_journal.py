"""The run journal records lifecycle evidence without an engine or stage implementations."""
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from tlkernel.run import RunState
from tlpipeline.journal import Journal
from tlpipeline.testing import FakeVersion


@pytest.mark.parametrize("state,previous,expected", [
    ({}, "", "first"),
    ({"resumed": True}, "earlier", "resume"),
    ({}, "earlier", "retry"),
    ({"answered": SimpleNamespace(id="ask-1")}, "earlier", "answer"),
    ({"fresh": True}, "earlier", "fresh"),
    ({"reexec": object()}, "earlier", "reexec"),
])
def test_origin(state, previous, expected):
    host = Mock(run_id="current", ck_run=previous, prev_ck="", reexec=None, fresh=False, answered=None, resumed=False)
    for name, value in state.items():
        setattr(host, name, value)
    repo = Mock(return_value="repo")
    with patch("tlpipeline.journal.RunLocator") as locator:
        locator.return_value.of_bead.return_value = []
        result = Journal(host, host, host, host, host, host, host, lambda: "slot", repo, FakeVersion()).origin()
    assert result == {"prev_run": previous, "started_because": expected,
                      "ask": "ask-1" if host.answered else ""}
    if not previous:
        repo.assert_called_once_with(host.git, host.wt)


def test_heartbeat_updates_the_run_manifest():
    host = Mock(run_id="current")
    with patch("tlpipeline.journal.RunLocator") as locator, \
            patch("tlpipeline.journal.time.time", return_value=123):
        Journal(host, host, host, host, host, host, host, lambda: "", lambda _git, _wt: "repo", FakeVersion()).heartbeat()
    locator.assert_called_once_with(host.home)
    locator.return_value.beat.assert_called_once_with("current", 123)


def test_settle_records_the_terminal_manifest():
    host = Mock(run_id="current", dry=False)
    with patch("tlpipeline.journal.RunLocator") as locator, \
            patch("tlpipeline.journal.time.time", return_value=123), \
            patch("tlpipeline.journal.previous_finish") as previous, \
            patch("tlpipeline.journal.finish_run") as finish:
        Journal(host, host, host, host, host, host, host, lambda: "", lambda _git, _wt: "repo",
            FakeVersion()).settle(RunState.PARKED, "paused")
    locator.return_value.get.assert_called_once_with("current")
    manifest = locator.return_value.get.return_value.manifest
    manifest.replace.assert_called_once_with(state=RunState.PARKED, ended=123, reason="paused", finish=None)
    previous.assert_called_once_with(manifest.replace.return_value)
    finish.assert_called_once_with(host.home, "current", previous.return_value, None)


def test_file_trace_skips_an_already_recorded_run():
    host = Mock(run_id="current")
    host.stores.traces.read_from.return_value.items = [SimpleNamespace(rec=SimpleNamespace(run="current"))]
    Journal(host, host, host, host, host, host, host, lambda: "", lambda _git, _wt: "repo", FakeVersion()).file_trace(Mock())
    host.stores.traces.read_from.assert_called_once_with(0)
    host.stores.traces.append.assert_not_called()
