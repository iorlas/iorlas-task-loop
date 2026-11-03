"""A committed malicious profile cannot make the push judge execute a host command."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401
from support import gitq
from support.engine_case import real_git

from taskloop.adapters.checks_argv import ArgvChecks
from taskloop.adapters.git import RealGit
from taskloop.app.land.push_judge import PushStatus, judge_push
from taskloop.contracts.env import snapshot
from taskloop.contracts.ports import CheckSpec
from taskloop.stores.memory import fake_stores


class PushPolicy(unittest.TestCase):
    @real_git("the judge must reject a real committed malicious profile without creating a canary outside its worktree")
    def test_tip_profile_cannot_execute_on_the_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "worktree"
            repo.mkdir()
            canary = root / "CANARY"
            gitq.git("init", "-q", "-b", "main", cwd=repo)
            for key, value in (("user.name", "t"), ("user.email", "t@x"), ("commit.gpgsign", "false")):
                gitq.git("config", key, value, cwd=repo)
            profile = repo / ".task-loop.json"
            profile.write_text(json.dumps({"engine": {"checks": [{"id": "gate", "argv": ["true"], "run": "gate"}]}}))
            gitq.git("add", ".task-loop.json", cwd=repo)
            gitq.git("commit", "-q", "-m", "trusted policy", cwd=repo)
            base = gitq.git("rev-parse", "HEAD", cwd=repo)
            self.assertTrue(base)
            gitq.git("update-ref", "refs/remotes/origin/main", base, cwd=repo)
            malicious = {"engine": {"checks": [
                {"id": "gate", "argv": ["true"], "run": "gate"},
                {"id": "attack", "argv": ["touch", str(canary)], "run": "gate"}]}}
            profile.write_text(json.dumps(malicious))
            gitq.git("commit", "-q", "-a", "-m", "writer profile", cwd=repo)
            tip = gitq.git("rev-parse", "HEAD", cwd=repo)
            self.assertNotEqual(tip, base)
            env = snapshot()

            def check(policy):
                for step in json.loads(profile.read_text())["engine"]["checks"]:
                    ArgvChecks(env, scratch_home=policy.check_scratch_home).run(CheckSpec(argv=step["argv"], cwd=str(repo)))
                return 0

            checked = mock.Mock(side_effect=check)
            decision = judge_push(str(repo), f"refs/heads/topic {tip} refs/heads/topic {'0' * 40}\n",
                                  fake_stores(), RealGit(env), checked, env=env)
            self.assertEqual(decision.status, PushStatus.REFUSED)
            self.assertTrue(decision.reasons[0].startswith("profile_changed: refs/heads/topic"))
            checked.assert_not_called()
            self.assertFalse(canary.exists())
