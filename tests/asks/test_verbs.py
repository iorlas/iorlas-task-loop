"""The owner's CLI verb surface: answer --verdict, hold --until (the loop takes 0 claims before T), override --waive/--defer/--drop
with a quoted approval."""

import argparse
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.narrow import must
from support.tiers import domain

from taskloop.adapters.fake_beads import FakeBeads
from taskloop.app.asks import intake, raiser
from taskloop.app.loop.queue import QueueRule
from taskloop.cli import asks as cli
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.ports import NewBead
from taskloop.domain import timespec
from taskloop.domain.asks import specs
from taskloop.stores.memory import fake_stores

T = 1_000_000.0


def parse(*argv: str) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    cli.add_parsers(ap.add_subparsers(dest="cmd"))
    return ap.parse_args(argv)


@domain
class VerbSurface(unittest.TestCase):
    def setUp(self) -> None:
        self.asks = fake_stores().asks
        self.store = FakeBeads()
        self.store.create(NewBead(title="x"))
        raiser.raise_ask(
            self.asks, specs.missing_criteria(), raiser.Asking(bead="fk-1", run="r", brief_hash="h", repo="", title="T", now=T)
        )
        self.out: list[str] = []

    def say(self, *argv: str) -> int:
        return cli.run(parse(*argv), self.asks, lambda _r: self.store, lambda: T + 5, "denis", self.out.append)

    def test_verdict_maps_to_a_typed_action(self) -> None:
        self.assertEqual(self.say("answer", "fk-1", "--verdict", "work"), 0)
        self.assertEqual(must(must(self.asks.get("fk-1")).answer).action, "rerun")
        self.assertEqual(self.say("answer", "fk-1", "--verdict", "decline", "--amend"), 0)
        given = must(must(self.asks.get("fk-1")).answer)
        self.assertEqual((given.action, "declined" in given.text), ("text", True))

    def test_hold_until_is_a_key_that_ends_by_itself(self) -> None:
        self.assertEqual(self.say("hold", "fk-1", "--until", "+2h"), 0)
        meta = self.store.beads["fk-1"].metadata
        until = float(meta[intake.HOLD_UNTIL])
        self.assertEqual(intake.held(meta, until - 1), "denis")
        self.assertEqual(intake.held(meta, until + 1), "")
        self.assertEqual(self.say("hold", "fk-1", "--release"), 0)
        self.assertEqual(intake.held(self.store.beads["fk-1"].metadata, 0), "")

    def test_the_loop_claims_nothing_while_held(self) -> None:
        self.say("hold", "fk-1", "--until", "+2h")
        until = float(self.store.beads["fk-1"].metadata[intake.HOLD_UNTIL])
        b = self.store.beads["fk-1"]
        for now, skipped in ((until - 60, True), (until + 60, False)):
            rule = QueueRule(mock.Mock(), EngineConfig(), {}, lambda _b: "", now=lambda n=now: n)
            q = rule.rank([b], "")
            self.assertEqual((bool(q.skipped), [s.skip.kind for s in q.skipped]), (skipped, ["hold"] if skipped else []))

    def test_override_needs_the_owners_quoted_words(self) -> None:
        self.assertEqual(self.say("override", "fk-1", "--waive", "tests pass", "--approval", ""), 1)
        self.assertEqual(self.say("override", "fk-1", "--defer", "docs"), 1)
        self.assertNotIn(intake.WAIVERS, self.store.beads["fk-1"].metadata)
        self.assertEqual(self.say("override", "fk-1", "--drop", "docs", "--approval", "Denis 10-28: skip the docs"), 0)
        self.assertIn("Denis 10-28: skip the docs", self.store.beads["fk-1"].metadata[intake.WAIVERS])
        self.assertEqual(self.say("override", "fk-1", "replan-cap"), 0)

    def test_times(self) -> None:
        now = datetime(2026, 10, 28, 12, 0).astimezone()
        self.assertEqual(timespec.parse_future("+90m", now), now.timestamp() + 5400)
        self.assertGreater(timespec.parse_future("09:00", now), now.timestamp())
        with self.assertRaises(ValueError):
            timespec.parse_future("2020-01-01T00:00", now)


if __name__ == "__main__":
    unittest.main()
