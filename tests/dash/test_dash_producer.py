"""Interleavings of the real producers (the run manifest rows, the owner-request file) against the dashboard's own checks: no
hand-made record stands in for what the engine writes."""

import tempfile
from pathlib import Path
from types import SimpleNamespace

from support.dashlogs import RunScript, T, bead
from support.runs import manifest

from taskloop.app.run import requests
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.run import RunState
from taskloop.contracts.runlife import Liveness, command_scope, host_name, shown
from taskloop_dash.api import live
from taskloop_dash.views.floor import slot_of
from taskloop_dash.views.world import ProjectIn

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


def test_a_manifest_that_ends_without_any_new_log_bytes_is_ended_and_takes_no_command(tmp_path):
    cfg = ConfigDir(tmp_path)
    running = manifest(cfg, RUN, BEAD, NOW, repo=REPO, state=RunState.RUNNING, heartbeat=NOW).manifest
    assert shown(running, NOW + 1) is Liveness.LIVE
    ended = manifest(cfg, RUN, BEAD, NOW, repo=REPO, state=RunState.DONE).manifest  # no log line follows the manifest write
    assert shown(ended, NOW + 1) is Liveness.ENDED
    assert command_scope(cfg, REPO, BEAD, RUN, NOW + 1) == NO_RUN


def test_a_run_that_never_ends_in_its_manifest_is_shown_lost_once_its_pid_is_gone(tmp_path):
    cfg = ConfigDir(tmp_path)
    m = manifest(cfg, RUN, BEAD, NOW, repo=REPO, state=RunState.RUNNING, heartbeat=NOW, pid=0, host=host_name()).manifest
    assert shown(m, NOW + 1) is Liveness.LIVE  # inside the settle window nothing is claimed
    assert shown(m, NOW + 3600) is Liveness.LOST
    assert command_scope(cfg, REPO, BEAD, RUN, NOW + 3600) == NO_RUN


def test_a_claim_with_no_manifest_for_90_seconds_is_starting_and_becomes_running_when_it_appears():
    claimed = bead("slot-a", "slot host a", "in_progress", assignee="tl-loop", updated_at="2027-01-15T08:00:00Z",
                   metadata={"held_bead": "p-1"})
    project = ProjectIn(id="p", name="p", beads=[bead("p-1", "Starting work", "in_progress")])
    assert slot_of(project, claimed, {}, T + 90).state == "starting"
    run = RunScript("p-1", slot="a", at=95).step("write", 10, lane="codex", tokens=1, end=False).run(T + 100)
    assert slot_of(project, claimed, {"p-1": [run]}, T + 100).state == "running"


def test_an_engine_log_removed_by_retention_between_polls_is_not_an_error():
    with tempfile.TemporaryDirectory() as d:
        cfg = ConfigDir(d)
        bundle = manifest(cfg, RUN, BEAD, NOW, repo=REPO, state=RunState.DONE)
        log = Path(bundle.log)
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text('{"k":"run_start"}\n')
        run = live.LiveRun(cfg, RUN)
        run.refresh()
        log.unlink()
        run.refresh()
        assert isinstance(live.page(run)["events"], list)  # no raise; what was already read may remain
