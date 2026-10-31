"""Factory orchestration uses loop records and fake processes, never a terminal or a service manager."""
import argparse
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import support.paths  # noqa: F401

from taskloop.adapters import factory as adapter
from taskloop.app.launch import factory
from taskloop.app.loop.files import LoopFiles
from taskloop.cli import factory as cli
from taskloop.contracts.env import Env
from taskloop.contracts.identity import Identity
from taskloop.contracts.loop import LoopState
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import Spawner


class Factory(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.files = LoopFiles(ConfigDir(Path(self.temp.name)), "repo-key", lambda pid: pid == 123, lambda: 42)
        self.state = LoopState(pid=123, started=40, t=41, repo="/repo", version="1", actor="loop", code_dir="/code", bead="tl-1")
        self.spawn = Mock(spec=Spawner)
        self.child = Mock(pid=123)
        self.child.poll.return_value = None
        self.spawn.start.return_value = self.child

    def publish(self, _delay):
        self.files.write(self.state)

    def test_start_detaches_through_spawner_and_reuses_live_state(self):
        with patch.object(adapter, "caffeinate_argv", return_value=[]):
            states, already = factory.start(self.files, "/repo", "1", ["python", "tl.py", "loop"], self.spawn, self.publish)
            again, already_again = factory.start(self.files, "/repo", "1", [], self.spawn)
        self.assertFalse(already)
        self.assertTrue(already_again)
        self.assertEqual(states, again)
        self.assertEqual(factory.recorded_pid(self.files), 123)
        self.spawn.start.assert_called_once()
        kwargs = self.spawn.start.call_args.kwargs
        self.assertEqual((kwargs["cwd"], kwargs["stdin"]), ("/repo", "null"))
        self.assertEqual(Path(kwargs["out"].name), self.files.runs() / "factory.log")
        self.assertTrue(kwargs["out"].closed)

    def test_startup_record_prevents_a_second_launch_before_publication(self):
        def publish_after_second_start(_delay):
            states, already = factory.start(self.files, "/repo", "1", [], self.spawn)
            self.assertTrue(already)
            self.assertEqual(states[0].pid, 123)
            self.assertEqual(states[0].actor, "")
            self.publish(_delay)

        with patch.object(adapter, "caffeinate_argv", return_value=[]):
            states, already = factory.start(self.files, "/repo", "1", [], self.spawn, publish_after_second_start)
        self.assertFalse(already)
        self.assertEqual(states, [self.state])
        self.spawn.start.assert_called_once()

    def test_existing_foreground_loop_is_reused_without_a_factory_pid(self):
        self.files.write(self.state)
        states, already = factory.start(self.files, "/repo", "1", [], self.spawn)
        self.assertTrue(already)
        self.assertEqual(states, [self.state])
        self.spawn.start.assert_not_called()

    def test_a_pid_file_without_a_loop_record_is_not_reported_as_running(self):
        (self.files.runs() / "loop.pid").write_text("123\n")
        self.assertEqual(self.files.live(), [])

    def test_dead_loop_record_is_not_reported_as_running(self):
        self.files.write(self.state.replace(pid=456))
        self.assertEqual(self.files.live(), [])

    def test_start_failure_reports_the_log_instead_of_success(self):
        self.child.poll.return_value = 2
        with self.assertRaisesRegex(RuntimeError, "loop exited 2; see .*factory.log"):
            factory.start(self.files, "/repo", "1", [], self.spawn)

    def test_stop_uses_the_same_targeted_graceful_command_for_both_modes(self):
        self.files.write(self.state)
        who = Identity(actor="owner", home=self.temp.name)
        for now, expected in ((False, "after"), (True, "now")):
            args = argparse.Namespace(op="stop", repo=None, now=now)
            with (patch.object(cli.repos, "repo_root", return_value="/repo"),
                  patch.object(cli.loop, "files_of", return_value=self.files),
                  patch.object(factory, "version", return_value="1"),
                  patch.object(self.files, "request_stop", wraps=self.files.request_stop) as stop,
                  redirect_stdout(io.StringIO())):
                self.assertEqual(cli.run(args, Env({}), self.spawn, who, Path("/code")), 0)
            stop.assert_called_once_with(now, "owner")
            self.assertEqual(self.files.stop_for(123, 40), expected)
            self.assertEqual(self.files.stop_for(123, 41), "")
        self.spawn.stop_pid.assert_not_called()

    def test_tail_zero_last_lines_and_follow(self):
        path = self.files.runs() / "factory.log"
        path.write_text("one\ntwo\nthree\n")
        self.assertEqual(list(factory.lines(path, 2)), ["two\n", "three\n"])
        self.assertEqual(list(factory.lines(path, 0)), [])
        with self.assertRaises(ValueError):
            list(factory.lines(path, -1))

        def append(_delay):
            with path.open("a") as stream:
                stream.write("four\n")

        stream = factory.lines(path, 1, True, append)
        try:
            self.assertEqual(next(stream), "three\n")
            self.assertEqual(next(stream), "four\n")
        finally:
            stream.close()

    def test_status_prints_cheap_loop_facts_and_absence_returns_one(self):
        who = Identity(actor="owner", home=self.temp.name)
        args = argparse.Namespace(op="status", repo=None)
        for running in (True, False):
            if running:
                self.files.write(self.state)
            else:
                self.files.remove(123)
            output = io.StringIO()
            with (patch.object(cli.repos, "repo_root", return_value="/repo"),
                  patch.object(cli.loop, "files_of", return_value=self.files),
                  patch.object(factory, "version", return_value="1"),
                  patch.object(cli.dash, "url", side_effect=lambda _: print("DASHBOARD http://localhost:7878")),
                  redirect_stdout(output)):
                result = cli.run(args, Env({}), self.spawn, who, Path("/code"))
            self.assertEqual(result, 0 if running else 1)
            for fact in ("REPO /repo", "VERSION 1", "LOG ", "DASHBOARD http://localhost:7878"):
                self.assertIn(fact, output.getvalue())
            self.assertIn("PID 123" if running else "not running", output.getvalue())
            if running:
                self.assertIn("BEAD tl-1", output.getvalue())

    def test_caffeinate_is_started_through_the_same_detached_port(self):
        with (patch.object(adapter.platform, "system", return_value="Darwin"),
              patch.object(adapter.shutil, "which", return_value="/usr/bin/caffeinate")):
            factory.start(self.files, "/repo", "1", ["python", "tl.py", "loop"], self.spawn, self.publish)
        self.assertEqual(self.spawn.start.call_args.args[0], ["/usr/bin/caffeinate", "-i", "-w", "123"])
        self.assertEqual(self.spawn.start.call_args.kwargs, {"stdin": "null", "out": "null"})

    def test_caffeinate_is_optional_and_darwin_only(self):
        for system, exe in (("Linux", "/bin/caffeinate"), ("Darwin", None)):
            with (patch.object(adapter.platform, "system", return_value=system),
                  patch.object(adapter.shutil, "which", return_value=exe)):
                self.assertEqual(adapter.caffeinate_argv(123), [])

    def test_cli_start_keeps_polling_and_ensures_dashboard_even_when_already_running(self):
        args = argparse.Namespace(op="start", repo=None)
        who = Identity(actor="owner", home=self.temp.name)
        for already in (False, True):
            output = io.StringIO()
            with (patch.object(cli.repos, "repo_root", return_value="/repo"),
                  patch.object(cli.loop, "files_of", return_value=self.files),
                  patch.object(factory, "version", return_value="1"),
                  patch.object(factory, "start", return_value=([self.state], already)) as start,
                  patch.object(cli.dash, "run", return_value=0) as dash,
                  redirect_stdout(output)):
                self.assertEqual(cli.run(args, Env({}), self.spawn, who, Path("/code")), 0)
            argv = start.call_args.args[3]
            self.assertEqual(argv[1:], ["/code/tl.py", "loop", "--repo", "/repo", "--wait-drained"])
            dash.assert_called_once_with("ensure", Env({}), self.spawn)
            self.assertIn("already running" if already else "started", output.getvalue())

    def test_factory_parser_defaults_and_options(self):
        parser = argparse.ArgumentParser()
        cli.add_parser(parser.add_subparsers(dest="cmd"))
        self.assertIsNone(parser.parse_args(["factory", "start"]).repo)
        logs = parser.parse_args(["factory", "logs"])
        self.assertEqual((logs.n, logs.follow), (50, False))
        logs = parser.parse_args(["factory", "logs", "-n", "3", "-f", "--repo", "/repo"])
        self.assertEqual((logs.n, logs.follow, logs.repo), (3, True, "/repo"))
        self.assertTrue(parser.parse_args(["factory", "stop", "--now"]).now)
