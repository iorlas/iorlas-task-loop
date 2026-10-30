"""dev/suite.py's exit code follows the suite result."""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "dev"))
import suite  # noqa: E402

from taskloop.app.release import suite as runner  # noqa: E402
from taskloop.app.release.shell import Abort  # noqa: E402


class GateCommand(unittest.TestCase):
    def test_exit_code_follows_the_suite(self):
        with mock.patch.object(runner, "host_suite", return_value=None) as s:
            self.assertEqual(suite.main(["--repo", "x"]), 0)
            s.assert_called_once_with(ROOT, Path("x"), mock.ANY)
        with mock.patch.object(runner, "host_suite", side_effect=Abort("red")), mock.patch("sys.stderr"):
            self.assertEqual(suite.main(["--repo", "x"]), 1)


if __name__ == "__main__":
    unittest.main()
