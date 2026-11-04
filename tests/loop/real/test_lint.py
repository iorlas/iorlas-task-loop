"""tl-7y6.7.1 / .7.2: the bead rule table (a fixture per rule), `tl lint`, and the loop's once-only refusal of a failing bead."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

# isort: split
from support import looptest
from support.fakes import as_bead
from support.narrow import must

from loop.test_loop import LoopBase, bead, rec
from taskloop.domain.beads import rules

GOOD = {"id": "t-1", "title": "t", "status": "open", "issue_type": "task", "description": "do it", "acceptance_criteria": "- it works"}


def fails(children=False, **f):
    return [x.rule for x in rules.failures(must(as_bead(dict(GOOD, **f))), "/repo", lambda: children)]


class Refusal(LoopBase):
    """Beads shaped like tl-pg0 (no acceptance), an epic with children and a decision are never claimed."""

    def test_failing_beads_are_never_claimed_and_are_labelled_and_commented_once(self):
        shaped = [dict(bead("x-1"), acceptance_criteria=""), dict(bead("x-3"), issue_type="decision"), bead("x-4")]
        bd = self.bd = self.fake(*shaped, bead("x-2", type="epic"), slots=2)
        self.script = {"x-4": [rec("landed")]}
        assert self.run_loop() == 0
        assert [b for b, _ in self.started] == ["x-4"]
        assert not [c for c in bd.calls if c[:2] == ("update", "x-1") and "--claim" in c]
        for bid in ("x-1", "x-3"):
            assert sum(c == ("label", "add", bid, "needs-ac") for c in bd.calls) == 1, bid
            assert sum(c[:3] == ("comments", "add", bid) for c in bd.calls) == 1, bid
        assert self.out.count("skip x-1:") == 1

    def test_a_bead_that_already_has_the_label_gets_no_second_comment(self):
        bd = self.fake(dict(bead("x-1", labels=["needs-ac"]), acceptance_criteria=""), slots=2)
        self.run_loop()
        assert not [c for c in bd.calls if c[0] in ("comments", "label")]
        assert looptest.queue(str(self.repo))[1] == [("x-1", "R2: no acceptance criteria")]
