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


def need(test, tool, *args):
    """Skip the running test unless `tool` works here and now (call it in the test body, after setUp has set the test's HOME)."""
    if not working(tool, *args or ("--version",)):
        test.skipTest("needs a real `%s` that works in a fresh directory under the test's environment" % tool)
