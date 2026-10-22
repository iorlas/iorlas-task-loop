"""tl-bxk.10.20: the write timeout follows the worker's activity, not the wall clock, and a stopped call's worker is
proven dead before any retry (lifesim-fld.27.10, -ae6v and -fld.6 each lost 47 min of live work to the 45 min cap, and
fld.27.10's Claude worker kept writing under the Codex retry)."""

import json
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_engine as te  # noqa: E402

import engine  # noqa: E402
import tl  # noqa: E402

POSIX = os.name != "nt"
MIN = 60.0

# route.py stand-in: starts a worker in its own group, names it with a run_id like delegate 0.31.1+, then waits.
# argv: dir mode. The worker ends itself when <dir>/done appears; mode "stubborn" ignores SIGTERM.
ROUTE = textwrap.dedent('''
    import os, signal, subprocess, sys, time
    d, mode = sys.argv[sys.argv.index("--cwd") + 1], os.environ.get("FAKE_MODE", "")
    body = "import os, signal, time\\n" + ("signal.signal(signal.SIGTERM, signal.SIG_IGN)\\n" if mode == "stubborn" else "") + \\
           "while not os.path.exists(%r): time.sleep(0.02)\\n" % os.path.join(d, "done")
    w = subprocess.Popen([sys.executable, "-c", body], start_new_session=True)
    open(os.path.join(d, "w.pid"), "w").write(str(w.pid))
    sys.stderr.write("delegate: worker pid=%d pgid=%d run_id=run1\\n" % (w.pid, w.pid))
    sys.stderr.flush()
    def bye(*_):
        sys.exit(143)  # route.py dies and leaves the worker to the engine's group kill
    signal.signal(signal.SIGTERM, bye)
    w.wait()
    print(\'{"v": 2, "status": "done", "data": {}, "ref": "r"}\')
''')


class Clock:
    """A fake clock: every look at it is `step` seconds later."""

    def __init__(self, step=MIN):
        self.now, self.step = 1000.0, step

    def __call__(self):
        self.now += self.step
        return self.now


