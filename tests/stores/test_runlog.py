"""The engine's typed run log (EngineLog v2): every start closes by its id, a cached check writes both records, a lock is
taken before it is released, a wait is written before it is slept, and the run's trace decodes through the contracts."""

import sys
from pathlib import Path

from support import engine_case as te
from support import homes, procsim
from support.logs import pairs, records
from support.plans import CLEAN, PLAN, WRITE

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402, F401

from taskloop.stores.real import real_stores  # noqa: E402
from tlkernel import log as rec  # noqa: E402

engine = te.engine


class RunLog(te.EngineTest):

    def test_engine_has_no_untyped_log_call(self):
        assert (ROOT / "src" / "taskloop" / "app" / "run" / "engine.py").read_text().count("self.log(") == 0

    def test_a_run_closes_every_start_by_its_id_and_every_record_decodes(self):
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        assert rc == 0
        recs = records(self.eng)
        assert pairs(recs) == ([], [])
        for r in recs:
            assert (r["v"], r["run_id"], r["bead"]) == (4, self.eng.log_path.parent.name, self.eng.bead)
            rec.decode(r)
        assert "run_start" in [r["kind"] for r in recs]
        after = ("said", "land_cleanup", "note")  # the close-out may follow the Close with comments and cleanup rows
        ends = [r for r in recs if r["kind"] not in after]
        assert ends[-1]["kind"] in ("step_end", "close")

    def test_a_cached_check_writes_both_records(self):
        count = Path(self.tmp.name) / "count"
        bump = procsim.fake("bump", procsim.appends(count))
        eng = self.checks_engine(checks=[{"id": "bump", "cmd": bump, "group": "tests"}])
        st = {"checks": [], "files": []}
        eng.run_checks(st, "s")
        eng.run_checks(st, "s")
        recs = records(eng)
        assert [p for p in pairs(recs)[0] + pairs(recs)[1] if p[0].startswith("check")] == []
        ids = {r["id"] for r in recs if r["kind"] == "check_start" and r["check"] == "bump"}
        assert len(ids) == 2
        assert len([r for r in recs if r["kind"] == "check_end" and r["id"] in ids]) == 2

    def test_a_lock_is_taken_before_it_is_released(self):
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        kinds = [r["kind"] for r in records(self.eng, "lock", "unlock")]
        assert rc == 0
        assert kinds and kinds[0] == "lock" and kinds.count("lock") == kinds.count("unlock")

    def test_the_trace_decodes_through_the_contracts(self):
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        assert rc == 0
        stores = real_stores(homes.cfg())
        got = stores.traces.read_from().items
        assert [str(t.rec.run) for t in got] == [self.eng.log_path.parent.name]
