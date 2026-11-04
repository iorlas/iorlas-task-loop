"""Captured runner lifecycle: held signals and exceptional waits stop the tree and close all descriptors."""
import subprocess
from unittest import mock

import pytest
import support.paths  # noqa: F401
from support.case import Case

from taskloop.adapters import procs


class CaptureRunner(Case):
    def test_timeout_stops_the_tree_and_drains_partial_output_before_raising(self):
        child, hold = mock.Mock(), mock.Mock()
        child.communicate.side_effect = [subprocess.TimeoutExpired(["slow"], 1, output=b"part"), (b"partial", b"err")]
        # Enter below the simulator's run_bytes boundary: this tests the real captured runner with a fake Popen.
        with (mock.patch.object(procs, "popen_held", return_value=(child, hold)), mock.patch.object(procs, "stop_tree") as stop,
              pytest.raises(subprocess.TimeoutExpired) as raised):
            procs.run(["capture-runner-timeout"], timeout=1)
        assert (raised.value.output, raised.value.stderr) == (b"partial", b"err")
        stop.assert_called_once_with(child, grace=procs.STOP_GRACE_S)
        hold.replay.assert_called_once_with()
        child.communicate.assert_has_calls([mock.call(input=None, timeout=1), mock.call(timeout=2.0)])
        for pipe in (child.stdin, child.stdout, child.stderr):
            pipe.close.assert_called_once_with()

    def test_a_held_signal_that_raises_stops_the_tree_before_propagating(self):
        child, hold = mock.Mock(), mock.Mock()
        hold.replay.side_effect = KeyboardInterrupt
        with (mock.patch.object(procs, "popen_held", return_value=(child, hold)), mock.patch.object(procs, "stop_tree") as stop,
              pytest.raises(KeyboardInterrupt)):
            procs.run(["capture-runner-interrupted"])
        stop.assert_called_once_with(child, grace=procs.STOP_GRACE_S)
        child.communicate.assert_not_called()
        for pipe in (child.stdin, child.stdout, child.stderr):
            pipe.close.assert_called_once_with()

    def test_adapter_text_decodes_utf8_and_converts_newlines(self):
        child, hold = mock.Mock(), mock.Mock()
        child.communicate.return_value = (b"a\r\nb\rc\xff", b"err\r\n")
        child.wait.return_value = 3
        with mock.patch.object(procs, "popen_held", return_value=(child, hold)):
            r = procs.run(["capture-runner-text"], input="hello\u00e9", env={"SENTINEL": "present"})
        assert (r.returncode, r.stdout, r.stderr) == (3, "a\nb\nc\ufffd", "err\n")
        child.communicate.assert_called_once_with(input=b"hello\xc3\xa9", timeout=None)
