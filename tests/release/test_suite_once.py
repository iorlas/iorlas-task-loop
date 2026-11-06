"""Verification uses pre-bump content; the same tree under the same selection is verified once."""
from dataclasses import replace
from pathlib import Path
from unittest import mock

import pytest
import support.paths  # noqa: F401
from support.case import Case
from support.shells import quiet_shell
from support.tmpdir import TemporaryDirectory

from taskloop.app.release import flow
from taskloop.app.release.shell import Abort
from taskloop.contracts.env import Env
from taskloop.contracts.gitfacts import StatusRow


class SuiteOnce(Case):
    def setup_method(self):
        tmp = TemporaryDirectory()
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
            assert not port.commit_staged.called

        with mock.patch.object(flow.gate, "verify", side_effect=verify):
            assert flow.bump_and_commit(repo, flow.Request("fix"), sh) == "1.2.4"
        assert seen == ['{"version":"1.2.3"}\n']
        assert "1.2.4" in plugin.read_text()
        port.commit_staged.assert_called_once_with(str(repo), "1.2.4: fix" + flow.publish.TRAILER)

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
        with pytest.raises(Abort, match="beyond"):
            flow.check_bump(self.root, "tested", "1.2.4", sh)
        port.changed_paths.return_value = tracked
        port.status.return_value = [StatusRow(path="src/untested.py", index=" ", work="M")]
        with pytest.raises(Abort, match="changed after"):
            flow.check_bump(self.root, "tested", "1.2.4", sh)
        port.status.return_value = []
        plugin.write_text('{"version":"1.2.5"}')
        with pytest.raises(Abort, match="version or manifest"):
            flow.check_bump(self.root, "tested", "1.2.4", sh)
        flow.manifest.write(self.root, tracked)
        with pytest.raises(Abort, match="version or manifest"):
            flow.check_bump(self.root, "tested", "1.2.4", sh)
        (self.root / flow.manifest.NAME).write_text("")
        with pytest.raises(Abort, match="version or manifest"):
            flow.check_bump(self.root, "tested", "1.2.5", sh)

    def test_the_release_gate_runs_with_the_green_test_ledger_off(self):
        repo = self.root / "repo"
        repo.mkdir()
        (repo / "justfile").write_text("gate:\n")
        port = mock.Mock()
        port.ls_tree.return_value = []
        seen = {}

        def run(cmd, cwd, check=True, *, extra=None, **_):
            seen.update(extra or {})
            return mock.Mock(returncode=0, stdout="", stderr="")

        sh = replace(quiet_shell(), port=port, env=Env({"TL_GREEN_LEDGER": "1"}), run=run)
        flow.gate.gate(repo, sh)
        assert seen["TL_GREEN_LEDGER"] == ""
