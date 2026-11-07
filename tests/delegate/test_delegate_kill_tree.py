"""Tree kill: a worker stopped by timeout, reap or the app-server path leaves no descendant, whatever session it sits in."""

import contextlib
import re
import shutil
import sys
import time
from pathlib import Path
from unittest import mock

import hermetic  # noqa: F401  (a home of its own for every test)
from stream_proc import proc_start
from test_route import ROOT

from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

# A fake of the Codex CLI: a node-shim analogue that starts a native child in a session of its own; the child ignores SIGTERM.
CHILD = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(300)"
SHIM = (
    "import subprocess,sys,time; "
    "c = subprocess.Popen([sys.executable, '-c', %r], start_new_session=True); "
    "open(sys.argv[1], 'w').write(str(c.pid)); time.sleep(300)"
).replace("%r", repr(CHILD))


def wait_for(path, seconds=10):
    end = time.time() + seconds
    while time.time() < end:
        with contextlib.suppress(OSError, ValueError):
            return int(Path(path).read_text())
        time.sleep(0.05)
    raise AssertionError("the shim never started its child")


def gone(pid, start, seconds=15):
    end = time.time() + seconds
    while time.time() < end:
        if proc_start(pid) != start:
            return True
        time.sleep(0.2)
    return False




class KillPaths(Case):
    def fake_server(self, body):
        """A `codex` whose app-server runs `body` (python); returns the which() patch."""
        d = TemporaryDirectory()
        self.addCleanup(d.cleanup)
        exe = Path(d.name) / "codex"
        exe.write_text(f"#!{sys.executable}\nimport sys, time\n{body}\n")
        exe.chmod(0o755)
        return mock.patch.object(shutil, "which", return_value=str(exe))



    def test_no_pattern_kills_and_no_bare_kill_in_router(self):
        src = "".join((ROOT / "src" / "delegate" / f).read_text(encoding="utf-8") for f in ("entry.py", "adapters/procs.py"))
        assert re.search(r"pkill|killall|pgrep", src) is None
        assert re.search(r"\.kill\(\)|os\.kill", src) is None  # every stop goes through stream_proc
        assert len(re.findall(r"\.terminate\(\)", src)) == 0
