"""Lifecycle telemetry: a stable fingerprint and started_because on every trace row, whatever ended the run, plus
the structured timing records the lifecycle report reads (gate, vendor error, kill, check cache)."""

import _thread
import json
import os
import signal
import threading
import unittest

import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import engine_case as te
from support import homes

from taskloop.app.run import engine
from taskloop.app.wire import slots as wslots
from taskloop.contracts.env import snapshot
from taskloop.contracts.ids import BeadId
from taskloop.domain.report import matchers as lifecycle

ROOT = te.ROOT
from support.dashes import make_dash  # noqa: E402
from support.spawn import port_git, real_spawner  # noqa: E402
from support.who import who  # noqa: E402

DASH = make_dash()


class TraceTelemetry(te.EngineTest):

    def traces(self):
        path = homes.config_dir() / "traces.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()]

    def records(self, kind):
        return [json.loads(line) for line in self.eng.log_path.read_text().splitlines() if json.loads(line)["kind"] == kind]

    def assert_row(self, outcome=None, because="first"):
        row = self.traces()[-1]
        self.assertEqual(row["started_because"], because)
        self.assertIn(row["started_because"], lifecycle.STARTED_BECAUSE)
        self.assertIn("fingerprint", row)
        self.assertEqual(row["fingerprint"], lifecycle.run_fingerprint(row["outcome"], row["why"]))
        if outcome is not None:
            self.assertEqual(row["outcome"], outcome)
        if row["outcome"] in ("landed", "done"):
            self.assertEqual(row["fingerprint"], "")
        else:
            self.assertTrue(row["fingerprint"])
        for old in ("run", "bead", "repo_url", "worktree", "branch", "version", "started", "ended", "outcome", "why",
                    "cost", "stats", "sessions", "log", "prev_run", "ask"):
            self.assertIn(old, row)
        return row


    @unittest.skipIf(os.name == "nt", "the engine stops a process group; sleep is POSIX")
    def test_an_interrupted_command_leaves_a_kill_record_and_its_tree_is_stopped(self):
        eng = engine.Engine(
            BeadId("t-1"),
            str(self.wt),
            wslots.load_cfg(str(self.wt), port_git()),
            verbose=False,
            store=self.store,
            env=snapshot(),
            spawner=real_spawner(),
            git=port_git(), who=who())
        started = self.wt / "child-started"
        stop_waiting, delivered = threading.Event(), threading.Event()

        def raising(signum, frame):  # the test owns SIGINT: interrupt_main does nothing unless a Python handler is installed
            if delivered.is_set():  # a second interrupt the watcher queued before the first landed: it must not hit tearDown
                return
            delivered.set()
            raise KeyboardInterrupt

        old = signal.signal(signal.SIGINT, raising)
        self.addCleanup(signal.signal, signal.SIGINT, old)

        def interrupt_once_the_child_runs():  # the command itself says it runs: the interrupt cannot land before the child exists
            while not started.exists() and not stop_waiting.wait(0.005):
                pass
            while started.exists() and not delivered.is_set() and not stop_waiting.wait(0.05):
                _thread.interrupt_main()  # sent again until the handler ran: an interrupt that did not land is not a verdict
        watcher = threading.Thread(target=interrupt_once_the_child_runs, daemon=True)
        watcher.start()
        self.addCleanup(watcher.join)
        self.addCleanup(stop_waiting.set)
        with self.assertRaises(KeyboardInterrupt):
            eng.sh(["sh", "-c", 'touch "$0"; exec sleep 30', str(started)], timeout=60)
        kills = [json.loads(line) for line in eng.log_path.read_text().splitlines()
                 if json.loads(line)["kind"] == "kill"]
        self.assertTrue(kills)
        self.assertEqual(kills[-1]["why"], "interrupted")
        self.assertIn("observed_t", kills[-1])


if __name__ == "__main__":
    unittest.main()
