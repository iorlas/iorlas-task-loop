"""With TL_JUDGE_READ_ONLY set (the repo's own pre-push hook), `tl judge-push` reads the receipt and never starts a check."""
import argparse
import sys
from pathlib import Path
from unittest import mock

from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.app.land.push_judge import PushDecision, PushStatus
from taskloop.app.launch import push_judge
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.env import Env


class JudgePushReadOnly(Case):
    def run_cmd(self, env: Env):
        seen = {}

        def judge(repo, stdin, stores, vcs, check, **kw):
            seen["check"] = check
            return PushDecision(PushStatus.ALLOWED)
        with (mock.patch.object(push_judge, "judge_push", judge), mock.patch.object(push_judge, "real_stores"),
              mock.patch.object(push_judge, "cmd_check", return_value=0) as ran, mock.patch.object(sys, "stdin") as stdin):
            stdin.read.return_value = ""
            push_judge.cmd_judge_push(argparse.Namespace(repo="."), who=mock.Mock(), env=env, spawner=mock.Mock(), git=mock.Mock())
            return seen["check"](mock.Mock(spec=EngineConfig)), ran

    def test_read_only_never_starts_a_check_and_reports_not_green(self):
        code, ran = self.run_cmd(Env({"TL_JUDGE_READ_ONLY": "1"}))
        assert code == 1
        ran.assert_not_called()

    def test_otherwise_the_judge_is_the_one_runner(self):
        code, ran = self.run_cmd(Env({}))
        assert code == 0
        ran.assert_called_once()
