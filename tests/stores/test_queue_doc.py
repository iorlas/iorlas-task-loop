"""The merge queue survives a fresh store reader through its repo document."""
from pathlib import Path

from taskloop.stores.real import real_stores
from tlkernel.paths import ConfigDir
from tlkernel.queue_doc import BuildRow, EntryRow, QueueDoc


def test_queue_document_round_trip(workdir: Path):
    cfg = ConfigDir(workdir)
    doc = QueueDoc(entries=[EntryRow(
        branch="topic", head="head", phase="gating", q="q", tree="tree", ref="ref", reason="reason",
        base="base", ahead=["first"], check_set="checks",
        build=BuildRow(pid=42, start_id="start", lease_expires=123.5, worktree="build-dir"))],
        in_flight=2, last_base="base")
    real_stores(cfg).queue.of("repo-key").write(doc)
    assert real_stores(cfg).queue.of("repo-key").get() == doc
    assert real_stores(cfg).queue_state.of("repo-key").get() is None
