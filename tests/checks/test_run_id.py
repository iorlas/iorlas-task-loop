"""RUNID: a check's process is told the run it belongs to (TL_RUN_ID, through the one child-env builder), and every row the run
writes about it names that run (LOGCONTRACT): the engine log, the duration history."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support.engine_case import EngineTest
from support.logs import records

# isort: split
from support import procsim

from taskloop.adapters import check_files, childenv
from taskloop.contracts.checks import Durations
from taskloop.contracts.envvars import EnvVar


def show(cwd, env):
    return 0, "run=" + env.get("TL_RUN_ID", "")


SHOW = procsim.default("show-run-id", show)


class RunId(EngineTest):
    def run_one(self):
        self.eng = self.checks_engine(checks=[{"id": "c", "cmd": SHOW}])
        res = self.eng.run_checks({"checks": [], "files": []}, "s")[0]
        return res, (self.eng.run_dir / res.log).read_text()

    def test_a_check_process_sees_the_id_of_its_run(self):
        _res, out = self.run_one()
        self.assertIn("run=" + self.eng.run_id, out)
        self.assertTrue(self.eng.run_id)

    def test_the_run_id_is_no_part_of_a_results_identity(self):
        self.assertNotIn(EnvVar.TL_RUN_ID.value, childenv.reaching({EnvVar.TL_RUN_ID.value: "x-1-2026"}))

    def test_every_row_of_the_run_and_the_duration_history_carry_it(self):
        self.run_one()
        rows = records(self.eng)
        self.assertTrue(rows)
        self.assertEqual({r["run_id"] for r in rows}, {self.eng.run_id})
        hist = self.eng.stores.durations.of(check_files.repo_key(self.eng.git, str(self.eng.wt))).get() or Durations()
        self.assertEqual([(r.run_id, r.bead, r.call_id, r.outcome) for r in hist.rows if r.call_id == "c"],
                         [(self.eng.run_id, self.eng.bead, "c", "passed")])
