"""Tools a test needs for real, found the way the engine will run them: a shim that fails in a fresh directory is not there."""
import shutil
import subprocess
import tempfile


def working(tool, *args):
    """True when `tool args` succeeds in a new empty directory (a mise shim in an untrusted directory does not)."""
    if not shutil.which(tool):
        return False
    with tempfile.TemporaryDirectory() as d:
        try:
            return subprocess.run([tool, *args], cwd=d, capture_output=True, timeout=20).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False


REAL_JUST = working("just", "--version")
