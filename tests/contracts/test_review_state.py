"""ReviewState is the one review/verify field of the run state: its fields are listed here, it round-trips through dump."""
import json
import sys
from pathlib import Path

import pytest
from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from contracts import samples as S
from tlkernel import wire
from tlkernel.review import ReviewState
from tlkernel.wire import StaleRecord

FIELDS = ["reviews", "rounds", "unchecked", "unverified", "verified", "filed", "unfiled"]


class ReviewStateFields(Case):
    def test_the_fields_are_exactly_these(self):
        assert list(wire.names(ReviewState)) == FIELDS

    def test_an_empty_state_dumps_and_reads_back(self):
        d = ReviewState().dump()
        assert d["v"] == 1
        assert ReviewState.from_dump(json.loads(json.dumps(d))) == ReviewState()

    def test_the_sample_round_trips(self):
        s = S.REVIEW_STATE
        assert ReviewState.from_dump(json.loads(json.dumps(s.dump()))) == s

    def test_a_foreign_version_or_key_is_refused(self):
        with pytest.raises(StaleRecord):
            ReviewState.from_dump({"v": 2})
        with pytest.raises(ValueError):
            ReviewState.from_dump({"v": 1, "extra": 1})
