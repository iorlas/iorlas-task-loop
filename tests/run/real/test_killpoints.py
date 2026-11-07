"""dev/killpoints.py with a real SIGKILL: one kill point of each phase and the whole tool's exit code on a hold."""
import subprocess
import sys

import pytest
import support.paths

TOOL = support.paths.ROOT / "dev" / "killpoints.py"


@pytest.mark.parametrize("point", ["1:before", "2:after_effect", "3:after_mark"])
def test_a_child_killed_with_sigkill_resumes_to_the_rule(point):
    run = subprocess.run([sys.executable, str(TOOL), "--only", point], capture_output=True, text=True, timeout=60, check=False)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "1 of 1 kill points hold" in run.stdout
