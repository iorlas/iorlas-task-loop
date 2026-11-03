"""Accepted-stage pushes own their elapsed time and silence limit, including time in the pre-push hook."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import support.paths  # noqa: F401
from support.narrow import must
from support.narrow_hosts import FakeOutboundHost

from taskloop.app.land.outbound import Outbound
from taskloop.app.run.budget import Budget
from taskloop.app.run.outcomes import run_breakdown
from taskloop.app.run.steps import Steps
from taskloop.app.run.stuck import StuckTick
from taskloop.contracts import log as rec
from taskloop.contracts.gitfacts import GitOutcome
from taskloop.contracts.runlife import silent_limit
from taskloop.contracts.stores import JsonlStore
from taskloop.stores.runlog import RunLog


class PushTiming(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "run.jsonl"
        self.host = FakeOutboundHost()
        self.clock = self.host.clock
        self.host.log = RunLog(JsonlStore(self.path, rec.decode), clock=self.clock.now)
        self.host.steps = Steps(self.host.log, self.clock.now)
        self.budget = Budget(self.host.cfg, self.clock.now)
        self.tick = StuckTick(SimpleNamespace(log=self.host.log, live_now="", now=self.clock.now))
        self.host.steps.begin("review", "review stage 1")
        self.clock.advance(559)
        self.enterContext(mock.patch("taskloop.app.land.outbound.uses_lfs", return_value=False))
        self.enterContext(mock.patch.object(self.host.git, "staged", return_value=False))

    def records(self):
        return [item.rec for item in self.host.log.log.read_from().items]

    def ends(self):
        return [(r.step, r.exec_seconds, r.outcome) for r in self.records() if isinstance(r, rec.StepEnd)]

    def test_long_push_is_booked_to_push_without_a_review_silence_warning(self):
        def push(_wt, _remote, _ref):
            self.assertEqual(must(self.host.steps.cur).step, "push")
            self.clock.advance(2900)
            self.host.log.emit(rec.Beat())
            self.tick.tick()
            self.assertEqual(self.tick.watch.step, "push")
            self.assertFalse([r for r in self.records() if isinstance(r, rec.Stuck)])
            return GitOutcome(ok=True, output="")

        with mock.patch.object(self.host.git, "push_lease", side_effect=push):
            Outbound(self.host).wip_push(1)
        self.assertEqual(self.ends(), [("review", 559, "done"), ("push", 2900, "done")])
        self.assertIsNone(self.host.steps.cur)
        self.assertAlmostEqual(self.budget.spent_min(), 3459 / 60)
        self.assertEqual(self.budget.waited, 0)
        self.assertEqual([(b.step, b.minutes, b.rounds) for b in run_breakdown(self.path)],
                         [("push", 48.0, 1), ("review", 9.0, 1)])

    def test_failed_or_interrupted_push_closes_its_timed_step(self):
        for result in (GitOutcome(ok=False, output="Could not resolve host: origin"), OSError("push interrupted")):
            with self.subTest(result=result):
                self.host.steps.begin("review", "next review")
                self.clock.advance(60)

                def push(_wt, _remote, _ref, result=result):
                    self.clock.advance(2900)
                    if isinstance(result, OSError):
                        raise result
                    return result

                with (mock.patch.object(self.host.git, "push_lease", side_effect=push),
                      self.assertRaises((RuntimeError, OSError))):
                    Outbound(self.host).wip_push(1)
                self.assertEqual(self.ends()[-2:], [("review", 60, "done"), ("push", 2900, "failed")])
                self.assertIsNone(self.host.steps.cur)
                self.tick.tick()
                self.assertFalse([r for r in self.records() if isinstance(r, rec.Stuck)])

    def test_lfs_time_belongs_to_the_same_push_step(self):
        def lfs():
            self.assertEqual(must(self.host.steps.cur).step, "push")
            self.clock.advance(300)
            return 0, ""

        def push(_wt, _remote, _ref):
            self.clock.advance(2900)
            self.tick.tick()
            return GitOutcome(ok=True, output="")

        out = Outbound(self.host)
        with mock.patch.object(out, "lfs_push", side_effect=lfs), mock.patch.object(self.host.git, "push_lease", side_effect=push):
            out.wip_push(1)
        self.assertEqual(self.ends(), [("review", 559, "done"), ("push", 3200, "done")])
        self.assertFalse([r for r in self.records() if isinstance(r, rec.Stuck)])

    def test_failed_lfs_push_is_timed_and_prevents_the_git_push(self):
        def lfs():
            self.clock.advance(2900)
            self.tick.tick()
            return 1, "Could not resolve host: origin"

        out = Outbound(self.host)
        with (mock.patch.object(out, "lfs_push", side_effect=lfs), mock.patch.object(self.host.git, "push_lease") as push,
              self.assertRaisesRegex(RuntimeError, "PAUSE_NETWORK")):
            out.wip_push(1)
        push.assert_not_called()
        self.assertEqual(self.ends(), [("review", 559, "done"), ("push", 2900, "failed")])
        self.assertIsNone(self.host.steps.cur)
        self.assertFalse([r for r in self.records() if isinstance(r, rec.Stuck)])

    def test_push_has_its_own_silence_limit_and_the_next_review_keeps_its_limit(self):
        def push(_wt, _remote, _ref):
            self.clock.advance(silent_limit("push") - 1)
            self.tick.tick()
            self.assertFalse([r for r in self.records() if isinstance(r, rec.Stuck)])
            self.clock.advance(1)
            self.tick.tick()
            stuck = [r for r in self.records() if isinstance(r, rec.Stuck)]
            self.assertEqual([(r.step, r.limit_s) for r in stuck], [("push", silent_limit("push"))])
            return GitOutcome(ok=True, output="")

        with mock.patch.object(self.host.git, "push_lease", side_effect=push):
            Outbound(self.host).wip_push(1)
        self.host.steps.begin("review", "next review")
        self.clock.advance(silent_limit("review"))
        self.tick.tick()
        stuck = [r for r in self.records() if isinstance(r, rec.Stuck)]
        self.assertEqual([r.step for r in stuck], ["push", "review"])

    def test_dry_run_or_custom_land_does_not_start_a_push_step(self):
        for dry, land in ((True, ["git", "push", "origin", "HEAD:main"]), (False, ["custom-land"])):
            with self.subTest(dry=dry, land=land):
                self.host.dry = dry
                self.host.cfg = self.host.cfg.replace(land=land)
                with mock.patch.object(self.host.git, "push_lease") as push:
                    Outbound(self.host).wip_push(1)
                push.assert_not_called()
                self.assertEqual(must(self.host.steps.cur).step, "review")
                self.assertEqual(self.ends(), [])
