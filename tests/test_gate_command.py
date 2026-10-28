"""The land gate in .task-loop.json: its script exists; dev/suite.py's exit code follows the suite result."""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dev"))
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
import suite  # noqa: E402
from taskloop.app.release import suite as runner  # noqa: E402
from taskloop.app.release.shell import Abort  # noqa: E402


class GateCommand(unittest.TestCase):
    def test_the_gate_names_a_script_that_exists(self):
        gate = json.loads((ROOT / ".task-loop.json").read_text(encoding="utf-8"))["engine"]["gate"]
        words = gate  # an argv list
        self.assertEqual(words[0], "python3")
        self.assertTrue((ROOT / words[1]).is_file(), gate)
        self.assertEqual((ROOT / words[1]).resolve(), (ROOT / "dev" / "suite-docker.py").resolve())

    def test_exit_code_follows_the_suite(self):
        with mock.patch.object(runner, "host_suite", return_value=None) as s:
            self.assertEqual(suite.main(["--repo", "x"]), 0)
            s.assert_called_once_with(ROOT, Path("x"), False)
        with mock.patch.object(runner, "host_suite", side_effect=Abort("red")), mock.patch("sys.stderr"):
            self.assertEqual(suite.main(["--repo", "x"]), 1)


if __name__ == "__main__":
    unittest.main()
