"""The doctor's reindex verb launches the same state indexer and reports its work."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from support.case import Case
from support.dashlogs import RunScript
from support.narrow import must
from support.spawn import port_git, real_spawner
from support.tlmain import tl

from taskloop.app.launch import reindex
from taskloop.contracts import factorybackup, factorydb
from taskloop.contracts.env import Env
from taskloop.contracts.identity import Identity
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.run import RunManifest
from taskloop.contracts.runrows import RunRows
from taskloop.contracts.stores import JsonStore


class Reindex(Case):
    def test_doctor_flag_rebuilds_and_reports_counts_without_running_diagnostics(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = ConfigDir(Path(folder))
            script = RunScript("b-1").step("write", 10, 3).close("done").write(cfg.root)
            rows = RunRows(cfg)
            original = must(rows.get(script.name))
            JsonStore(cfg.run_manifest(script.name), RunManifest).write(original)
            with rows.transaction() as con:
                for table in ("attempt", "step", "run"):
                    con.execute(f"DELETE FROM {table} WHERE run=?", (script.name,))
            args = tl.build_parser().parse_args(["doctor", "--reindex"])
            ctx = tl.Ctx(tl.HERE, lambda: 0.0, [], Env({}), spawner=real_spawner(), git=port_git(),
                         who=Identity(actor="test", home=str(cfg.root)))
            with patch.object(reindex, "print", create=True) as output, \
                    patch.object(tl.doctor, "run", side_effect=AssertionError("ordinary diagnostics ran")):
                assert tl.v_doctor(args, ctx) == 0
            assert "reindexed: 1 runs, 1 sources in" in output.call_args.args[0]
            con = must(factorydb.open_ro(cfg.factory_db()))
            try:
                assert con.execute("SELECT rev, manifest IS NOT NULL, facts IS NOT NULL FROM run").fetchall() == [(0, 1, 1)]
                assert rows.get(script.name) == original
            finally:
                con.close()


@pytest.mark.parametrize("with_backup", [False, True])
def test_reindex_recovers_truncated_database(tmp_path, with_backup):
    cfg = ConfigDir(tmp_path)
    script = RunScript("b-saved").step("write", 10, 3).close("done").write(cfg.root)
    rows = RunRows(cfg)
    original = must(rows.get(script.name))
    JsonStore(cfg.run_manifest(script.name), RunManifest).write(original)
    factorydb.close_shared()
    snapshot = factorybackup.backup(cfg, 1_800_000_000.0) if with_backup else None
    # This retained manifest postdates the snapshot and must be reimported.
    later = RunScript("b-later").step("plan", 2).close("done").write(cfg.root)
    retained = must(rows.get(later.name))
    JsonStore(cfg.run_manifest(later.name), RunManifest).write(retained)
    factorydb.close_shared()
    cfg.factory_db().write_bytes(b"")
    try:
        with patch.object(reindex, "print", create=True) as said:
            assert reindex.run(cfg) == 0
        output = "\n".join(call.args[0] for call in said.call_args_list)
        if with_backup:
            assert f"restored factory.db from {snapshot}" in output
        else:
            assert "factory.db was damaged and no backup exists; rebuilding from retained files" in output
        assert "reindexed: 2 runs, 2 sources in" in output
        assert rows.get(script.name) == original
        assert rows.get(later.name) == retained
        assert factorybackup.damaged(cfg) == ""
        assert next(cfg.root.glob("factory.db.bad-*")).read_bytes() == b""
    finally:
        factorydb.close_shared()
