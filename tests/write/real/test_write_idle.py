"""tl-bxk.10.20: the write timeout follows the worker's activity, not the wall clock, and a stopped call's worker is gone before any
retry (lifesim-fld.27.10, -ae6v and -fld.6 each lost 47 min of live work to the 45 min cap). The engine's runner is stream-proc's
`run` with a watcher: delegate gets `--timeout` (the one wall cap) and `--idle` (its own silence limit; a hung worker is a typed stop in
its answer), the engine keeps no silence timer, and the worker's pids come from the live file's first line (WorkerStarted) and from the
answer's `worker.end`, never from ps or a stderr line."""

import os
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

# isort: split
from support import engine_case as te
from support import fake_route
from support.narrow import must

from taskloop.adapters import procs, runner
from taskloop.adapters.delegate import Stopped
from taskloop.app.run import engine
from taskloop.app.wire import slots as wslots
from taskloop.contracts.env import snapshot
from taskloop.contracts.ids import BeadId

POSIX = os.name != "nt"
MIN = 60.0

# route.py stand-in: starts a worker in its own session, writes WorkerStarted as the first line of the live file like delegate, then
# waits for <cwd>/done. Mode "stubborn": the worker ignores SIGTERM. Mode "chatty": the live file keeps moving until CHAT_UNTIL.
ROUTE = textwrap.dedent('''
    import json, os, subprocess, sys, time
    d, mode = sys.argv[sys.argv.index("--cwd") + 1], os.environ.get("FAKE_MODE", "")
    body = ("trap '' TERM\\n" if mode == "stubborn" else "") + "while [ ! -e '%s' ]; do sleep 0.02; done\\n" % os.path.join(d, "done")
    w = subprocess.Popen(["sh", "-c", body], start_new_session=True)  # a shell worker: the interpreter start is not what is tested
    open(os.path.join(d, "w.pid"), "w").write(str(w.pid))
    live = os.environ.get("DELEGATE_LIVE_FILE")
    if live:
        os.makedirs(os.path.dirname(live), exist_ok=True)
        with open(live, "a") as f:
            f.write(json.dumps({"v": 1, "pid": w.pid, "pgid": w.pid, "run_id": "run1"}) + "\\n")
            f.flush()
            while mode == "chatty" and time.time() < float(os.environ["CHAT_UNTIL"]):
                f.write(json.dumps({"t": time.time(), "k": "msg", "text": "still here"}) + "\\n")
                f.flush()
                time.sleep(0.1)
            if mode == "chatty":
                open(os.path.join(d, "done"), "w").close()
    w.wait()
    print(json.dumps({"contract": 3, "data": {}, "ref": "r"}))
''')
@unittest.skipUnless(POSIX, "process groups")
class StreamRunnerCall(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.d = Path(self.tmp.name)
        (self.d / "route.py").write_text(ROUTE)
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

    def run_route(self, mode="", wall=60.0, on_worker=None, **env):
        r = runner.StreamRunner(self.d / "err.log", wall, self.live, on_worker, grace=0.5)
        cmd = [sys.executable, str(self.d / "route.py"), "--cwd", str(self.d)]
        return r, lambda: r(cmd, cwd=str(self.d), env=dict(os.environ, FAKE_MODE=mode, DELEGATE_LIVE_FILE=self.live, **env), timeout=wall)

    def worker_pid(self):
        return int((self.d / "w.pid").read_text())

    def test_the_worker_is_read_from_the_live_files_first_line_and_a_quiet_one_is_not_stopped(self):
        """Silence is delegate's: the engine's runner stops a call only at the wall limit or a stop of the run."""
        seen = []
        r, go = self.run_route("chatty", on_worker=seen.append, CHAT_UNTIL=str(time.time() + 0.4))
        done = go()
        self.assertEqual((must(r.worker).pid, must(r.worker).run_id), (self.worker_pid(), "run1"))
        self.assertEqual(seen, [r.worker])
        self.assertEqual(done.returncode, 0)
        self.assertEqual(r.stop, {})

    def test_the_wall_limit_stops_the_call_through_stream_proc(self):
        r, go = self.run_route("", wall=0.8)
        with self.assertRaises(Stopped):
            go()
        self.assertEqual(r.stop["kind"], "wall")
        self.assertFalse(procs.alive(self.worker_pid()))


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
        c = wslots.load_cfg(str(self.wt))
        with te.delegate_stack(script):
            self.eng = engine.Engine(BeadId("t-1"), str(self.wt), c, store=self.store, env=snapshot())
            rc = self.eng.run()
        return rc, script


for _name in dir(te.EngineTest):  # the engine fixture only: not every test of its class again
    if _name.startswith("test_") and _name not in SurvivorBlocksTheRetry.__dict__:
        setattr(SurvivorBlocksTheRetry, _name, None)


if __name__ == "__main__":
    unittest.main()
