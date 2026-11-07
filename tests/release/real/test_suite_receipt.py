"""The release bump is authorized by the judge's ordinary suite receipt, including cached verification."""
import json
import os
from pathlib import Path
from unittest import mock

from support.checked import run_checked

from taskloop.adapters.git import RealGit
from taskloop.adapters.spawner import RealSpawner
from taskloop.app.land.push_judge import PushStatus, judge_push
from taskloop.app.release import flow, gate, shell
from taskloop.app.release.push import push_main
from taskloop.stores.real import real_stores
from tlgate import authorization
from tlgate.domain.specs import gate_items
from tlkernel.env import Env
from tlkernel.ids import CheckId, TreeSha
from tlkernel.paths import ConfigDir
from tlkernel.runkey import BaseSha
from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory


class ReleaseReceipt(Case):
    def test_judge_finds_bump_receipt_after_green_suite_and_cache_hit(self):
        for cached in (False, True):
            with self.subTest(cached=cached), TemporaryDirectory() as tmp:
                self.exercise_release(Path(tmp), cached)

    def exercise_release(self, root, cached):
        repo, origin = root / "repo", root / "origin.git"
        repo.mkdir()
        env = Env({"PATH": os.environ["PATH"], "HOME": str(root), "XDG_CONFIG_HOME": str(root / "config"),
                   "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
                   "GIT_AUTHOR_NAME": "Release", "GIT_AUTHOR_EMAIL": "release@example.invalid",
                   "GIT_COMMITTER_NAME": "Release", "GIT_COMMITTER_EMAIL": "release@example.invalid"})
        def git(*args):
            return run_checked(["git", *args], repo, env=env.vars, text=True).stdout.strip()
        git("init", "--bare", str(origin))
        git("init", "-b", "main")
        plugin = repo / flow.publish.PLUGIN
        plugin.parent.mkdir(parents=True)
        plugin.write_text('{"version":"1.2.3"}\n')
        (repo / ".task-loop.json").write_text(json.dumps({"engine": {"checks": [
            {"id": "suite", "argv": ["just", "test"], "run": "gate"}]}}))
        git("add", ".")
        git("commit", "-m", "before release")
        git("remote", "add", "origin", str(origin))
        git("push", "-u", "origin", "main")
        base, before_tree = git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")
        port = RealGit(env)
        sh = shell.of(RealSpawner(env), port, env)
        checks = mock.Mock()
        verify = gate.verify
        if cached:
            verify(repo, sh, checks)
        stores = real_stores(ConfigDir(root / "config/task-loop"))
        actual_push = port.push
        def judged_push(d, remote, refspec):
            tip, tree = git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")
            assert tree != before_tree
            request = f"refs/heads/main {tip} refs/heads/main {base}\n"
            decision = judge_push(d, request, stores, port, env=env)
            assert decision.status == PushStatus.ALLOWED, decision.reasons
            cfg = authorization.profile(port, d, TreeSha(base))
            memo = authorization.memo_for(stores, port, d, cfg, TreeSha(tree), BaseSha(base), env)
            check = next(c for c in gate_items(cfg) if c.id == CheckId("suite"))
            rec = memo.hit(memo.key(check))
            assert rec is not None
            assert (rec.tree, rec.base, rec.result.status) == (tree, base, "passed")
            actual_push(d, remote, refspec)
        with (mock.patch.object(gate, "verify", side_effect=lambda at, shell: verify(at, shell, checks)),
              mock.patch.object(port, "push", side_effect=judged_push)):
            def bump():
                return flow.bump_and_commit(repo, flow.Request("receipt"), sh)
            version = push_main(repo, "receipt", bump(), base, bump, sh)
        assert version == "1.2.4"
        assert git("rev-parse", "HEAD") == git("--git-dir", str(origin), "rev-parse", "main")
        checks.assert_called_once()
