"""Authoritative run wire records, revisions, and schema retirement."""

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
import support.paths  # noqa: F401
from support.case import Case
from support.tmpdir import TemporaryDirectory

from taskloop.contracts import factorydb, wire
from taskloop.contracts.docstore import JsonStore
from taskloop.contracts.enums import Outcome, Result, Step, WhyCode
from taskloop.contracts.ids import loop_key
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.run import RunFinish, RunManifest, RunState
from taskloop.contracts.runrows import RunRows, StaleRevision


class RunRowsTest(Case):
    def setup_method(self):
        tmp = TemporaryDirectory()
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

    def test_unreadable_manifest_row_is_an_error(self):
        self.rows.put(self.complete())
        with self.rows.transaction() as con:
            con.execute("UPDATE run SET manifest='{' WHERE run='r'")
        with patch.object(JsonStore, "get", side_effect=AssertionError("file fallback")):
            with pytest.raises(factorydb.DatabaseError):
                self.rows.get("r")
            with pytest.raises(factorydb.DatabaseError):
                self.rows.all()


class RefusedRows(RunRowsTest):
    """A manifest row with an extra key is refused, naming the key and that the row is from another
    version; a row that does not validate says so, not 'sqlite' (tl-x3m0)."""

    def put_raw(self, edit):
        m = RunManifest(run="r", repo="/repo", bead="b", started=10.0, loop="loop", state=RunState.RUNNING)
        self.rows.put(m)
        with self.rows.transaction() as con:
            body = json.loads(con.execute("SELECT manifest FROM run WHERE run='r'").fetchone()[0])
            edit(body)
            con.execute("UPDATE run SET manifest=? WHERE run='r'", (json.dumps(body),))
        return m

    def test_an_extra_key_is_refused_naming_the_key_and_the_other_version(self):
        self.put_raw(lambda body: body.update(pid_start_from_the_future=1.5))
        for read in (lambda: self.rows.get("r"), self.rows.all):
            with pytest.raises(factorydb.DatabaseError, match=r"pid_start_from_the_future.*another version, delete it"):
                read()

    def test_a_row_that_does_not_validate_names_validation_the_run_and_the_field(self):
        self.put_raw(lambda body: body.update(started="not a number"))
        for read in (lambda: self.rows.get("r"), self.rows.all):
            with pytest.raises(factorydb.DatabaseError, match=r"run manifest r does not validate.*started"):
                read()
