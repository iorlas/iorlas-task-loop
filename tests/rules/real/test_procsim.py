"""The process sim guard is off for a real test: it may spawn (tests/rules/test_procsim.py holds the guard itself)."""
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)


class MarkedGuard(unittest.TestCase):
    def test_a_marked_test_may_spawn(self):
        self.assertEqual(subprocess.run(["true"], check=False).returncode, 0)  # a fake still answers; a real command runs
        self.assertEqual(subprocess.run(["sleep", "0.01"], check=False).returncode, 0)


if __name__ == "__main__":
    unittest.main()
