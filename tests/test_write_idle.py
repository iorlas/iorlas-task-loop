"""tl-bxk.10.20: the write timeout follows the worker's activity, not the wall clock, and a stopped call's worker is gone before any
retry (lifesim-fld.27.10, -ae6v and -fld.6 each lost 47 min of live work to the 45 min cap). The engine's runner is stream-proc's
`run` with a watcher: delegate gets `--timeout` and `--idle`, the `Silence` here is the backstop, and the worker's pids come from
the live file's first line (WorkerStarted) and from the answer's `worker.end`, never from ps or a stderr line."""

import json
import os
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

# isort: split
from support import engine_case as te
from support import fake_route
from support.narrow import must

from taskloop.adapters import delegate as dg
from taskloop.adapters import procs, runner
from taskloop.adapters.delegate import Stopped
from taskloop.app.release import seams
from taskloop.app.run import engine
from taskloop.app.wire import slots as wslots
from taskloop.contracts.delegate import DelegateResult

POSIX = os.name != "nt"
MIN = 60.0

# route.py stand-in: starts a worker in its own session, writes WorkerStarted as the first line of the live file like delegate, then
# waits for <cwd>/done. Mode "stubborn": the worker ignores SIGTERM. Mode "chatty": the live file keeps moving until CHAT_UNTIL.
ROUTE = textwrap.dedent('''
    import json, os, subprocess, sys, time
    d, mode = sys.argv[sys.argv.index("--cwd") + 1], os.environ.get("FAKE_MODE", "")
    body = "import os, signal, time\\n" + ("signal.signal(signal.SIGTERM, signal.SIG_IGN)\\n" if mode == "stubborn" else "") + \\
           "while not os.path.exists(%r): time.sleep(0.02)\\n" % os.path.join(d, "done")
    w = subprocess.Popen([sys.executable, "-c", body], start_new_session=True)
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


class SilenceRules(unittest.TestCase):
    def setUp(self):
        self.t, self.warns = [1000.0], []
        self.w = runner.Silence(15 * MIN, 25 * MIN, 120 * MIN, on_warn=self.warns.append, clock=lambda: self.t[0])
        self.w.begin()

    def test_process_output_counts_as_activity(self):
        self.t[0] += 24 * MIN
        self.assertEqual(self.w.check(None), "")
        self.w.touch()
        self.t[0] += 24 * MIN
        self.assertEqual(self.w.check(None), "")  # 48 min in all, 24 since the output

    def test_a_live_file_that_moves_counts_as_activity(self):
        self.t[0] += 40 * MIN
        self.assertEqual(self.w.check(self.t[0] - 60), "")

    def test_a_worker_gone_quiet_warns_at_15_min_and_is_stopped_at_25(self):
        self.t[0] += 16 * MIN
        self.assertEqual(self.w.check(None), "")
        self.assertEqual(self.warns, ["write: no worker output for 16 min"])
        self.t[0] += 10 * MIN
        self.assertIn("no worker output for 26 min", self.w.check(None))

    def test_a_warning_is_given_once_per_quiet_stretch(self):
        self.t[0] += 16 * MIN
        self.w.check(None)
        self.t[0] += 3 * MIN
        self.w.check(None)
        self.assertEqual(len(self.warns), 1)
        self.w.touch()
        self.t[0] += 16 * MIN
        self.w.check(None)
        self.assertEqual(len(self.warns), 2)

    def test_the_hard_cap_stops_a_worker_that_never_goes_quiet(self):
        self.t[0] += 121 * MIN
        self.assertEqual(self.w.check(self.t[0]), "hard cap 120 min")


@unittest.skipUnless(POSIX, "process groups")
class StreamRunnerCall(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.d = Path(self.tmp.name)
        (self.d / "route.py").write_text(ROUTE)
        self.live = str(self.d / "x.live" / "01-write.jsonl")
        for p in (mock.patch.object(runner, "POLL_S", 0.05), mock.patch.object(runner, "WATCH_S", 0.05)):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.cleanup_worker)

    def cleanup_worker(self):
        f = self.d / "w.pid"
        if f.exists() and f.read_text():
            procs.stop_pid(int(f.read_text()), grace=0.2)
        self.tmp.cleanup()

    def run_route(self, mode="", silence=None, wall=60.0, on_worker=None, **env):
        r = runner.StreamRunner(self.d / "err.log", silence, wall, self.live, on_worker, grace=0.5)
        cmd = [sys.executable, str(self.d / "route.py"), "--cwd", str(self.d)]
        return r, lambda: r(cmd, cwd=str(self.d), env=dict(os.environ, FAKE_MODE=mode, DELEGATE_LIVE_FILE=self.live, **env), timeout=wall)

    def worker_pid(self):
        return int((self.d / "w.pid").read_text())

    def test_the_worker_is_read_from_the_live_files_first_line(self):
        seen = []
        r, go = self.run_route("chatty", on_worker=seen.append, CHAT_UNTIL=str(time.time() + 0.6))
        go()
        self.assertEqual((must(r.worker).pid, must(r.worker).run_id), (self.worker_pid(), "run1"))
        self.assertEqual(seen, [r.worker])

    def test_a_live_file_that_keeps_moving_keeps_the_call_alive_past_the_silence_limit(self):
        sil = runner.Silence(0.3, 0.6, 30.0)
        r, go = self.run_route("chatty", silence=sil, CHAT_UNTIL=str(time.time() + 1.6))
        done = go()
        self.assertEqual(done.returncode, 0)
        self.assertEqual(r.stop, {})

    def test_a_silent_worker_is_stopped_with_everything_it_started(self):
        sil = runner.Silence(0.2, 0.5, 30.0)
        r, go = self.run_route("stubborn", silence=sil)
        with self.assertRaises(Stopped) as got:
            go()
        self.assertIn("no worker output", got.exception.why)
        self.assertEqual(r.stop["alive"], [])
        self.assertFalse(procs.alive(self.worker_pid()))  # it ignored SIGTERM and is gone: stream-proc proved it
        self.assertIsNotNone(r.obs["kill_t"])
        self.assertEqual(must(r.worker).run_id, "run1")

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
            self.eng = engine.Engine("t-1", str(self.wt), c, store=self.store)
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

    def test_the_write_node_gets_the_idle_limits_from_the_config_and_other_nodes_do_not(self):
        idles = []
        script = fake_route.Script({"plan": [te.PLAN], "write": [te.WRITE], "review": [te.CLEAN]})
        c = wslots.load_cfg(str(self.wt))
        with (
            te.delegate_stack(script),
            mock.patch.object(
                seams.DelegateRoute, "runner", lambda self, log, idle=None, wall=None, live="", on_worker=None: idles.append(idle) or script
            ),
        ):
            engine.Engine("t-1", str(self.wt), c, store=self.store).run()
        seen = dict(zip([x[0] for x in script.calls], idles, strict=False))  # one runner per call, in call order
        self.assertEqual(
            tuple(seen["worker"][:3]), (15 * MIN, 25 * MIN + dg.BACKSTOP_S, 120 * MIN)
        )  # delegate stops at 25 min (--idle), the engine 2 min after
        self.assertIsNone(seen["planner"])
        self.assertIsNone(seen["reviewer"])

    def test_a_write_under_the_idle_rules_gets_no_close_to_the_limit_warning(self):
        eng = engine.Engine("t-1", str(self.wt), wslots.load_cfg(str(self.wt)), store=self.store)
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
