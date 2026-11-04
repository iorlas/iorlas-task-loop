"""The doctor's reindex verb launches the same state indexer and reports its work."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support.dashlogs import RunScript
from support.narrow import must
from support.spawn import port_git, real_spawner
from support.tlmain import tl

from taskloop.app.launch import reindex
from taskloop.contracts import factorydb
from taskloop.contracts.env import Env
from taskloop.contracts.identity import Identity
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.run import RunManifest
from taskloop.contracts.runrows import RunRows
from taskloop.contracts.stores import JsonStore


class Reindex(unittest.TestCase):
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
                self.assertEqual(tl.v_doctor(args, ctx), 0)
            self.assertIn("reindexed: 1 runs, 1 sources in", output.call_args.args[0])
            con = must(factorydb.open_ro(cfg.factory_db()))
            try:
                self.assertEqual(con.execute("SELECT rev, manifest IS NOT NULL, facts IS NOT NULL FROM run").fetchall(),
                                 [(0, 1, 1)])
                self.assertEqual(rows.get(script.name), original)
            finally:
                con.close()
