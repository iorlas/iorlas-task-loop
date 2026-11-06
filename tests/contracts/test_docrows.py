"""Checkpoints and follow-up outboxes as database rows (tl-sqd3.26.3, read path): the Doc face of the file store, an older loop's file
adopted once, forward- and backward-readable bodies, a torn or foreign body named as such, and a revision that refuses a stale write."""
import json
import os
import shutil

import pytest
import support.paths  # noqa: F401
from support.case import Case

from taskloop.contracts import scratch
from taskloop.contracts.checkpoint import Checkpoint
from taskloop.contracts.docrows import RowDocs, StaleRevision
from taskloop.contracts.docstore import Absent, ForeignVersion, Torn
from taskloop.contracts.followups import FollowupOutbox
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.wire import Refused
from taskloop.stores.real import real_stores


def ck(step: str = "", closed: bool = False, bead: str = "t-1") -> Checkpoint:
    return Checkpoint(bead=bead, run="r1", t=5.0, step=step, closed=closed)


class CheckpointRows(Case):
    def setup_method(self):
        folder = scratch.scratch_dir(os.environ)
        self.addCleanup(shutil.rmtree, folder, True)
        self.cfg = ConfigDir(folder)
        self.stores = real_stores(self.cfg)
        self.docs = RowDocs(self.cfg, Checkpoint, table="checkpoint", key_col="bead", body_col="body", revisioned=True)
        self.doc = self.docs.of("t-1")

    def set_body(self, body: str):
        with self.docs.rows.transaction() as con:
            con.execute("UPDATE checkpoint SET body=? WHERE bead='t-1'", (body,))

    def test_absent_then_present_with_a_revision_that_counts_each_write(self):
        assert isinstance(self.doc.read(), Absent) and self.docs.keys() == []
        self.doc.write(ck())
        assert self.doc.get() == ck() and self.docs.keys() == ["t-1"] and self.doc.revision() == 0
        self.doc.write(ck(step="gate"))
        assert self.doc.get() == ck(step="gate") and self.doc.revision() == 1
        self.doc.delete()
        assert self.doc.get() is None and self.docs.keys() == []

    def test_a_write_at_a_stale_revision_is_refused_and_changes_nothing(self):
        self.doc.write(ck())
        self.doc.write(ck(step="a"), expect_rev=0)
        with pytest.raises(StaleRevision):
            self.doc.write(ck(step="b"), expect_rev=0)
        assert self.doc.get() == ck(step="a")

    def test_modify_reruns_on_the_newer_record_when_another_writer_got_in_between(self):
        self.doc.write(ck())
        seen: list[str] = []

        def fn(rec: Checkpoint) -> Checkpoint:
            seen.append(rec.step)
            if len(seen) == 1:  # a second writer lands between the read and the write
                self.doc.write(ck(step="theirs"))
            return rec.replace(applied=[*rec.applied, f"after-{rec.step or 'none'}"])
        assert self.doc.modify(fn)
        assert seen == ["", "theirs"]
        got = self.doc.get()
        assert got is not None and got.step == "theirs" and got.applied == ["after-theirs"]

    def test_modify_of_no_record_is_false_and_a_writer_that_always_loses_is_refused(self):
        assert not self.doc.modify(lambda rec: rec)
        self.doc.write(ck())

        def always_raced(rec: Checkpoint) -> Checkpoint:
            self.doc.write(ck(step="again"))
            return rec
        with pytest.raises(StaleRevision):
            self.doc.modify(always_raced)

    def test_the_book_lists_open_beads_from_rows(self):
        self.stores.checkpoints.of("t-1").write(ck())
        self.stores.checkpoints.of("t-2").write(ck(bead="t-2", closed=True))
        assert self.stores.checkpoints.open_beads() == ["t-1"]

    def test_a_newer_writers_extra_key_is_read_past_and_an_older_writers_missing_field_takes_its_default(self):
        self.doc.write(ck())
        body = json.loads(self.doc.raw() or "{}")
        self.set_body(json.dumps({**body, "from_the_future": 1}))
        assert self.doc.get() == ck()
        self.set_body(json.dumps({k: v for k, v in body.items() if k not in ("step", "stage", "rounds", "feedback")}))
        assert self.doc.get() == ck()

    def test_a_torn_body_and_another_version_are_named_not_read_as_absent(self):
        self.doc.write(ck())
        self.set_body("{not json")
        assert isinstance(self.doc.read(), Torn)
        with pytest.raises(Refused):
            self.doc.need()
        self.set_body(json.dumps({"v": 99, "bead": "t-1"}))
        assert isinstance(self.doc.read(), ForeignVersion)


class FollowupRows(Case):
    def setup_method(self):
        folder = scratch.scratch_dir(os.environ)
        self.addCleanup(shutil.rmtree, folder, True)
        self.cfg = ConfigDir(folder)
        self.docs = real_stores(self.cfg).followups

    def test_an_outbox_round_trips_as_a_kv_row(self):
        box = FollowupOutbox(pending=[{"title": "t"}])
        self.docs.of("t-1").write(box)
        assert self.docs.of("t-1").get() == box and self.docs.keys() == ["t-1"]
