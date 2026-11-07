"""Receipt rows are the sole authority, including retention and legacy retirement."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest
import support.paths  # noqa: F401
from support.case import Case
from support.memstores import MemDocSet
from support.tmpdir import TemporaryDirectory

from taskloop.stores.real import real_stores
from tlkernel import factorydb, wire
from tlkernel.checks import BaseRedRecord, CheckResult, PassRecord
from tlkernel.docstore import Absent, Present
from tlkernel.ids import CheckId, TreeSha
from tlkernel.paths import ConfigDir
from tlkernel.receiptrows import DbDocSet
from tlkernel.runkey import BaseSha, Digest, RunKey


class ReceiptRowsTest(Case):
    def setup_method(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(factorydb.close_shared)
        self.cfg = ConfigDir(Path(tmp.name))
        self.stores = real_stores(self.cfg)
        self.docs = self.stores.results("repo", "test")

    def receipt(self, ts=1.0):
        key = RunKey(check=CheckId("test"), cmd=Digest("cmd"), config=Digest("config"), toolchain=Digest("tools"),
                     tree=TreeSha("key-tree"), base=BaseSha("key-base"), inputs=Digest("inputs"),
                     selected=Digest("selected"), env=Digest("env"), execution=Digest("host-id"))
        result = CheckResult(id=key.check, cmd="echo héllo", group="tests", exit=0, status="passed", tail="evidence")
        return PassRecord(key=key, result=result, tree=TreeSha("tree"), base=BaseSha("base"), run_id="run", host="host",
                          ts=ts, origin="original", round=2, log_abs="/evidence/log")

    def connection(self):
        con = factorydb.shared_rw(self.cfg.factory_db())
        assert con is not None
        return con

    def test_roundtrip_upsert_and_relational_columns_share_the_wire_record(self):
        for rec in (self.receipt(), self.receipt(3.0).replace(tree=TreeSha("new-tree"), host="new-host", run_id="new-run")):
            self.docs.of("digest").write(rec)
            assert self.docs.of("digest").get() == rec
            assert self.docs.of("digest").need() == rec
            assert self.docs.of("digest").read() == Present(rec)
            row = self.connection().execute("SELECT repo_key,check_id,digest,kind,tree,base,run,host,ts,body FROM check_pass").fetchone()
            assert row[:9] == ("repo", "test", "digest", "pass", rec.tree, rec.base, rec.run_id, rec.host, rec.ts)
            assert json.loads(row[9]) == wire.dump(rec)
        self.docs.of("digest").delete()
        assert self.docs.of("digest").get() is None
        assert self.docs.of("digest").read() == Absent()
        assert self.docs.keys() == []

    def test_missing_reads_and_deletes_do_not_create_a_database(self):
        assert self.docs.of("absent").get() is None
        assert self.docs.of("absent").need() is None
        assert self.docs.keys() == []
        self.docs.of("absent").delete()
        self.docs.keep_newest(8)
        assert not self.cfg.factory_db().exists()

    def test_corrupt_or_unavailable_db_and_invalid_body_raise_database_error(self):
        self.cfg.factory_db().write_bytes(b"not sqlite")
        with pytest.raises(factorydb.DatabaseError):
            self.docs.of("digest").get()
        with pytest.raises(factorydb.DatabaseError):
            self.docs.keys()
        self.cfg.factory_db().unlink()
        with patch.object(factorydb, "shared_rw", return_value=None), pytest.raises(factorydb.DatabaseError):
            self.docs.of("digest").write(self.receipt())
        self.docs.of("digest").write(self.receipt())
        con = self.connection()
        with factorydb.begin_immediate(con):
            con.execute("UPDATE check_pass SET body='{' ")
        with pytest.raises(factorydb.DatabaseError):
            self.docs.of("digest").get()

    def test_keys_are_sorted_and_families_are_isolated(self):
        for digest in ("z", "a", "m"):
            self.docs.of(digest).write(self.receipt())
        self.stores.results("other", "test").of("foreign").write(self.receipt())
        self.stores.results("repo", "other").of("other-check").write(
            self.receipt().replace(key=self.receipt().key.replace(check=CheckId("other"))))
        assert self.docs.keys() == ["a", "m", "z"]

    def test_base_red_keeps_its_check_id_and_key_tree_and_base(self):
        rec = self.receipt()
        reds = self.stores.base_red("repo")
        for check in ("test", "other"):
            red = BaseRedRecord(key=rec.key.replace(check=CheckId(check)), red=True, run_id="r", host="h", ts=3.0)
            reds.of(check).write(red)
            assert reds.of(check).get() == red
            row = self.connection().execute("SELECT check_id,kind,tree,base,run,host,ts FROM check_pass WHERE digest=?",
                                            (check,)).fetchone()
            assert row == (check, "base_red", red.key.tree, red.key.base, "r", "h", 3.0)
        assert reds.keys() == ["other", "test"]
        reds.of("test").delete()
        assert reds.keys() == ["other"]

    def test_keep_newest_is_one_delete_and_matches_the_memory_store(self):
        mem = MemDocSet(PassRecord)
        other = self.stores.results("other", "test")
        other.of("untouched").write(self.receipt())
        red = BaseRedRecord(key=self.receipt().key, red=True)
        self.stores.base_red("repo").of("untouched").write(red)
        for i in reversed(range(12)):
            for docs in (self.docs, mem):
                docs.of(f"d{i:02}").write(self.receipt(float(i)))
        statements = []
        con = self.connection()
        con.set_trace_callback(statements.append)
        try:
            self.docs.keep_newest(8)
        finally:
            con.set_trace_callback(None)
        assert [s.split()[0] for s in statements] == ["BEGIN", "DELETE", "COMMIT"]
        mem.keep_newest(8)
        assert self.docs.keys() == [f"d{i:02}" for i in range(4, 12)]
        assert self.docs.keys() == mem.keys()
        assert other.keys() == ["untouched"]
        assert self.stores.base_red("repo").of("untouched").get() == red
        self.docs.keep_newest(0)
        assert self.docs.keys() == []

    def test_two_threads_writing_different_digests_lose_nothing(self):
        def write(prefix):
            for i in range(20):
                self.docs.of(f"{prefix}{i:02}").write(self.receipt(float(i)))

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(write, prefix) for prefix in ("a", "b")]
            for future in futures:
                future.result()
        assert self.docs.keys() == [f"{prefix}{i:02}" for prefix in ("a", "b") for i in range(20)]

    def test_unreadable_database_is_not_an_absent_receipt(self):
        with patch.object(Path, "stat", side_effect=PermissionError("unreadable")):
            with pytest.raises(factorydb.DatabaseError):
                self.docs.of("one").get()
            with pytest.raises(factorydb.DatabaseError):
                self.docs.keys()

    def test_mismatched_check_is_rejected(self):
        docs = DbDocSet(self.cfg, "repo", "other", "pass", PassRecord)
        with pytest.raises(ValueError):
            docs.of("digest").write(self.receipt())
        assert docs.keys() == []
