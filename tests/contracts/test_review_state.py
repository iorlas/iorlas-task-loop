"""ReviewState is the one review/verify field of the run state: its fields are listed here, it round-trips through dump."""
import dataclasses
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402,F401
from contracts import samples as S  # noqa: E402
from taskloop.contracts.codec import CodecError, StaleRecord  # noqa: E402
from taskloop.contracts.review import ReviewState  # noqa: E402

FIELDS = ["reviews", "rounds", "unchecked", "unverified", "verified", "filed", "unfiled"]


class ReviewStateFields(unittest.TestCase):
    def test_the_fields_are_exactly_these(self):
        self.assertEqual([f.name for f in dataclasses.fields(ReviewState)], FIELDS)

    def test_an_empty_state_dumps_and_reads_back(self):
        d = ReviewState().dump()
        self.assertEqual(d["v"], 1)
        self.assertEqual(ReviewState.from_dump(json.loads(json.dumps(d))), ReviewState())

    def test_the_sample_round_trips(self):
        s = S.REVIEW_STATE
        self.assertEqual(ReviewState.from_dump(json.loads(json.dumps(s.dump()))), s)

    def test_a_foreign_version_or_key_is_refused(self):
        with self.assertRaises(StaleRecord):
            ReviewState.from_dump({"v": 2})
        with self.assertRaises(CodecError):
            ReviewState.from_dump({"v": 1, "extra": 1})


if __name__ == "__main__":
    unittest.main()