@unittest.skipUnless(POSIX, "process groups")
class WriteFollowsTheWorker(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        (self.d / "route.py").write_text(ROUTE)
        (self.d / "session.jsonl").write_text("{}\n")
        runs = self.d / "cfg" / "agent-runs" / "runs"
        runs.mkdir(parents=True)
        (runs / "run1.json").write_text(json.dumps({"id": "run1", "transcript": str(self.d / "session.jsonl")}))
        for p in (mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.d / "cfg"), "APPDATA": str(self.d / "cfg")}),
                  mock.patch.object(engine, "POLL", 0.02), mock.patch.object(engine, "STOP_GRACE", 1),
                  mock.patch.object(engine, "PROOF_TERM", 0.5), mock.patch.object(engine, "PROOF_KILL", 1)):
            p.start()
            self.addCleanup(p.stop)
        self.clock, self.warns = Clock(), []

    def tearDown(self):
        f = self.d / "w.pid"
        if f.exists() and f.read_text():
            with __import__("contextlib").suppress(OSError):
                os.killpg(int(f.read_text()), 9)
        self.tmp.cleanup()

    def worker(self):
        return int((self.d / "w.pid").read_text())

    def gone(self, pid):
        for _ in range(100):
            if not tl.proc_alive(pid):
                return True
            time.sleep(0.05)
        return False

    def call(self, mtime, mode="", wall=47 * MIN, **kw):
        idle = engine.Idle(15 * MIN, 25 * MIN, 120 * MIN, on_warn=self.warns.append, clock=self.clock, mtime=mtime)
        cmd = [sys.executable, str(self.d / "route.py"), "--cwd", str(self.d)]
        stop = {}
        with mock.patch.dict(os.environ, {"FAKE_MODE": mode}):
            res, _ = engine.run_proc(cmd, str(self.d), wall, self.d / "err.log", idle=idle, stop=stop, **kw)
        return res, stop

    def test_a_worker_that_keeps_writing_past_the_old_45_min_cap_is_not_stopped(self):
        def mtime(path):  # the session file moves at every look; after 50 fake minutes the worker ends
            if self.clock.now > 1000 + 50 * MIN:
                (self.d / "done").write_text("")
            return self.clock.now

        res, stop = self.call(mtime)
        self.assertIsNotNone(res)
        self.assertEqual(res[0], 0)
        self.assertEqual(stop, {})
        self.assertGreater(self.clock.now, 1000 + 47 * MIN)  # it outlived today's wall-clock limit
        self.assertEqual(self.warns, [])

    def test_a_worker_gone_quiet_warns_at_15_min_and_is_stopped_at_25(self):
        res, stop = self.call(lambda path: 1000.0)  # the session file never moves again
        self.assertIsNone(res)
        self.assertEqual(self.warns, ["write: no worker output for 15 min"])
        self.assertIn("no worker output for 25 min", stop["why"])
        self.assertEqual(stop["alive"], [])
        self.assertTrue(self.gone(self.worker()))
        self.assertLess(self.clock.now, 1000 + 30 * MIN)

    def test_the_hard_cap_stops_a_worker_that_never_goes_quiet(self):
        res, stop = self.call(lambda path: self.clock.now)
        self.assertIsNone(res)
        self.assertIn("hard cap 120 min", stop["why"])
        self.assertTrue(self.gone(self.worker()))

    def test_a_session_that_cannot_be_found_falls_back_to_the_wall_clock_limit(self):
        (self.d / "cfg" / "agent-runs" / "runs" / "run1.json").unlink()
        res, stop = self.call(lambda path: self.clock.now, wall=47 * MIN)
        self.assertIsNone(res)
        self.assertEqual(self.warns, [])
        self.assertIn("timeout 47 min", stop["why"])
        self.assertGreaterEqual(self.clock.now, 1000 + 47 * MIN)
        self.assertLess(self.clock.now, 1000 + 49 * MIN)

    def test_a_worker_that_ignores_sigterm_is_killed_and_proven_dead(self):
        res, stop = self.call(lambda path: 1000.0, mode="stubborn")
        self.assertIsNone(res)
        self.assertEqual(stop["alive"], [])
        self.assertTrue(self.gone(self.worker()))

    def test_a_worker_that_survives_every_signal_is_reported_alive(self):
        with mock.patch.object(engine, "send_group", return_value=False), mock.patch.object(engine, "send_pid", return_value=False), \
                mock.patch.object(engine, "signal_child", return_value=False):
            res, stop = self.call(lambda path: 1000.0, mode="stubborn")
        self.assertIsNone(res)
        self.assertEqual(stop["alive"], [self.worker()])
        self.assertTrue(tl.proc_alive(self.worker()))

    def test_call_delegate_hands_the_survivors_to_the_engine(self):
        route = self.d / "route.py"
        idle = engine.Idle(15 * MIN, 25 * MIN, 120 * MIN, clock=self.clock, mtime=lambda p: 1000.0)
        with mock.patch.object(engine, "send_group", return_value=False), mock.patch.object(engine, "send_pid", return_value=False), \
                mock.patch.object(engine, "signal_child", return_value=False), mock.patch.dict(os.environ, {"FAKE_MODE": "stubborn"}):
            r, j = engine.call_delegate(str(route), "worker", "x", {"type": "object"}, str(self.d), None, 47 * MIN - 120,
                                        self.d / "err.log", idle=idle)
        self.assertIsNone(j)
        self.assertEqual(r.alive, [self.worker()])
        self.assertIn("timeout", r.error)
        self.assertIn("25 min", r.error)


class IdleRules(unittest.TestCase):
    def watch(self, mtime, **kw):
        self.warns, self.t = [], [0.0]
        w = engine.Idle(15 * MIN, 25 * MIN, 120 * MIN, on_warn=self.warns.append, clock=lambda: self.t[0], mtime=mtime,
                        session=lambda run_id: "/s.jsonl", **kw)
        w.begin()
        return w

    def test_process_output_counts_as_activity(self):
        w = self.watch(lambda p: 0.0)
        for at in (10, 20, 30, 40):  # a line every 10 min: never 25 min quiet
            self.t[0] = at * MIN
            w.touch()
            self.assertEqual(w.check({"run_id": "r"}, 47 * MIN), "")
        self.assertEqual(self.warns, [])

    def test_a_warning_is_given_once_per_quiet_stretch(self):
        w = self.watch(lambda p: 0.0)
        for at in (16, 17, 18):
            self.t[0] = at * MIN
            self.assertEqual(w.check({"run_id": "r"}, 47 * MIN), "")
        self.assertEqual(len(self.warns), 1)
        self.t[0] = 25 * MIN
        self.assertIn("25 min", w.check({"run_id": "r"}, 47 * MIN))

    def test_without_a_run_id_the_wall_clock_decides(self):
        w = self.watch(lambda p: 0.0)
        self.t[0] = 46 * MIN
        self.assertEqual(w.check({}, 47 * MIN), "")  # 46 quiet minutes, but nothing to watch: today's limit only
        self.t[0] = 47 * MIN
        self.assertIn("timeout 47 min", w.check({}, 47 * MIN))
        self.assertEqual(self.warns, [])


