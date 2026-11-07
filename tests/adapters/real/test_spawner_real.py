"""adapters/spawner.py on real processes: capture, the timeout, a child that outlives the call, and the wait that times out."""
import os
import sys
from unittest import mock

# isort: split
import pytest

from taskloop.adapters.spawner import RealSpawner
from tlkernel.env import snapshot
from tlkernel.procport import WaitTimeout
from tltestkit.case import Case


class RealSpawn(Case):
    def test_run_captures_text_and_the_exit_code(self):
        r = RealSpawner(snapshot()).run([sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"])
        assert (r.exit, r.out.strip(), r.err.strip()) == (3, "out", "err")

    def test_a_timeout_is_exit_124(self):
        r = RealSpawner(snapshot()).run([sys.executable, "-c", "import time; time.sleep(30)"], timeout_s=0.3)
        assert (r.exit, r.timed_out) == (124, True)

    def test_a_missing_program_is_an_oserror(self):
        with pytest.raises(OSError):
            RealSpawner(snapshot()).run(["/no/such/program"])

    def test_the_virtualenv_does_not_reach_the_child(self):
        with mock.patch.dict(os.environ, {"VIRTUAL_ENV": "/v"}):
            r = RealSpawner(snapshot()).run([sys.executable, "-c", "import os; print(os.environ.get('VIRTUAL_ENV', 'none'))"])
        assert r.out.strip() == "none"

    def test_stream_passes_both_streams_in_order_and_stops_a_tree_at_its_limit(self):
        got: list[str] = []
        r = RealSpawner(snapshot()).stream([sys.executable, "-c", "print('a', flush=True)"], on_output=got.append)
        assert ("".join(got), r.returncode, r.timed_out) == ("a\n", 0, None)
        sleeper = [sys.executable, "-c", "import time; time.sleep(30)"]
        r = RealSpawner(snapshot()).stream(sleeper, on_output=got.append, timeout_s=0.3, grace=0.5)
        assert (r.timed_out, r.survivors) == ("wall", ())

    def test_a_started_child_waits_times_out_and_stops(self):
        child = RealSpawner(snapshot()).start([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            with pytest.raises(WaitTimeout):
                child.wait(0.2)
            assert child.poll() is None
        finally:
            child.stop(0.5)
        assert child.poll() is not None
