"""tl-7y6.7.3 at run-task: a parked bead is refused at the entry, a run that ends on a question records its text hash, the owner's
--fresh takes over a claim no engine runs (per bead, not per actor), and a parked bead lets go of its claim."""
from unittest import mock

from support import homes

# isort: split
from support import engine_case as te
from support.fakes import FakeBeadStore
from support.spawn import port_git
from support.who import who

from taskloop.app.run import running as wrunning
from taskloop.app.wire import asks as wasks
from tlasks import admission, parks
from tlkernel import beadpark as park
from tlkernel.ids import BeadId
from tlkernel.kinds import Kind
from tlkernel.parks import ParkStore
from tltestkit.narrow import must
from tltestkit.plans import PLAN, WRITE, review

BEAD = {"id": "t-1", "title": "Add f", "status": "open", "description": "Add f.", "acceptance_criteria": "- f.txt exists", "metadata": {}}


class Entry(te.EngineTest):
    def cfg(self):
        return homes.cfg()

    def test_a_parked_bead_is_refused_at_the_entry_until_its_text_changes(self):
        store = FakeBeadStore().put(BEAD)
        parks.ended(self.cfg(), must(store.show(BeadId("t-1"))), Kind.ASK_STUCK, "run-1", 1.0)
        why = admission.parked(wasks.host(), BeadId("t-1"), False, str(self.wt), who(), store)
        assert "unchanged" in why
        assert admission.parked(wasks.host(), BeadId("t-1"), True, str(self.wt), who(), store) == ""  # the owner asks for it
        store.put(dict(BEAD, description="Add f, with the header."))
        assert admission.parked(wasks.host(), BeadId("t-1"), False, str(self.wt), who(), store) == ""

    def test_the_third_run_on_one_text_is_refused_even_with_fresh(self):
        store = FakeBeadStore().put(BEAD)
        for n in (1, 2):
            parks.ended(self.cfg(), must(store.show(BeadId("t-1"))), Kind.ASK_STUCK, f"run-{n}", float(n))
        assert "change the description" in admission.parked(wasks.host(), BeadId("t-1"), True, str(self.wt), who(), store)

    def test_an_answered_ask_runs_the_bead_and_starts_the_count_again(self):
        store = FakeBeadStore().put(BEAD)
        for n in (1, 2):
            parks.ended(self.cfg(), must(store.show(BeadId("t-1"))), Kind.ASK_STUCK, f"run-{n}", float(n))
        with mock.patch.object(parks, "answered", return_value=True):
            assert admission.parked(wasks.host(), BeadId("t-1"), False, str(self.wt), who(), store) == ""
        assert ParkStore(self.cfg()).get(BeadId("t-1")) is None

    def test_a_run_that_ends_on_a_question_records_the_text_hash_and_lets_go_of_the_claim(self):
        self.store.put(dict(BEAD, assignee=who().actor, status="in_progress"))  # an engine's actor holds it
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE] * 2, "review": [review(unmet=["x"])] * 2}, max_rounds=2, max_replans=0)
        assert rc == 2
        rec = ParkStore(self.cfg()).get(BeadId("t-1"))
        assert rec is not None
        assert rec is not None
        assert (rec.runs, rec.hash) == (1, park.text_hash(must(self.store.show(BeadId("t-1")))))
        blocked = [c for c in self.store.calls if c[:2] == ("update", "t-1") and "blocked" in c]
        assert blocked and blocked[0][-2:] == ("--assignee", ""), blocked

    def claimed(self, status="in_progress"):
        return {"id": "t-1", "status": status, "assignee": "tl-2be89f88", "lease_expires_at": "2999-01-01T00:00:00Z", "dependencies": []}

    def test_fresh_takes_over_a_live_lease_when_no_engine_runs_the_bead(self):
        store = FakeBeadStore()
        with store.stub(show=self.claimed()), mock.patch.object(wrunning, "running", return_value={"t-2": "s1"}):  # ANOTHER bead runs
            ok, why = admission.admit(wasks.host(), BeadId("t-1"), str(self.wt), port_git(), who(),
                store=store, fresh=True, running_now=wrunning.running)
        assert (ok, why) == (True, "reopened")
        assert store.calls[0] == ("update", "t-1", "--status", "open", "--if-assignee", "tl-2be89f88", "--assignee", "")

    def test_without_fresh_that_claim_stays_and_with_an_engine_on_the_bead_fresh_does_not_take_it(self):
        store = FakeBeadStore()
        with store.stub(show=self.claimed()), mock.patch.object(wrunning, "running", return_value={}):
            ok, why = admission.admit(wasks.host(), BeadId("t-1"), str(self.wt), port_git(), who(),
                store=store, running_now=wrunning.running)
        assert not ok
        assert "a live claim" in why
        with store.stub(show=self.claimed()), mock.patch.object(wrunning, "running", return_value={"t-1": "s2"}):
            ok, why = admission.admit(wasks.host(), BeadId("t-1"), str(self.wt), port_git(), who(),
                store=store, fresh=True, running_now=wrunning.running)
        assert not ok
        assert "a live claim" in why
