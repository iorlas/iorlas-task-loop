"""tl-7y6.7.3: park is a state transition. The rule (domain/beads/park.py) and the d5f.39 replay: 7 runs on an unchanged bead."""
import json
import sys
from pathlib import Path

from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

# isort: split
from taskloop.domain.beads import park
from tlkernel.bead import Bead
from tlkernel.ids import BeadId
from tlkernel.parks import Park

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "replay"


def bead(desc="do it", ac="- works", title="t", **kw):
    return Bead(id=BeadId("t-1"), title=title, status="open", description=desc, acceptance_criteria=ac, **kw)


class TextHash(Case):
    def test_title_description_and_acceptance_change_the_hash_nothing_else_does(self):
        base = park.text_hash(bead())
        assert base != park.text_hash(bead(desc="do it better"))
        assert base != park.text_hash(bead(ac="- works fast"))
        assert base != park.text_hash(bead(title="u"))
        assert base == park.text_hash(bead(labels=["x"], notes="Land (engine): x", priority=0))
        assert park.text_hash(bead(title="a", desc="b")) != park.text_hash(bead(title="ab", desc=""))


class Verdict(Case):
    def rec(self, runs, b=None):
        return Park(bead=BeadId("t-1"), hash=park.text_hash(b or bead()), runs=runs, run="r1", t=1.0)

    def test_no_record_or_a_changed_text_is_free(self):
        assert park.verdict(None, bead()) is None
        assert park.verdict(self.rec(1), bead(desc="changed")) is None
        assert park.verdict(self.rec(5), bead(ac="- changed")) is None

    def test_the_first_question_parks_the_bead_until_it_changes_but_fresh_or_an_answer_runs_it(self):
        v = park.verdict(self.rec(1), bead())
        assert (v.kind if v else None) == "parked"
        assert park.verdict(self.rec(1), bead(), fresh=True) is None
        assert park.verdict(self.rec(1), bead(), answered=True) is None

    def test_the_third_run_on_one_text_is_refused_even_by_fresh(self):
        for kw in ({}, {"fresh": True}):
            v = park.verdict(self.rec(2), bead(), **kw)
            assert (v.kind if v else None) == "capped", kw
        assert park.verdict(self.rec(2), bead(), answered=True) is None  # the answer is new input
        assert park.verdict(self.rec(2), bead(desc="changed"), fresh=True) is None


class Replay(Case):
    def test_d5f39_seven_runs_on_an_unchanged_bead_are_one_run_then_a_refusal(self):
        rows = [json.loads(ln) for ln in (FIX / "d5f39_unchanged.jsonl").read_text().splitlines() if ln.strip()]
        assert len(rows) == 7
        b, rec, ran, refused = bead(), None, 0, []
        for r in rows:
            v = park.verdict(rec, b)
            if v:
                refused.append(v.kind)
                continue
            ran += 1
            rec = park.after_question(rec, b, f"run-{ran}", r["t"])
        assert (ran, refused) == (1, ["parked"] * 6)

    def test_the_owner_forcing_it_twice_hits_the_hard_refusal_on_the_third_and_a_change_ends_it(self):
        b, rec, ran = bead(), None, 0
        for n in range(1, 6):
            v = park.verdict(rec, b, fresh=True)
            if v:
                assert (n, v.kind) == (3, "capped")
                break
            ran += 1
            rec = park.after_question(rec, b, f"run-{n}", float(n))
        assert ran == 2
        assert park.verdict(rec, bead(desc="now with a header spec"), fresh=True) is None

    def test_one_run_closed_twice_counts_once(self):
        rec = park.after_question(None, bead(), "r1", 1.0)
        assert park.after_question(rec, bead(), "r1", 2.0).runs == 1
