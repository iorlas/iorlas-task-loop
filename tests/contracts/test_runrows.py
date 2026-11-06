"""Authoritative run wire records, revisions, legacy import and schema retirement."""

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import support.paths  # noqa: F401
from support.case import Case
from support.narrow import must

from taskloop.contracts import factorydb, wire
from taskloop.contracts.enums import Outcome, Result, Step, WhyCode
from taskloop.contracts.ids import loop_key
from taskloop.contracts.locator import RunLocator
from taskloop.contracts.paths import ConfigDir, RunFiles
from taskloop.contracts.run import CallIdentity, DoneEntry, DoneMemo, RunFinish, RunManifest, RunState
from taskloop.contracts.runrows import RunRows, StaleRevision, import_legacy
from taskloop.contracts.stores import JsonStore


class RunRowsTest(Case):
    def setup_method(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg = ConfigDir(Path(tmp.name))
        self.rows = RunRows(self.cfg)

    def complete(self):
        finish = RunFinish(state=RunState.DONE, ended=20.0, outcome=Outcome.DONE, result=Result.LANDED,
                           kind="landed", why="delivered", sha="abc", why_code=WhyCode.VERIFY, end='{"payload":"retained"}')
        return RunManifest(run="r", repo="/repo", bead="b", started=10.0, ended=20.0, loop="loop", attempts=4,
                           state=RunState.DONE, heartbeat=20.0, pid=123, host="host", reason="delivered", mode="stage:gate",
                           owner="ownér", session="session", beads=("b2", "b3"), next_step=Step.GATE, worktree="/tree",
                           branch="feature", sha="abc", finish=finish, finish_projected=True)

    def test_roundtrip_every_manifest_field_and_matching_relational_columns(self):
        m = self.complete()
        self.rows.put(m)
        assert self.rows.get(m.run) == m
        assert m.finish is not None and m.next_step is not None
        with self.rows.transaction() as con:
            row = con.execute("SELECT repo,repo_key,bead,mode,owner,session,loop,worktree,branch,sha,state,reason,"
                              "started,ended,next_step,outcome,why,manifest,rev FROM run").fetchone()
        assert row[:17] == (m.repo, loop_key(m.repo), m.bead, m.mode, m.owner, m.session, m.loop, m.worktree,
                                    m.branch, m.sha, m.state.value, m.reason, m.started, m.ended, m.next_step.value,
                                    m.finish.outcome.value, m.finish.why)
        assert row[17:] == (json.dumps(wire.dump(m), indent=1, ensure_ascii=False) + "\n", 0)
        self.rows.put(m.replace(repo="/new", bead="new", state=RunState.FAILED), expect_rev=0)
        with self.rows.transaction() as con:
            assert con.execute("SELECT repo,repo_key,bead,state,rev FROM run").fetchone() == ("/new", loop_key("/new"), "new", "failed", 1)

    def test_stale_revision_and_failed_change_leave_the_row_unchanged(self):
        m = self.complete()
        self.rows.put(m)
        self.rows.put(m.replace(owner="new"), expect_rev=0)
        before = self.rows.snapshot(m.run)
        with pytest.raises(StaleRevision):
            self.rows.put(m, expect_rev=0)
        with pytest.raises(StaleRevision):
            self.rows.put(m.replace(run="missing"), expect_rev=0)
        assert self.rows.snapshot(m.run) == before
        with pytest.raises(ValueError, match="abort"), self.rows.transaction() as con:
            self.rows.write(con, m)
            raise ValueError("abort")
        assert self.rows.snapshot(m.run) == before

    def test_queries_are_ordered_and_filter_in_sql(self):
        for run, repo, bead, started in (("z", "/r", "b", 2.0), ("b", "/r", "c", 1.0), ("a", "/s", "b", 1.0)):
            self.rows.put(RunManifest(run=run, repo=repo, bead=bead, started=started))
        assert [m.run for m in self.rows.all()] == ["a", "b", "z"]
        assert [m.run for m in self.rows.of_bead("b")] == ["a", "z"]
        assert [m.run for m in self.rows.of_bead("b", "/r")] == ["z"]
        assert [m.run for m in self.rows.of_repo("/r")] == ["b", "z"]

    def legacy(self, m):
        JsonStore(self.cfg.run_manifest(m.run), RunManifest).write(m)

    def test_import_is_insert_only_repeatable_and_preserves_legacy_bytes(self):
        for run in ("a", "b", "c"):
            self.legacy(self.complete().replace(run=run))
        torn = self.cfg.run_manifest("torn")
        torn.parent.mkdir(parents=True)
        torn.write_text("{")
        files = {p: p.read_bytes() for p in self.cfg.runs_dir().glob("*/manifest.json")}
        assert import_legacy(self.cfg) == 3
        assert {p: p.read_bytes() for p in files} == files
        before = self.rows.snapshot("a")
        self.legacy(self.complete().replace(run="a", owner="stale file"))
        assert import_legacy(self.cfg) == 0
        assert self.rows.snapshot("a") == before
        for path, raw in files.items():
            if path.parent.name != "a":
                assert path.read_bytes() == raw
        assert must(JsonStore(self.cfg.run_manifest("a"), RunManifest).get()).owner == "stale file"

    def test_locator_imports_only_once_and_never_rereads_an_imported_file(self):
        self.legacy(self.complete())
        first = RunLocator(self.cfg)
        assert must(first.get("r")).manifest == self.complete()
        self.cfg.run_manifest("r").write_text("{")
        with patch.object(Path, "iterdir", side_effect=AssertionError("repeated directory scan")), \
                patch.object(JsonStore, "get", side_effect=AssertionError("legacy reread")):
            assert RunLocator(self.cfg).runs() == first.runs()
            assert must(first.get("r")).manifest == self.complete()

    def test_import_skips_a_manifest_under_another_run_id(self):
        path = self.cfg.run_manifest("wrong")
        JsonStore(path, RunManifest).write(self.complete())
        before = path.read_bytes()
        assert import_legacy(self.cfg) == 0
        assert self.rows.all() == []
        assert path.read_bytes() == before

    def test_legacy_steps_and_one_synthetic_attempt_import_once_without_changing_files(self):
        for name in ("valid", "torn", "old-name"):
            self.legacy(self.complete().replace(run=name))
        valid = RunFiles(self.cfg.run_dir("valid")).done_memo()
        old = RunFiles(self.cfg.run_dir("old-name")).legacy_done_memo()
        entry = DoneEntry(sha="old-prompt-sha", file="/answer", identity=CallIdentity(
            semantics="sem", worktree="/wt", cwd="/wt", tree="tree", cwd_tree="tree", head="head", cwd_head="head"))
        for path in (valid, old):
            JsonStore(path, DoneMemo).write(DoneMemo(done={'["write", 1]': entry}))
        torn = RunFiles(self.cfg.run_dir("torn")).done_memo()
        torn.write_text("{")
        files = {path: path.read_bytes() for path in (valid, old, torn)}
        assert import_legacy(self.cfg) == 3
        with self.rows.transaction() as con:
            steps = con.execute("SELECT run,key,try,attempt,status,started,ended,input_digest,result,calls "
                                "FROM step ORDER BY run").fetchall()
            attempts = con.execute("SELECT run,n,started,ended,end_kind,fault_class,fingerprint "
                                   "FROM attempt ORDER BY run").fetchall()
        assert [r[0] for r in steps] == ["old-name", "valid"]
        for row in steps:
            assert row[1:8] == ('["write", 1]', 1, 4, "done", 10, 10, "old-prompt-sha")
            assert wire.load(DoneEntry, row[8]) == entry
            assert row[9] == 0
        assert attempts == [(name, 4, 10, 20, None, None, None) for name in ("old-name", "torn", "valid")]
        assert {path: path.read_bytes() for path in files} == files
        with patch.object(JsonStore, "get", side_effect=AssertionError("legacy reread")):
            assert import_legacy(self.cfg) == 0

    def test_legacy_memo_never_replaces_existing_step_rows(self):
        m = self.complete()
        self.legacy(m)
        self.rows.put(m)
        path = RunFiles(self.cfg.run_dir(m.run)).done_memo()
        JsonStore(path, DoneMemo).write(DoneMemo(done={'[1]': DoneEntry(sha="stale", file="/old")}))
        with self.rows.transaction() as con:
            con.execute("INSERT INTO step (run,key,try,attempt,status,started,input_digest) "
                        "VALUES ('r','[2]',1,4,'done',10,'current')")
        assert import_legacy(self.cfg) == 0
        with self.rows.transaction() as con:
            assert con.execute("SELECT key,input_digest FROM step").fetchall() == [("[2]", "current")]

    def test_v1_is_quarantined_and_recreated_at_the_current_schema(self):
        path = self.cfg.factory_db()
        with sqlite3.connect(path) as con:
            con.execute("CREATE TABLE derived (value TEXT)")
            con.execute("INSERT INTO derived VALUES ('old projection')")
            con.execute("PRAGMA user_version=1")
        con.close()
        con = factorydb.open_rw(path)
        assert con is not None
        try:
            assert con.execute("PRAGMA user_version").fetchone() == (factorydb.SCHEMA_VERSION,)
            assert con.execute("SELECT count(*) FROM run").fetchone() == (0,)
        finally:
            con.close()
        bad, = self.cfg.root.glob("factory.db.bad-*")
        with sqlite3.connect(bad) as old:
            assert old.execute("SELECT * FROM derived").fetchall() == [("old projection",)]
        old.close()

    def test_corruption_is_an_error_and_never_reads_legacy(self):
        self.legacy(self.complete())
        self.cfg.factory_db().write_bytes(b"broken database")
        with patch.object(JsonStore, "get", side_effect=AssertionError("file fallback")), \
                pytest.raises(factorydb.DatabaseError):
            RunLocator(self.cfg).get("r")
        assert self.cfg.factory_db().read_bytes() == b"broken database"

    def test_unreadable_manifest_row_is_an_error_without_a_legacy_read(self):
        self.legacy(self.complete())
        import_legacy(self.cfg)
        with self.rows.transaction() as con:
            con.execute("UPDATE run SET manifest='{' WHERE run='r'")
        with patch.object(JsonStore, "get", side_effect=AssertionError("file fallback")):
            with pytest.raises(factorydb.DatabaseError):
                self.rows.get("r")
            with pytest.raises(factorydb.DatabaseError):
                self.rows.all()
