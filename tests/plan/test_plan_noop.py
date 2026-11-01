"""An untouched empty plan parks; existing work keeps the finished-work policy."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.checks import typed
from support.engine_case import PLAN

from taskloop.app.plan.planner import Planner
from taskloop.app.run.blocked import Blocked, blocked_for
from taskloop.contracts.kinds import Kind


class EmptyPlan(unittest.TestCase):
    def host(self, *, done=False, diff="", landed=""):
        host = mock.Mock(done=done, landed_sha=landed, leftovers=[])
        host.checkout.task_diff.return_value = diff
        host.blocked_for = blocked_for
        return host

    def test_noop_with_or_without_followups_and_on_replan(self):
        for leftovers in ([], [{"title": "Follow up", "why": "later"}]):
            for again in (False, True):
                with self.subTest(leftovers=leftovers, again=again):
                    host = self.host()
                    plan = typed(dict(PLAN, stages=[], leftovers=leftovers, summary="x" * 250))
                    with self.assertRaises(Blocked) as caught:
                        Planner(host).finished_work(plan, again)
                    self.assertEqual(caught.exception.kind, Kind.NOOP)
                    self.assertEqual(caught.exception.why, "noop: the plan found nothing to implement: " + "x" * 200)
                    self.assertEqual(host.leftovers, leftovers)
                    host.publish_plan.assert_called_once_with()

    def test_accepted_work_keeps_finished_work_behavior(self):
        for diff in ("", "patch"):
            with self.subTest(diff=diff):
                host = self.host(done=True, diff=diff)
                plan = typed(dict(PLAN, stages=[], leftovers=[{"title": "Follow up", "why": "later"}]))
                self.assertIs(Planner(host).finished_work(plan, False), plan)
                self.assertEqual(host.leftovers, plan["leftovers"])

    def test_existing_diff_or_land_never_becomes_noop(self):
        for host in (self.host(diff="patch"), self.host(landed="abc")):
            with self.assertRaises(Blocked) as caught:
                Planner(host).finished_work(typed(dict(PLAN, stages=[])), False)
            self.assertEqual(caught.exception.kind, Kind.FAULT_PLAN)

    def test_verify_answer_without_work_also_becomes_noop(self):
        host = self.host()
        host.verify_answer = True
        host.wt = "."
        with self.assertRaises(Blocked) as caught:
            Planner(host).accept(typed(dict(PLAN, stages=[])), False)
        self.assertEqual(caught.exception.kind, Kind.NOOP)
