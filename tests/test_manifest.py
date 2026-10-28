"""MANIFEST.sha256: a release commits it, `tl doctor` checks an installed plugin against it and names the file that differs."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
import vendored  # noqa: E402,F401

from taskloop.app.release import manifest  # noqa: E402
from taskloop.app.wire import doctor  # noqa: E402

NAME, MARKET = "iorlas-task-loop", "iorlas-marketplace"


class Manifest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "plugin"
        (self.root / "skills").mkdir(parents=True)
        (self.root / "a.txt").write_bytes(b"alpha\n")
        (self.root / "skills" / "tl.py").write_bytes(b"print(1)\n")
        manifest.write(self.root, ["a.txt", "skills/tl.py", manifest.NAME, "dangling"])

    def test_the_manifest_lists_each_file_once_and_not_itself(self):
        lines = (self.root / manifest.NAME).read_text().splitlines()
        self.assertEqual([x.split("  ")[1] for x in lines], ["a.txt", "skills/tl.py"])

    def test_a_clean_tree_verifies(self):
        self.assertEqual(manifest.verify(self.root), [])

    def test_one_flipped_byte_names_the_exact_file(self):
        (self.root / "skills" / "tl.py").write_bytes(b"print(2)\n")
        self.assertEqual(manifest.verify(self.root), ["skills/tl.py differs from MANIFEST.sha256"])

    def test_a_removed_file_and_a_missing_manifest_are_reported(self):
        (self.root / "a.txt").unlink()
        self.assertEqual(manifest.verify(self.root), ["a.txt is listed in MANIFEST.sha256 but missing"])
        (self.root / manifest.NAME).unlink()
        self.assertIn("MANIFEST.sha256 is missing", manifest.verify(self.root)[0])

    def test_a_file_the_manifest_does_not_list_is_left_alone(self):
        (self.root / "__pycache__").mkdir()
        (self.root / "__pycache__" / "x.pyc").write_bytes(b"\0")
        self.assertEqual(manifest.verify(self.root), [])


class DoctorInstall(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
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
        return doctor.install_problems(self.root)

    def test_a_clean_install_and_an_agents_file_with_its_section_have_no_problem(self):
        self.assertEqual(self.problems(), [])

    def test_a_flipped_byte_of_the_installed_plugin_is_reported_with_its_file(self):
        (self.installed / "skills" / "task-loop" / "tl.py").write_bytes(b"print('Tl')\n")
        self.assertEqual(self.problems(), ["installed task-loop 1.2.3: skills/task-loop/tl.py differs from MANIFEST.sha256"])

    def test_an_agents_file_without_the_ownership_section_is_a_problem(self):
        (self.root / "AGENTS.md").write_text("# x\n")
        self.assertIn("Ownership", self.problems()[0])

    def test_the_repos_own_agents_file_has_the_section(self):
        self.assertEqual([p for p in doctor.install_problems(ROOT) if "Ownership" in p], [])


if __name__ == "__main__":
    unittest.main()
