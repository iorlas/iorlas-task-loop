"""The doctor's reindex verb launches the same state indexer and reports its work."""

from pathlib import Path
from unittest.mock import patch

import pytest
from support.spawn import port_git, real_spawner
from support.tlmain import tl

from taskloop.adapters import factorybackup
from taskloop.app.launch import reindex
from taskloop.app.wire import doctor
from taskloop.cli import doctor as cli_doctor
from tldash.testing import RunScript
from tlkernel import factorydb
from tlkernel.env import Env
from tlkernel.identity import Identity
from tlkernel.paths import ConfigDir
from tlkernel.runrows import RunRows
from tltestkit.case import Case
from tltestkit.narrow import must
from tltestkit.tmpdir import TemporaryDirectory


class Reindex(Case):
    def test_doctor_flag_rebuilds_and_reports_counts_without_running_diagnostics(self):
        with TemporaryDirectory() as folder:
            cfg = ConfigDir(Path(folder))
            script = RunScript("b-1").step("write", 10, 3).close("done").write(cfg.root)
            rows = RunRows(cfg)
            original = must(rows.get(script.name))
            with rows.transaction() as con:
                con.execute("UPDATE run SET facts=NULL WHERE run=?", (script.name,))
            args = tl.build_parser().parse_args(["doctor", "--reindex"])
            ctx = tl.Ctx(tl.HERE, lambda: 0.0, [], Env({}), spawner=real_spawner(), git=port_git(),
                         who=Identity(actor="test", home=str(cfg.root)))
            with patch.object(reindex, "print", create=True) as output, \
                    patch.object(doctor, "run", side_effect=AssertionError("ordinary diagnostics ran")):
                assert cli_doctor.run(args, ctx) == 0
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
    factorydb.close_shared()
    snapshot = factorybackup.backup(cfg, 1_800_000_000.0) if with_backup else None
    later = RunScript("b-later").step("plan", 2).close("done").write(cfg.root)
    factorydb.close_shared()
    cfg.factory_db().write_bytes(b"")
    try:
        with patch.object(reindex, "print", create=True) as said:
            assert reindex.run(cfg) == 0
        output = "\n".join(call.args[0] for call in said.call_args_list)
        if with_backup:
            assert f"restored factory.db from {snapshot}" in output
        else:
            assert "factory.db was damaged and no backup exists; rebuilding empty (the run files are no longer a source)" in output
        assert f"reindexed: {1 if with_backup else 0} runs, {1 if with_backup else 0} sources in" in output
        assert rows.get(script.name) == (original if with_backup else None)
        assert rows.get(later.name) is None  # the run files are no longer a source of runs: what the snapshot lacks is gone
        assert factorybackup.damaged(cfg) == ""
        assert next(cfg.root.glob("factory.db.bad-*")).read_bytes() == b""
    finally:
        factorydb.close_shared()
