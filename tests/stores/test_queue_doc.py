"""The merge queue survives a fresh store reader through its repo document."""
from pathlib import Path

from taskloop.stores.real import real_stores
from tlkernel.flakes import FlakeLog, FlakeRow
from tlkernel.paths import ConfigDir
from tlkernel.queue_doc import BuildRow, EntryRow, QueueDoc


def test_queue_document_round_trip(workdir: Path):
    cfg = ConfigDir(workdir)
    doc = QueueDoc(entries=[EntryRow(
        branch="topic", head="head", phase="gating", q="q", tree="tree", ref="ref", reason="reason",
        base="base", ahead=["first"], check_set="checks", after="first",
        build=BuildRow(pid=42, start_id="start", lease_expires=123.5, worktree="build-dir"))],
        in_flight=2, last_base="base")
    real_stores(cfg).queue.of("repo-key").write(doc)
    assert real_stores(cfg).queue.of("repo-key").get() == doc
    assert real_stores(cfg).queue_state.of("repo-key").get() is None


def test_flake_log_round_trip(workdir: Path):
    cfg = ConfigDir(workdir)
    log = FlakeLog(rows=[FlakeRow(test="test_a", t=123.5, how="retry", run="run-1", bead="tl-1")])
    real_stores(cfg).flakes.of("repo-key").write(log)
    assert real_stores(cfg).flakes.of("repo-key").get() == log
    assert real_stores(cfg).flakes.of("other-repo").get() is None
    assert real_stores(cfg).queue.of("repo-key").get() is None
