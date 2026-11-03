"""Executable paths are resolved in the check's worktree, including its execute permission."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.adapters.check_probe import PathProbe


class ExecutablePaths(unittest.TestCase):
    def test_a_relative_executable_is_resolved_against_the_worktree(self):
        with tempfile.TemporaryDirectory() as folder:
            tool = Path(folder, "bin", "tool")
            tool.parent.mkdir()
            tool.write_text("#!/bin/sh\nexit 0\n")
            tool.chmod(0o755)
            probe = PathProbe(folder, {"PATH": ""})
            self.assertTrue(probe.has_command("./bin/tool"))
            self.assertTrue(probe.has_command("bin/tool"))
            self.assertTrue(probe.has_command(str(tool)))

    def test_a_file_without_execute_permission_and_a_directory_do_not_resolve(self):
        with tempfile.TemporaryDirectory() as folder:
            tool = Path(folder, "tool")
            tool.write_text("not executable\n")
            tool.chmod(0o644)
            probe = PathProbe(folder, {"PATH": ""})
            self.assertFalse(probe.has_command("./tool"))
            self.assertFalse(probe.has_command("./missing"))
            self.assertFalse(probe.has_command(folder))
