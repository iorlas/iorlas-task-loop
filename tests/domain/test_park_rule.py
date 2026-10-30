"""tl-7y6.7.3: park is a state transition. The rule (domain/beads/park.py) and the d5f.39 replay: 7 runs on an unchanged bead."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

# isort: split
from taskloop.contracts.bead import Bead
from taskloop.contracts.ids import BeadId
from taskloop.contracts.parks import Park
from taskloop.domain.beads import park

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "replay"


def bead(desc="do it", ac="- works", title="t", **kw):
    return Bead(id=BeadId("t-1"), title=title, status="open", description=desc, acceptance_criteria=ac, **kw)


class TextHash(unittest.TestCase):
    def test_title_description_and_acceptance_change_the_hash_nothing_else_does(self):
        base = park.text_hash(bead())
        self.assertNotEqual(base, park.text_hash(bead(desc="do it better")))
        self.assertNotEqual(base, park.text_hash(bead(ac="- works fast")))
        self.assertNotEqual(base, park.text_hash(bead(title="u")))
        self.assertEqual(base, park.text_hash(bead(labels=["x"], notes="Land (engine): x", priority=0)))
        self.assertNotEqual(park.text_hash(bead(title="a", desc="b")), park.text_hash(bead(title="ab", desc="")))


class Verdict(unittest.TestCase):
    def rec(self, runs, b=None):
        return Park(bead=BeadId("t-1"), hash=park.text_hash(b or bead()), runs=runs, run="r1", t=1.0)

    def test_no_record_or_a_changed_text_is_free(self):
        self.assertIsNone(park.verdict(None, bead()))
        self.assertIsNone(park.verdict(self.rec(1), bead(desc="changed")))
        self.assertIsNone(park.verdict(self.rec(5), bead(ac="- changed")))

    def test_the_first_question_parks_the_bead_until_it_changes_but_fresh_or_an_answer_runs_it(self):
        v = park.verdict(self.rec(1), bead())
        self.assertEqual(v.kind if v else None, "parked")
        self.assertIsNone(park.verdict(self.rec(1), bead(), fresh=True))
        self.assertIsNone(park.verdict(self.rec(1), bead(), answered=True))

    def test_the_third_run_on_one_text_is_refused_even_by_fresh(self):
        for kw in ({}, {"fresh": True}):
            v = park.verdict(self.rec(2), bead(), **kw)
            self.assertEqual(v.kind if v else None, "capped", kw)
        self.assertIsNone(park.verdict(self.rec(2), bead(), answered=True))  # the answer is new input
        self.assertIsNone(park.verdict(self.rec(2), bead(desc="changed"), fresh=True))


class Replay(unittest.TestCase):
    def test_d5f39_seven_runs_on_an_unchanged_bead_are_one_run_then_a_refusal(self):
        rows = [json.loads(ln) for ln in (FIX / "d5f39_unchanged.jsonl").read_text().splitlines() if ln.strip()]
        self.assertEqual(len(rows), 7)
        b, rec, ran, refused = bead(), None, 0, []
        for r in rows:
            v = park.verdict(rec, b)
            if v:
                refused.append(v.kind)
                continue
            ran += 1
            rec = park.after_question(rec, b, f"run-{ran}", r["t"])
        self.assertEqual((ran, refused), (1, ["parked"] * 6))

    def test_the_owner_forcing_it_twice_hits_the_hard_refusal_on_the_third_and_a_change_ends_it(self):
        b, rec, ran = bead(), None, 0
        for n in range(1, 6):
            v = park.verdict(rec, b, fresh=True)
            if v:
                self.assertEqual((n, v.kind), (3, "capped"))
                break
            ran += 1
            rec = park.after_question(rec, b, f"run-{n}", float(n))
        self.assertEqual(ran, 2)
        self.assertIsNone(park.verdict(rec, bead(desc="now with a header spec"), fresh=True))

    def test_one_run_closed_twice_counts_once(self):
        rec = park.after_question(None, bead(), "r1", 1.0)
        self.assertEqual(park.after_question(rec, bead(), "r1", 2.0).runs, 1)
