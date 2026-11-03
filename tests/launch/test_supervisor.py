"""Detached supervision refills dead lanes, honors stop, and uses the owner inbox."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import support.paths  # noqa: F401

from taskloop.app.launch import factory, supervisor
from taskloop.app.loop.files import LoopFiles
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import Spawner
from taskloop.contracts.stores import AskStore


class Supervisor(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.files = LoopFiles(ConfigDir(Path(temp.name)), "repo-key", lambda pid: True, lambda: 42)
        self.spawner = Mock(spec=Spawner)
        self.spawner.start.return_value = Mock(pid=123)

    def test_ensure_detaches_once_and_stop_disables_refills(self):
        with (patch.object(supervisor.pidcheck, "proc_start", return_value="token"),
              patch.object(supervisor.pidcheck, "proc_alive", return_value=True)):
            supervisor.ensure(self.files, "/repo", ["tl", "factory", "supervise"], self.spawner, 3)
            supervisor.ensure(self.files, "/repo", [], self.spawner, 2)
        self.spawner.start.assert_called_once()
        self.assertEqual(self.spawner.start.call_args.kwargs["stdin"], "null")
        self.assertEqual(supervisor.enabled(self.files).read_text(), "2")
        supervisor.disable(self.files)
        with patch.object(factory, "_spawn") as spawn:
            factory.start(self.files, "/repo", "1", [], self.spawner, enabled=supervisor.enabled(self.files))
        spawn.assert_not_called()

    def test_dead_lane_refill_is_checked_every_ten_seconds_and_stop_wins(self):
        supervisor.enabled(self.files).write_text("3")
        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) == 2:
                supervisor.disable(self.files)

        with patch.object(factory, "start", return_value=([], 1)) as start:
            self.assertEqual(supervisor.run(self.files, "/repo", "1", ["tl", "loop"], self.spawner, sleep), 0)
        self.assertEqual(sleeps, [10, 10])
        self.assertEqual(start.call_count, 2)
        self.assertEqual(start.call_args.kwargs["lanes"], 3)
        self.assertFalse(supervisor.enabled(self.files).exists())

    def test_failed_restart_notifies_once_and_keeps_retrying(self):
        supervisor.enabled(self.files).write_text("1")
        attempts = []

        def sleep(_seconds):
            attempts.append(1)
            if len(attempts) == 2:
                supervisor.disable(self.files)

        with patch.object(factory, "start", side_effect=RuntimeError("loop exited 2")) as start:
            supervisor.run(self.files, "/repo", "1", [], self.spawner, sleep)
        self.assertEqual(start.call_count, 2)
        asks = AskStore.at(self.files.cfg).all()
        self.assertEqual(len(asks), 1)
        self.assertEqual(asks[0].title, "Factory down")
        self.assertFalse(asks[0].blocking)

    def test_pid_start_token_prevents_reusing_an_unrelated_process(self):
        (self.files.runs() / "supervisor.pid").write_text("123\nold-token\n")
        with patch.object(supervisor.pidcheck, "proc_alive", return_value=False) as alive:
            self.assertFalse(supervisor.alive(self.files))
        alive.assert_called_once_with(123, "old-token")
