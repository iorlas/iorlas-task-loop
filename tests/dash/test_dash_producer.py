"""Interleavings of the real producers (the run manifest rows, the owner-request file) against the dashboard's own checks: no
hand-made record stands in for what the engine writes."""

from types import SimpleNamespace

from support.runs import manifest

from taskloop.app.run import requests
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.run import RunState
from taskloop.contracts.runlife import command_scope

NOW = 1_800_000_000.0
BEAD, RUN, REPO = "tl-1", "tl-1-20261026-100000", "/repo"
NO_RUN = "no run of this bead is going"


def test_a_stop_after_the_run_ended_is_refused_and_one_before_it_is_dropped_unacted(tmp_path):
    cfg = ConfigDir(tmp_path)
    manifest(cfg, RUN, BEAD, NOW, repo=REPO, state=RunState.RUNNING)
    assert command_scope(cfg, REPO, BEAD, RUN, NOW) == ""
    assert requests.post(cfg, RUN, "dash", NOW, repo=REPO, bead=BEAD, stop=True) == ""  # accepted: the engine has not taken it yet
    manifest(cfg, RUN, BEAD, NOW, repo=REPO, state=RunState.DONE)  # the run ends first
    requests.OwnerRequests(SimpleNamespace(home=cfg, run_id=RUN)).drop()  # ... and its close-out drops what it never took
    assert requests.peek(cfg, RUN) is None
    assert requests.post(cfg, RUN, "dash", NOW + 1, repo=REPO, bead=BEAD, stop=True) == NO_RUN
    assert requests.peek(cfg, RUN) is None


def test_a_command_naming_another_repos_bead_is_refused_before_any_write(tmp_path):
    cfg = ConfigDir(tmp_path)
    manifest(cfg, RUN, BEAD, NOW, repo=REPO, state=RunState.RUNNING)
    why = requests.post(cfg, RUN, "dash", NOW, repo="/other", bead=BEAD, stop=True)
    assert "does not belong" in why
    assert requests.peek(cfg, RUN) is None
