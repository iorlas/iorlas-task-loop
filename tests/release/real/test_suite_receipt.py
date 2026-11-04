"""The release bump is authorized by the judge's ordinary suite receipt, including cached verification."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from taskloop.adapters.git import RealGit
from taskloop.adapters.spawner import RealSpawner
from taskloop.app.checks import authorization
from taskloop.app.land.push_judge import PushStatus, judge_push
from taskloop.app.release import flow, shell, suite
from taskloop.app.release.push import push_main
from taskloop.contracts.env import Env
from taskloop.contracts.ids import CheckId, TreeSha
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.runkey import BaseSha
from taskloop.domain.checks.specs import gate_items
from taskloop.stores.real import real_stores


class ReleaseReceipt(unittest.TestCase):
    def test_judge_finds_bump_receipt_after_green_suite_and_cache_hit(self):
        for cached in (False, True):
            with self.subTest(cached=cached), tempfile.TemporaryDirectory() as tmp:
                self.exercise_release(Path(tmp), cached)

    def exercise_release(self, root, cached):
        repo, origin = root / "repo", root / "origin.git"
        repo.mkdir()
        env = Env({"PATH": os.environ["PATH"], "HOME": str(root), "XDG_CONFIG_HOME": str(root / "config"),
                   "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "TASK_LOOP_SUITE_HOST": "1",
                   "GIT_AUTHOR_NAME": "Release", "GIT_AUTHOR_EMAIL": "release@example.invalid",
                   "GIT_COMMITTER_NAME": "Release", "GIT_COMMITTER_EMAIL": "release@example.invalid"})
        def git(*args):
            return subprocess.run(["git", *args], cwd=repo, env=env.vars, capture_output=True,
                                  text=True, check=True).stdout.strip()
        git("init", "--bare", str(origin))
        git("init", "-b", "main")
        plugin = repo / flow.publish.PLUGIN
        plugin.parent.mkdir(parents=True)
        plugin.write_text('{"version":"1.2.3"}\n')
        (repo / ".task-loop.json").write_text(json.dumps({"engine": {"checks": [
            {"id": "suite", "argv": ["python3", "dev/suite-docker.py"], "run": "gate"}]}}))
        git("add", ".")
        git("commit", "-m", "before release")
        git("remote", "add", "origin", str(origin))
        git("push", "-u", "origin", "main")
        base, before_tree = git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")
        port = RealGit(env)
        sh = shell.of(RealSpawner(env), port, env)
        checks = mock.Mock()
        verify = suite.verify
        if cached:
            verify(repo, repo, sh, checks)
        stores = real_stores(ConfigDir(root / "config/task-loop"))
        run_check = mock.Mock(return_value=1)
        actual_push = port.push
        def judged_push(d, remote, refspec):
            tip, tree = git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")
            self.assertNotEqual(tree, before_tree)
            request = f"refs/heads/main {tip} refs/heads/main {base}\n"
            decision = judge_push(d, request, stores, port, run_check, env=env, spawner=sh.spawner)
            self.assertEqual(decision.status, PushStatus.ALLOWED, decision.reasons)
            run_check.assert_not_called()
            cfg = authorization.profile(port, d, TreeSha(base))
            memo = authorization.memo_for(stores, port, d, cfg, TreeSha(tree), BaseSha(base), env, sh.spawner)
            check = next(c for c in gate_items(cfg) if c.id == CheckId("suite"))
            rec = memo.hit(memo.key(check))
            assert rec is not None
            self.assertEqual((rec.tree, rec.base, rec.result.status), (tree, base, "passed"))
            actual_push(d, remote, refspec)
        with (mock.patch.object(suite, "verify", side_effect=lambda tool, at, shell: verify(tool, at, shell, checks)),
              mock.patch.object(port, "push", side_effect=judged_push)):
            def bump():
                return flow.bump_and_commit(repo, repo, flow.Request("receipt"), sh)
            version = push_main(repo, "receipt", bump(), base, bump, sh)
        self.assertEqual(version, "1.2.4")
        self.assertEqual(git("rev-parse", "HEAD"), git("--git-dir", str(origin), "rev-parse", "main"))
        checks.assert_called_once()
