"""A plain `pytest -n N` that includes tests/delegate starts its workers: the worker home is not under the real ~/.config, which the
delegate hermetic audit (tests/delegate/hermetic.py) refuses to open anything in."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_workers_start_with_the_delegate_audit_installed():
    env = {k: v for k, v in os.environ.items() if k != "TL_SCRATCH"}
    env["TL_DELEGATE_TESTS"] = "1"
    cmd = [sys.executable, "-m", "pytest", "-n", "1", "--collect-only", "-p", "no:cacheprovider", "-q",
           "tests/delegate/test_live_events.py"]
    ran = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, check=False)
    assert ran.returncode == 0, ran.stdout[-1500:] + ran.stderr[-500:]
    assert "hermetic" not in ran.stdout
