"""Verification uses pre-bump content and warms a shared cache before offline workers spawn."""
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

import support.paths  # noqa: F401
from support.shells import quiet_shell

from taskloop.adapters.childenv import tool_env
from taskloop.app.release import flow, suite
from taskloop.app.release.cache import SuiteCache
from taskloop.app.release.shell import Abort
from taskloop.contracts.env import Env
from taskloop.contracts.gitfacts import StatusRow
from taskloop.contracts.paths import ConfigDir


class SuiteOnce(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.env = Env({"XDG_CONFIG_HOME": str(self.root / "cfg"), "XDG_CACHE_HOME": str(self.root / "cache")})

    def test_bump_checks_the_tree_before_mutating_version_or_manifest(self):
        repo = self.root / "repo"
        plugin = repo / flow.publish.PLUGIN
        plugin.parent.mkdir(parents=True)
        plugin.write_text('{"version":"1.2.3"}\n')
        port = mock.Mock()
        port.rev_parse.return_value = "before"
        port.show.return_value = plugin.read_text()
        port.ls_files.return_value = [flow.publish.PLUGIN]
        port.ls_tree.return_value = []
        port.changed_paths.return_value = [flow.publish.PLUGIN, flow.manifest.NAME]
        port.status.return_value = []
        sh = replace(quiet_shell(), port=port, env=self.env)
        seen = []

        def verify(*args):
            seen.append(plugin.read_text())
            self.assertFalse(port.commit_staged.called)

        with mock.patch.object(flow.suite, "verify", side_effect=verify):
            self.assertEqual(flow.bump_and_commit(repo, repo, flow.Request("fix"), sh), "1.2.4")
        self.assertEqual(seen, ['{"version":"1.2.3"}\n'])
        self.assertIn("1.2.4", plugin.read_text())
        port.commit_staged.assert_called_once_with(str(repo), "1.2.4: fix" + flow.publish.TRAILER)

    def test_same_pre_bump_tree_reuses_green_and_red_never_records_one(self):
        port = mock.Mock()
        port.rev_parse.return_value = "pre-bump-tree"
        sh = replace(quiet_shell(), port=port, env=self.env)
        checks = mock.Mock()
        self.assertFalse(suite.verify(self.root, self.root, sh, checks))
        self.assertTrue(suite.verify(self.root, self.root, sh, checks))
        checks.assert_called_once()
        port.rev_parse.assert_called_with(str(self.root), "HEAD^{tree}")
        port.rev_parse.return_value = "changed-tree"
        self.assertFalse(suite.verify(self.root, self.root, sh, checks))
        self.assertEqual(checks.call_count, 2)
        port.rev_parse.return_value = "red-tree"
        with self.assertRaises(Abort):
            suite.verify(self.root, self.root, sh, mock.Mock(side_effect=Abort("red")))
        store = SuiteCache(ConfigDir(self.root / "cfg" / "task-loop"))
        self.assertFalse(any(g.tree == "red-tree" for g in store._all()))

    def test_post_bump_check_rejects_unexpected_changes_dirty_tree_and_corrupt_metadata(self):
        plugin = self.root / flow.publish.PLUGIN
        plugin.parent.mkdir(parents=True)
        plugin.write_text('{"version":"1.2.4"}')
        tracked = [flow.publish.PLUGIN, flow.manifest.NAME]
        flow.manifest.write(self.root, tracked)
        port = mock.Mock()
        port.changed_paths.return_value = tracked
        port.status.return_value = []
        port.ls_files.return_value = tracked
        sh = replace(quiet_shell(), port=port)
        flow.check_bump(self.root, "tested", "1.2.4", sh)
        port.changed_paths.return_value = [*tracked, "src/untested.py"]
        with self.assertRaisesRegex(Abort, "beyond"):
            flow.check_bump(self.root, "tested", "1.2.4", sh)
        port.changed_paths.return_value = tracked
        port.status.return_value = [StatusRow(path="src/untested.py", index=" ", work="M")]
        with self.assertRaisesRegex(Abort, "changed after"):
            flow.check_bump(self.root, "tested", "1.2.4", sh)
        port.status.return_value = []
        plugin.write_text('{"version":"1.2.5"}')
        with self.assertRaisesRegex(Abort, "version or manifest"):
            flow.check_bump(self.root, "tested", "1.2.4", sh)
        flow.manifest.write(self.root, tracked)
        with self.assertRaisesRegex(Abort, "version or manifest"):
            flow.check_bump(self.root, "tested", "1.2.4", sh)
        (self.root / flow.manifest.NAME).write_text("")
        with self.assertRaisesRegex(Abort, "version or manifest"):
            flow.check_bump(self.root, "tested", "1.2.5", sh)

    def test_host_suite_prewarms_the_tested_projects_dependencies(self):
        repo = self.root / "clone"
        repo.mkdir()
        (repo / "pyproject.toml").write_text("[project]\nname = 'tested'\n")
        with mock.patch.object(suite, "available_mb", return_value=8192), \
                mock.patch.object(suite, "prewarm") as warm, \
                mock.patch.object(suite, "run_parts", return_value=[]), \
                mock.patch.object(suite, "merge_outputs", return_value=("", True)):
            sh = replace(quiet_shell(), env=self.env)
            suite._host_suite(self.root, repo, sh)
        warm.assert_called_once_with(repo, sh)

    def test_prewarm_and_isolated_workers_share_cache_and_children_stay_offline(self):
        calls = []
        sh = replace(quiet_shell(), env=self.env, run=mock.Mock(side_effect=lambda *a, **kw: calls.append((a, kw))))
        suite.prewarm(self.root, sh)
        self.assertEqual(calls[0][0][0][:2], ["uv", "sync"])
        self.assertEqual(len(calls), 4)
        cache = str(self.root / "cache" / "task-loop" / "uv")
        self.assertTrue(all(kw["extra"] == {"UV_CACHE_DIR": cache, "UV_OFFLINE": "0"} for _, kw in calls))
        env = suite.isolated_env(self.root / "worker", self.env)
        self.assertEqual((env["UV_CACHE_DIR"], env["UV_OFFLINE"]), (cache, "1"))
        child = tool_env(env)
        self.assertEqual((child["UV_CACHE_DIR"], child["UV_OFFLINE"]), (cache, "1"))

    def test_isolated_workers_never_carry_the_owners_hooks_path(self):
        env = suite.isolated_env(self.root / "worker", self.env)
        keys = [env[f"GIT_CONFIG_KEY_{i}"].lower() for i in range(int(env.get("GIT_CONFIG_COUNT", "0")))]
        self.assertNotIn("core.hookspath", keys)
