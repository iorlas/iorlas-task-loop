"""A land try records the seconds of its fetch, rebase and gate beside why it went on or retried (LandTry)."""
from itertools import count
from unittest import mock

from support.fakegit import FakeGit
from support.narrow_land import table_kit

# isort: split
from tlkernel import log as rec
from tlland.host import Land


def test_a_try_records_the_seconds_of_its_fetch_rebase_and_gate() -> None:
    git = FakeGit(**{"rev_parse__origin/main": ["a"] * 4, "rev_parse__HEAD": ["h", "h", "landed"], "rev_parse__HEAD^{tree}": "tree",
                     "rebase": (0, ""), "log": "", "push": [(0, "")]})
    kit = table_kit(git)
    clock = count(0, 2)  # every reading of the monotonic clock is 2 s after the one before
    with mock.patch("tlland.tries.time.monotonic", side_effect=lambda: float(next(clock))):
        assert kit.lander.inside.run(Land())[0] == "landed"
    (got,) = [r for r in kit.land.emitted() if isinstance(r, rec.LandTry)]
    assert (got.fetch_s, got.rebase_s) == (2.0, 2.0)
    assert got.gate_s >= 0.0
