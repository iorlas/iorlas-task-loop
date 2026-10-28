"""The engine's typed run log (EngineLog v2): every start closes by its id, a cached check writes both records, a lock is
taken before it is released, a wait is written before it is slept, and the run's trace decodes through the contracts."""

import sys
import unittest
from pathlib import Path

import test_engine as te
from test_engine import CLEAN, PLAN, PY, WRITE
from support.logs import pairs, records

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
from taskloop.contracts import log as rec  # noqa: E402
from taskloop.stores.real import real_stores  # noqa: E402
from taskloop.contracts.paths import ConfigDir  # noqa: E402

engine, tl = te.engine, te.tl


class RunLog(unittest.TestCase):
    setUp, tearDown, fake_bd, run_engine = (te.EngineTest.setUp, te.EngineTest.tearDown, te.EngineTest.fake_bd,
                                            te.EngineTest.run_engine)
    commit_base_cfg = te.EngineTest.commit_base_cfg
    checks_engine = te.EngineTest.checks_engine

    def test_engine_has_no_untyped_log_call(self):
        self.assertEqual((ROOT / "skills" / "task-loop" / "engine.py").read_text().count("self.log("), 0)

    def test_a_run_closes_every_start_by_its_id_and_every_record_decodes(self):
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        recs = records(self.eng)
        self.assertEqual(pairs(recs), ([], []))
        for r in recs:
            self.assertEqual(r["v"], 2)
            rec.decode(r)
        self.assertIn("run_start", [r["kind"] for r in recs])
        self.assertIn(recs[-1]["kind"], ("step_end", "close"))

    def test_a_cached_check_writes_both_records(self):
        count = Path(self.tmp.name) / "count"
        bump = PY + ' -c "open(%r, \'a\').write(\'1\')"' % str(count)
        eng = self.checks_engine(checks=[{"id": "bump", "cmd": bump, "group": "tests"}])
        st = {"checks": [], "files": []}
        eng.run_checks(st, "s")
        eng.run_checks(st, "s")
        recs = records(eng)
        self.assertEqual([p for p in pairs(recs)[0] + pairs(recs)[1] if p[0].startswith("check")], [])
        self.assertEqual(len([r for r in recs if r["kind"] == "check_start"]), 2)
        self.assertEqual(len([r for r in recs if r["kind"] == "check_end"]), 2)

    def test_a_lock_is_taken_before_it_is_released(self):
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        kinds = [r["kind"] for r in records(self.eng, "lock", "unlock")]
        self.assertEqual(rc, 0)
        self.assertTrue(kinds and kinds[0] == "lock" and kinds.count("lock") == kinds.count("unlock"))

    def test_the_trace_decodes_through_the_contracts(self):
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        stores = real_stores(ConfigDir(tl.config_dir()))
        got = stores.traces.read_from().items
        self.assertEqual([str(t.rec.run) for t in got], [self.eng.log_path.stem])


if __name__ == "__main__":
    unittest.main()
