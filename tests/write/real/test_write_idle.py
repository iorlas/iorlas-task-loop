"""tl-bxk.10.20: the write timeout follows the worker's activity, not the wall clock, and a stopped call's worker is gone before any
retry (lifesim-fld.27.10, -ae6v and -fld.6 each lost 47 min of live work to the 45 min cap). The engine's runner is stream-proc's
`run` with a watcher: delegate gets `--timeout` (the one wall cap) and `--idle` (its own silence limit; a hung worker is a typed stop in
its answer), the engine keeps no silence timer, and the worker's pids come from the live file's first line (WorkerStarted) and from the
answer's `worker.end`, never from ps or a stderr line."""

import os
import sys
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

# isort: split
from support import engine_case as te
from support import fake_route
from support.fake_api import FakeApi
from support.narrow import must
from support.spawn import port_git, real_spawner
from support.who import who

from taskloop.adapters import procs, runner
from taskloop.adapters.delegate import Stopped
from taskloop.app.run import engine
from taskloop.app.slots import config as wslots_config
from tlkernel.env import snapshot
from tlkernel.ids import BeadId

POSIX = os.name != "nt"
MIN = 60.0

@pytest.mark.skipif(not (POSIX), reason="process groups")
class ApiRunnerCall(Case):
    def setup_method(self):
        self.tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        self.d = Path(self.tmp.name)
        self.live = str(self.d / "x.live" / "01-write.jsonl")
        for p in (mock.patch.object(runner, "POLL_S", 0.05),):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.cleanup_worker)

    def cleanup_worker(self):
        f = self.d / "w.pid"
        if f.exists() and f.read_text():
            procs.stop_pid(int(f.read_text()), grace=0.2)
        self.tmp.cleanup()

    def run_call(self, chat_until=0.0, wall=60.0, on_worker=None):
        body = "while [ ! -e '%s' ]; do sleep 0.02; done" % (self.d / "done")
        fake = FakeApi(self.d, body, chat_until)
        r = runner.ApiRunner(self.d / "err.log", wall, self.live, on_worker, grace=0.5)
        request = runner.api.RunRequest(role="worker", brief_file="b.md", cwd=str(self.d), live_file=self.live)
        return r, fake, lambda: r(["delegate"], cwd=str(self.d), timeout=wall, request=request)

    def worker_pid(self):
        return int((self.d / "w.pid").read_text())

    def test_the_worker_is_read_from_the_live_files_first_line_and_a_quiet_one_is_not_stopped(self):
        """Silence is delegate's: the engine's runner stops a call only at the wall limit or a stop of the run."""
        seen = []
        r, fake, go = self.run_call(chat_until=time.time() + 0.4, on_worker=seen.append)
        threading.Thread(target=lambda: (time.sleep(0.6), (self.d / "done").write_text("")), daemon=True).start()
        with fake.patch():
            done = go()
        assert (must(r.worker).pid, must(r.worker).run_id) == (self.worker_pid(), "run1")
        assert seen == [r.worker]
        assert done.returncode == 0
        assert r.stop == {}

    def test_the_wall_limit_stops_the_call_through_cancel(self):
        r, fake, go = self.run_call(wall=0.8)
        with fake.patch(), pytest.raises(Stopped):
            go()
        assert r.stop["kind"] == "wall"
        assert not procs.alive(self.worker_pid())


class SurvivorBlocksTheRetry(te.EngineTest):
    def blocked_write(self, stop_alive=None, worker=None):
        class Script(fake_route.Script):
            def reply(self, role, *a, **kw):
                if role != "worker":
                    return super().reply(role, *a, **kw)
                self.calls.append((role, None, None))
                if stop_alive:
                    self.stop = {"alive": stop_alive, "why": "timeout (no worker output for 25 min)"}
                    raise Stopped("timeout (no worker output for 25 min)")
                return fake_route.answer(self.c, "worker_failed", "r1", worker=worker, exit_code=-15)

        script = Script({"plan": [te.PLAN], "write": [te.WRITE], "review": [te.CLEAN]})
        c = wslots_config.load_cfg(str(self.wt), port_git())
        with te.delegate_stack(script):
            self.eng = engine.Engine(
                BeadId("t-1"), str(self.wt), c, store=self.store, env=snapshot(), spawner=real_spawner(), git=port_git(), who=who()
            )
            rc = self.eng.run()
        return rc, script


for _name in dir(te.EngineTest):  # the engine fixture only: not every test of its class again
    if _name.startswith("test_") and _name not in SurvivorBlocksTheRetry.__dict__:
        setattr(SurvivorBlocksTheRetry, _name, None)
