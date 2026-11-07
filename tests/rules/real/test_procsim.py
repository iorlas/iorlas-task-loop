"""The process sim guard is off for a real test: it may spawn (tests/rules/test_procsim.py holds the guard itself)."""
import subprocess
import sys
from pathlib import Path

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class MarkedGuard(Case):
    def test_a_marked_test_may_spawn(self):
        assert subprocess.run(["true"], check=False).returncode == 0  # a fake still answers; a real command runs
        assert subprocess.run(["sleep", "0.01"], check=False).returncode == 0
