"""MANIFEST.sha256: a release commits it, `tl doctor` checks an installed plugin against it and names the file that differs."""
import json
import os
import sys
from pathlib import Path
from unittest import mock

from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from taskloop.adapters.ident import claude_dir, config_dir  # noqa: E402
from taskloop.app.doctor import setup_checks  # noqa: E402
from tlkernel.env import snapshot  # noqa: E402
from tlrelease import catalog, manifest  # noqa: E402

NAME, MARKET = "iorlas-task-loop", "iorlas-marketplace"


class Manifest(Case):
    def setup_method(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "plugin"
        (self.root / "skills").mkdir(parents=True)
        (self.root / "a.txt").write_bytes(b"alpha\n")
        (self.root / "skills" / "tl.py").write_bytes(b"print(1)\n")
        manifest.write(self.root, ["a.txt", "skills/tl.py", manifest.NAME, "dangling"])

    def test_the_manifest_lists_each_file_once_and_not_itself(self):
        lines = (self.root / manifest.NAME).read_text().splitlines()
        assert [x.split("  ")[1] for x in lines] == ["a.txt", "skills/tl.py"]

    def test_a_clean_tree_verifies(self):
        assert manifest.verify(self.root) == []

    def test_one_flipped_byte_names_the_exact_file(self):
        (self.root / "skills" / "tl.py").write_bytes(b"print(2)\n")
        assert manifest.verify(self.root) == ["skills/tl.py differs from MANIFEST.sha256"]

    def test_a_removed_file_and_a_missing_manifest_are_reported(self):
        (self.root / "a.txt").unlink()
        assert manifest.verify(self.root) == ["a.txt is listed in MANIFEST.sha256 but missing"]
        (self.root / manifest.NAME).unlink()
        assert "MANIFEST.sha256 is missing" in manifest.verify(self.root)[0]

    def test_a_file_the_manifest_does_not_list_is_left_alone(self):
        (self.root / "__pycache__").mkdir()
        (self.root / "__pycache__" / "x.pyc").write_bytes(b"\0")
        assert manifest.verify(self.root) == []


class DoctorInstall(Case):
    def setup_method(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        home = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(home / "claude"), "XDG_CONFIG_HOME": str(home / "cfg")})
        env.start()
        self.addCleanup(env.stop)
        self.installed = home / "claude" / "plugins" / "cache" / MARKET / NAME / "1.2.3"
        (self.installed / "skills" / "task-loop").mkdir(parents=True)
        (self.installed / "skills" / "task-loop" / "tl.py").write_bytes(b"print('tl')\n")
        manifest.write(self.installed, ["skills/task-loop/tl.py"])
        (home / "claude" / "plugins" / "installed_plugins.json").write_text(json.dumps(
            {"plugins": {f"{NAME}@{MARKET}": [{"scope": "user", "installPath": str(self.installed)}]}}))
        self.root = home / "running"
        self.root.mkdir()
        (self.root / "AGENTS.md").write_text("# x\n\n## Ownership\n\n| a | b |\n")

    def problems(self):
        def verify_installed():
            claude = claude_dir(snapshot())
            version = catalog.installed_version(claude)
            installed = catalog.cache_dirs(claude).get(version)
            return [f"installed task-loop {version}: {p}" for p in manifest.verify(installed)] if installed else []

        return setup_checks.install_problems(self.root, config_dir(snapshot()), verify_installed)

    def test_a_clean_install_and_an_agents_file_with_its_section_have_no_problem(self):
        assert self.problems() == []

    def test_a_flipped_byte_of_the_installed_plugin_is_reported_with_its_file(self):
        (self.installed / "skills" / "task-loop" / "tl.py").write_bytes(b"print('Tl')\n")
        assert self.problems() == ["installed task-loop 1.2.3: skills/task-loop/tl.py differs from MANIFEST.sha256"]

    def test_an_agents_file_without_the_ownership_section_is_a_problem(self):
        (self.root / "AGENTS.md").write_text("# x\n")
        assert "Ownership" in self.problems()[0]

    def test_the_repos_own_agents_file_has_the_section(self):
        assert [p for p in setup_checks.install_problems(ROOT, config_dir(snapshot()), lambda: []) if "Ownership" in p] == []
