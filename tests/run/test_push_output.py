"""The engine shell hands the land complete push output, including diagnostics before the last fifteen lines."""
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

import support.paths  # noqa: F401

from taskloop.app.run.shell import Shell
from taskloop.contracts.log import CmdEnd
from taskloop.stores.memory import fake_stores
from taskloop.stores.runlog import RunLog


class PushOutput(unittest.TestCase):
    def test_push_returns_complete_stdout_and_stderr_capture(self):
        refusal = "gate: refusing the push: run just check\n"
        chunks = ["progress\n" * 250, refusal, "progress\n" * 250, "error: failed to push some refs\n"]
        host = SimpleNamespace(log=RunLog(fake_stores().run_log("r")), wt="/repo", halt=threading.Event(),
                               halt_point=lambda _when: None)
        shell = Shell(host)

        def stream(_cmd, _cwd, _env, _pin, output, *_args):
            output.extend(chunks)
            return SimpleNamespace(timed_out=None, signal=None, returncode=1)

        with mock.patch.object(shell, "stream", side_effect=stream):
            rc, output = shell.run(["git", "push", "origin", "HEAD:main"], pin=True)
        self.assertEqual(rc, 1)
        self.assertEqual(output, "".join(chunks))
        ends = [row.rec for row in host.log.log.read_from().items if isinstance(row.rec, CmdEnd)]
        self.assertEqual(ends[0].out, output)
