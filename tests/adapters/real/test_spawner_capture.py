"""Captured processes stop grandchildren on timeout and preserve stdin, exact bytes and inherited output."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from taskloop.adapters import procs
from taskloop.adapters.spawner import RealSpawner
from tlkernel.env import snapshot
from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory


class CapturedProcesses(Case):
    def test_run_timeout_kills_grandchildren_and_keeps_partial_output(self):
        child = ("import os, signal, sys, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                 "print(os.getpid(), flush=True); os.write(2, b'partial\\xff'); time.sleep(60)")
        for detached in (False, True):
            with self.subTest(detached=detached), TemporaryDirectory() as tmp:
                pidfile = Path(tmp) / "pid"
                parent = ("import subprocess, sys, time; from pathlib import Path; "
                          f"p = subprocess.Popen([sys.executable, '-c', {child!r}], start_new_session={detached}); "
                          "Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(60)")
                try:
                    with mock.patch.object(procs, "STOP_GRACE_S", 0.1):
                        r = RealSpawner(snapshot()).run([sys.executable, "-c", parent, str(pidfile)], timeout_s=1)
                    assert (r.exit, r.timed_out, r.err) == (124, True, "partial\ufffd")
                    pid = int(pidfile.read_text())
                    assert r.out.strip() == str(pid)
                    assert not procs.alive(pid), f"grandchild {pid} survived the capture timeout"
                finally:
                    if pidfile.exists():
                        procs.stop_pid(int(pidfile.read_text()), grace=0.1)

    def test_run_bytes_preserves_binary_stdout_and_stderr(self):
        code = "import os; os.write(1, b'\\x00\\xff\\r\\n'); os.write(2, b'\\xfe'); raise SystemExit(3)"
        r = RealSpawner(snapshot()).run_bytes([sys.executable, "-c", code])
        assert (r.exit, r.out, r.err) == (3, b"\x00\xff\r\n", b"\xfe")

    def test_input_and_large_output_do_not_deadlock(self):
        code = "import sys; sys.stdout.write('x' * 200000); sys.stdout.flush(); sys.stdout.write(sys.stdin.read())"
        r = RealSpawner(snapshot()).run([sys.executable, "-c", code], input="y" * 200000, timeout_s=3)
        assert (r.exit, r.out) == (0, "x" * 200000 + "y" * 200000)

    def test_capture_false_inherits_output_and_still_supplies_input(self):
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            code = ("import os, sys; from taskloop.adapters.spawner import RealSpawner; "
                    "from tlkernel.env import snapshot; "
                    "r = RealSpawner(snapshot()).run([sys.executable, '-c', "
                    "\"import sys; print(sys.stdin.read()); print('err', file=sys.stderr)\"], "
                    "input='in', capture=False, timeout_s=3); "
                    "assert (r.exit, r.out, r.err) == (0, '', '')")
            p = procs.spawn([sys.executable, "-c", code], stdout=out, stderr=err, env=dict(os.environ))
            try:
                assert p.wait(5) == 0
            finally:
                procs.stop_tree(p, grace=0.1)
            out.seek(0)
            err.seek(0)
            assert (out.read(), err.read()) == (b"in\n", b"err\n")

    def test_adapter_bytes_timeout_preserves_partial_bytes(self):
        code = "import os, time; os.write(1, b'\\xff'); os.write(2, b'\\xfe'); time.sleep(60)"
        with pytest.raises(subprocess.TimeoutExpired) as raised:
            procs.run_bytes([sys.executable, "-c", code], timeout=0.5)
        assert (raised.value.output, raised.value.stderr) == (b"\xff", b"\xfe")
