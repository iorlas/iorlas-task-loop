"""tl-bxk.10.20: the write timeout follows the worker's activity, not the wall clock, and a stopped call's worker is gone before any
retry (lifesim-fld.27.10, -ae6v and -fld.6 each lost 47 min of live work to the 45 min cap). The engine's runner is stream-proc's
`run` with a watcher: delegate gets `--timeout` (the one wall cap) and `--idle` (its own silence limit; a hung worker is a typed stop in
its answer), the engine keeps no silence timer, and the worker's pids come from the live file's first line (WorkerStarted) and from the
answer's `worker.end`, never from ps or a stderr line."""

import inspect
import json
import os
import sys
import textwrap
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

# isort: split
from support import engine_case as te
from support import fake_route

from taskloop.adapters import runner
from taskloop.adapters.delegate import Stopped
from taskloop.app.run import engine
from taskloop.app.wire import slots as wslots
from taskloop.contracts import wire
from taskloop.contracts.config import ConfigError, EngineConfig, load
from taskloop.contracts.delegate import DelegateResult, RunRequest
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


class NoEngineSideSilence(unittest.TestCase):
    def test_the_engine_has_no_warn_stop_cap_timer_of_its_own(self):
        self.assertFalse(hasattr(runner, "Silence") or hasattr(runner, "WATCH_S"))
        self.assertNotIn("silence", inspect.signature(runner.StreamRunner).parameters)
        cfg = set(wire.names(EngineConfig))
        self.assertTrue({"write_idle_min", "write_cap_min"} <= cfg)
        self.assertFalse({"write_idle_warn_min", "write_idle_stop_min"} & cfg)

    def test_a_retired_tier_key_in_the_profile_fails_loudly(self):
        for key in ("write_idle_warn_min", "write_idle_stop_min"):
            with self.assertRaises(ConfigError):
                load({"engine": {key: 15}})


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
            self.eng = engine.Engine(BeadId("t-1"), str(self.wt), c, store=self.store)
            rc = self.eng.run()
        return rc, script

    def test_a_write_whose_worker_outlived_the_stop_fails_the_node_and_is_not_retried(self):
        rc, script = self.blocked_write(stop_alive=[4242])
        self.assertEqual(rc, 2)
        self.assertEqual([x[0] for x in script.calls].count("worker"), 1)  # no second attempt into the same worktree
        self.assertIn("4242", self.eng.why)
        self.assertIn("still alive", self.eng.why)

    def test_worker_survived_in_the_answer_blocks_the_bead_with_the_pids(self):
        worker = {"end": "worker_survived", "stopped": True, "term_sent": True, "kill_sent": True, "waited_s": 9.0,
                  "survivors": [{"pid": 31337, "start": "5"}, {"pid": 31338, "start": "6"}], "pid": 31337, "pgid": 31337, "start": "5"}
        rc, script = self.blocked_write(worker=worker)
        self.assertEqual(rc, 2)
        self.assertEqual([x[0] for x in script.calls].count("worker"), 1)
        for pid in ("31337", "31338"):
            self.assertIn(pid, self.eng.why)

    def test_the_write_call_carries_delegates_idle_limit_and_one_wall_cap_in_its_argv(self):
        script = fake_route.Script({"plan": [te.PLAN], "write": [te.WRITE], "review": [te.CLEAN]})
        c = wslots.load_cfg(str(self.wt))
        argvs = []
        real = RunRequest.to_argv

        def spy(r, py, route):
            argvs.append(real(r, py, route))
            return argvs[-1]

        with te.delegate_stack(script), mock.patch.object(RunRequest, "to_argv", spy):
            engine.Engine(BeadId("t-1"), str(self.wt), c, store=self.store).run()
        by_role = {a[a.index("run") + 1]: a for a in argvs}
        w = by_role["worker"]
        want = (str(int(c.write_idle_min * 60)), str(int(c.write_cap_min * 60)))
        self.assertEqual((w[w.index("--idle") + 1], w[w.index("--timeout") + 1]), want)
        self.assertEqual(w.count("--timeout"), 1)
        self.assertNotIn("--idle", by_role["reviewer"])  # delegate's own default for the others
        self.assertNotIn("--idle", by_role["planner"])

    def test_a_write_under_the_idle_rules_gets_no_close_to_the_limit_warning(self):
        eng = engine.Engine(BeadId("t-1"), str(self.wt), wslots.load_cfg(str(self.wt)), store=self.store)
        r = DelegateResult(data=te.CLEAN, secs=40 * 60)
        eng.records.anomalies("write", r, 1)
        eng.records.anomalies("review", r, 1)
        warned = [json.loads(x)["text"] for x in Path(eng.log_path).read_text().splitlines() if '"warn"' in x]
        self.assertEqual(len(warned), 1)  # the review's, not the write's
        self.assertTrue(warned[0].startswith("review took"))


for _name in dir(te.EngineTest):  # the engine fixture only: not every test of its class again
    if _name.startswith("test_") and _name not in SurvivorBlocksTheRetry.__dict__:
        setattr(SurvivorBlocksTheRetry, _name, None)


if __name__ == "__main__":
    unittest.main()
