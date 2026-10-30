"""tl-7y6.7.3 at run-task: a parked bead is refused at the entry, a run that ends on a question records its text hash, the owner's
--fresh takes over a claim no engine runs (per bead, not per actor), and a parked bead lets go of its claim."""
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

# isort: split
from support import engine_case as te
from support.engine_case import PLAN, WRITE, review
from support.fakes import FakeBeadStore
from support.narrow import must

from taskloop.adapters import ident
from taskloop.app.asks import parks
from taskloop.app.run import entry
from taskloop.app.run import running as wrunning
from taskloop.contracts.ids import BeadId
from taskloop.contracts.kinds import Kind
from taskloop.contracts.parks import ParkStore
from taskloop.contracts.paths import ConfigDir
from taskloop.domain.beads import park

BEAD = {"id": "t-1", "title": "Add f", "status": "open", "description": "Add f.", "acceptance_criteria": "- f.txt exists", "metadata": {}}


class Entry(te.EngineTest):
    def cfg(self):
        return ConfigDir(ident.config_dir())

    def test_a_parked_bead_is_refused_at_the_entry_until_its_text_changes(self):
        store = FakeBeadStore().put(BEAD)
        parks.ended(self.cfg(), must(store.show(BeadId("t-1"))), Kind.ASK_STUCK, "run-1", 1.0)
        why = entry.parked(BeadId("t-1"), False, str(self.wt), store)
        self.assertIn("unchanged", why)
        self.assertEqual(entry.parked(BeadId("t-1"), True, str(self.wt), store), "")  # the owner asks for it
        store.put(dict(BEAD, description="Add f, with the header."))
        self.assertEqual(entry.parked(BeadId("t-1"), False, str(self.wt), store), "")

    def test_the_third_run_on_one_text_is_refused_even_with_fresh(self):
        store = FakeBeadStore().put(BEAD)
        for n in (1, 2):
            parks.ended(self.cfg(), must(store.show(BeadId("t-1"))), Kind.ASK_STUCK, f"run-{n}", float(n))
        self.assertIn("change the description", entry.parked(BeadId("t-1"), True, str(self.wt), store))

    def test_an_answered_ask_runs_the_bead_and_starts_the_count_again(self):
        store = FakeBeadStore().put(BEAD)
        for n in (1, 2):
            parks.ended(self.cfg(), must(store.show(BeadId("t-1"))), Kind.ASK_STUCK, f"run-{n}", float(n))
        with mock.patch.object(parks, "answered", return_value=True):
            self.assertEqual(entry.parked(BeadId("t-1"), False, str(self.wt), store), "")
        self.assertIsNone(ParkStore(self.cfg()).get(BeadId("t-1")))

    def test_a_run_that_ends_on_a_question_records_the_text_hash_and_lets_go_of_the_claim(self):
        self.store.put(dict(BEAD, assignee=ident.actor(), status="in_progress"))  # an engine's actor holds it
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE] * 2, "review": [review(unmet=["x"])] * 2}, max_rounds=2, max_replans=0)
        self.assertEqual(rc, 2)
        rec = ParkStore(self.cfg()).get(BeadId("t-1"))
        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertEqual((rec.runs, rec.hash), (1, park.text_hash(must(self.store.show(BeadId("t-1"))))))
        blocked = [c for c in self.store.calls if c[:2] == ("update", "t-1") and "blocked" in c]
        self.assertTrue(blocked and blocked[0][-2:] == ("--assignee", ""), blocked)

    def claimed(self, status="in_progress"):
        return {"id": "t-1", "status": status, "assignee": "tl-2be89f88", "lease_expires_at": "2999-01-01T00:00:00Z", "dependencies": []}

    def test_fresh_takes_over_a_live_lease_when_no_engine_runs_the_bead(self):
        store = FakeBeadStore()
        with store.stub(show=self.claimed()), mock.patch.object(wrunning, "running", return_value={"t-2": "s1"}):  # ANOTHER bead runs
            ok, why = entry.admit("t-1", str(self.wt), store=store, fresh=True)
        self.assertEqual((ok, why), (True, "reopened"))
        self.assertEqual(store.calls[0], ("update", "t-1", "--status", "open", "--if-assignee", "tl-2be89f88", "--assignee", ""))

    def test_without_fresh_that_claim_stays_and_with_an_engine_on_the_bead_fresh_does_not_take_it(self):
        store = FakeBeadStore()
        with store.stub(show=self.claimed()), mock.patch.object(wrunning, "running", return_value={}):
            ok, why = entry.admit("t-1", str(self.wt), store=store)
        self.assertFalse(ok)
        self.assertIn("a live claim", why)
        with store.stub(show=self.claimed()), mock.patch.object(wrunning, "running", return_value={"t-1": "s2"}):
            ok, why = entry.admit("t-1", str(self.wt), store=store, fresh=True)
        self.assertFalse(ok)
        self.assertIn("a live claim", why)
