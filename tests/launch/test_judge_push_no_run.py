"""`tl judge-push --no-run` reads evidence only: a push without a receipt is refused and no check is started."""
import argparse
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.app.land.push_judge import PushDecision, PushStatus
from taskloop.app.launch import push_judge
from taskloop.contracts.config import EngineConfig


class JudgePushNoRun(unittest.TestCase):
    def run_cmd(self, *, no_run: bool):
        seen = {}

        def judge(repo, stdin, stores, git, check, **kw):
            seen["check"] = check
            return PushDecision(PushStatus.ALLOWED)
        with (mock.patch.object(push_judge, "judge_push", judge), mock.patch.object(push_judge, "real_stores"),
              mock.patch.object(push_judge, "cmd_check", return_value=0) as ran, mock.patch.object(sys, "stdin") as stdin):
            stdin.read.return_value = ""
            push_judge.cmd_judge_push(argparse.Namespace(repo=".", no_run=no_run), who=mock.Mock(), env=mock.Mock(),
                                      spawner=mock.Mock(), git=mock.Mock())
            return seen["check"](mock.Mock(spec=EngineConfig)), ran

    def test_no_run_never_starts_a_check_and_reports_not_green(self):
        code, ran = self.run_cmd(no_run=True)
        self.assertEqual(code, 1)
        ran.assert_not_called()

    def test_default_still_runs_the_check(self):
        code, ran = self.run_cmd(no_run=False)
        self.assertEqual(code, 0)
        ran.assert_called_once()


if __name__ == "__main__":
    unittest.main()
