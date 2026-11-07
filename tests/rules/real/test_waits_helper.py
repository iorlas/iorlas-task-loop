"""An exited child's inherited stderr pipe must not hang the test worker."""
import os
import signal
import subprocess
import time

import pytest

from tltestkit.waits import until_marker


def test_until_marker_bounds_stderr_read_when_a_grandchild_holds_the_pipe(tmp_path):
    child = subprocess.Popen(["sh", "-c", "sleep 30 & exit 3"], stderr=subprocess.PIPE, start_new_session=True)
    started = time.monotonic()
    try:
        with pytest.raises(AssertionError, match=r"the child exited \(3\) before it wrote its marker: stderr was unreadable"):
            until_marker(tmp_path / "marker", child)
        assert time.monotonic() - started < 10
    finally:
        os.killpg(child.pid, signal.SIGKILL)  # the process group this test started
        child.communicate(timeout=5)
