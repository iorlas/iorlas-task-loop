"""The land gate in .task-loop.json: its script exists; dev/suite.py's exit code follows the suite result."""
import json
import shlex
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dev"))
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
import release  # noqa: E402
import suite  # noqa: E402


class GateCommand(unittest.TestCase):
    def test_the_gate_names_a_script_that_exists(self):
        gate = json.loads((ROOT / ".task-loop.json").read_text(encoding="utf-8"))["engine"]["gate"]
        words = shlex.split(gate)
        self.assertEqual(words[0], "python3")
        self.assertTrue((ROOT / words[1]).is_file(), gate)
        self.assertEqual((ROOT / words[1]).resolve(), (ROOT / "dev" / "suite-docker.py").resolve())

    def test_exit_code_follows_the_suite(self):
        with mock.patch.object(release, "suite", return_value=None) as s:
            self.assertEqual(suite.main(["--repo", "x"]), 0)
            s.assert_called_once_with("x", record=False)
        with mock.patch.object(release, "suite", side_effect=release.Abort("red")), mock.patch("sys.stderr"):
            self.assertEqual(suite.main(["--repo", "x"]), 1)


if __name__ == "__main__":
    unittest.main()