class ProveDead(unittest.TestCase):
    def test_it_never_signals_the_engine_its_group_or_its_parent(self):
        table = {os.getpid(): (os.getppid(), os.getpgrp(), "a"), os.getppid(): (1, os.getpgid(os.getppid()), "b"),
                 777: (1, 777, "c")}
        worker = {"pid": 777, "pgid": os.getpgrp(), "start": "c"}  # a route.py that names our own group as its worker
        sent = []
        with mock.patch.object(tl, "proc_table", return_value=table), mock.patch.object(tl, "proc_alive", return_value=True), \
                mock.patch.object(engine.os, "kill", side_effect=lambda p, s: sent.append(p)), \
                mock.patch.object(engine.os, "killpg", side_effect=lambda g, s: sent.append(("g", g))), \
                mock.patch.object(engine.os, "getpgid", side_effect=lambda p: table[p][1]), \
                mock.patch.object(engine, "PROOF_TERM", 0.05), mock.patch.object(engine, "PROOF_KILL", 0.05):
            alive = engine.prove_dead([], worker)
        self.assertEqual(alive, [777])  # still "alive" in this fake world
        self.assertIn(777, sent)
        self.assertNotIn(os.getpid(), sent)
        self.assertNotIn(os.getppid(), sent)
        self.assertNotIn(("g", os.getpgrp()), sent)


class SurvivorBlocksTheRetry(te.EngineTest):
    def test_a_write_whose_worker_outlived_the_stop_fails_the_node_and_is_not_retried(self):
        class Script(te.DelegateScript):
            def __call__(self, route, role, *a, **kw):
                if role != "worker":
                    return super().__call__(route, role, *a, **kw)
                self.calls.append((role, None, None))
                return engine.Result(secs=2820, error="timeout (no worker output for 25 min)", backend="delegate",
                                     alive=[4242]), None

        script = Script({"plan": [te.PLAN], "write": [te.WRITE], "review": [te.CLEAN]})
        c = engine.load_cfg(str(self.wt))
        with mock.patch.object(engine, "find_route", return_value="/fake/route.py"), \
                mock.patch.object(engine, "contract", return_value=te.CONTRACT), \
                mock.patch.object(engine, "call_delegate", script), mock.patch.object(engine.time, "sleep"):
            self.eng = engine.Engine("t-1", str(self.wt), c)
            rc = self.eng.run()
        self.assertEqual(rc, 2)
        self.assertEqual([x[0] for x in script.calls].count("worker"), 1)  # no second attempt into the same worktree
        self.assertIn("4242", self.eng.why)
        self.assertIn("still alive", self.eng.why)

    def test_the_write_node_gets_the_idle_limits_from_the_config_and_other_nodes_do_not(self):
        seen = {}

        class Script(te.DelegateScript):
            def __call__(self, route, role, *a, idle=None, **kw):
                seen[role] = idle
                return super().__call__(route, role, *a, **kw)

        script = Script({"plan": [te.PLAN], "write": [te.WRITE], "review": [te.CLEAN]})
        c = engine.load_cfg(str(self.wt))
        with mock.patch.object(engine, "find_route", return_value="/fake/route.py"), \
                mock.patch.object(engine, "contract", return_value=te.CONTRACT), \
                mock.patch.object(engine, "call_delegate", script), mock.patch.object(engine.time, "sleep"):
            engine.Engine("t-1", str(self.wt), c).run()
        self.assertEqual((seen["worker"].warn, seen["worker"].stop, seen["worker"].cap), (15 * MIN, 25 * MIN, 120 * MIN))
        self.assertIsNone(seen["planner"])
        self.assertIsNone(seen["reviewer"])


for _name in dir(te.EngineTest):  # the engine fixture only: not every test of its class again
    if _name.startswith("test_") and _name not in SurvivorBlocksTheRetry.__dict__:
        setattr(SurvivorBlocksTheRetry, _name, None)


if __name__ == "__main__":
    unittest.main()
