"""The run_bytes adapter over stream-proc's capture_bytes: the run's deadline, subprocess.run's contract, text decoding."""
import subprocess
from unittest import mock

import pytest
import stream_proc
import support.paths  # noqa: F401

from taskloop.adapters import procs
from tltestkit.case import Case


def _bytes(exit_: int = 0, out: bytes = b"", err: bytes = b"", timed_out: bool = False) -> stream_proc.CapturedBytes:
    return stream_proc.CapturedBytes(exit_, out, err, 0.0, timed_out, ())


class CaptureRunner(Case):
    def test_a_timeout_raises_timeout_expired_with_the_partial_bytes(self):
        with mock.patch.object(stream_proc, "capture_bytes", return_value=_bytes(124, b"partial", b"err", True)), \
                pytest.raises(subprocess.TimeoutExpired) as raised:
            procs.run_bytes(["slow"], timeout=1)
        assert (raised.value.output, raised.value.stderr) == (b"partial", b"err")

    def test_inherited_stdin_is_passed_through_unless_input_is_given(self):
        with mock.patch.object(stream_proc, "capture_bytes", return_value=_bytes()) as cap:
            procs.run_bytes(["a"])
            procs.run_bytes(["b"], input=b"x")
            procs.run_bytes(["c"], inherit_stdin=False)
        assert [c.kwargs["stdin"] for c in cap.call_args_list] == [None, subprocess.DEVNULL, subprocess.DEVNULL]
        assert cap.call_args_list[1].kwargs["input"] == b"x"

    def test_adapter_text_decodes_utf8_and_converts_newlines(self):
        with mock.patch.object(stream_proc, "capture_bytes", return_value=_bytes(3, b"a\r\nb\rc\xff", b"err\r\n")):
            r = procs.run(["capture-runner-text"], input="helloé", env={"SENTINEL": "present"})
        assert (r.returncode, r.stdout, r.stderr) == (3, "a\nb\nc�", "err\n")
