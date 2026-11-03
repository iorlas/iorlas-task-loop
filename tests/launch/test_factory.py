"""Factory orchestration uses loop records and fake processes, never a terminal or a service manager."""
import argparse
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import support.paths  # noqa: F401

from taskloop.adapters import factory as adapter
from taskloop.app.launch import factory
from taskloop.app.loop.files import LoopFiles
from taskloop.cli import factory as cli
from taskloop.contracts.config import RepoProfile, SlotsConfig
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
        self.assertEqual(already, 1)
        self.assertEqual(already_again, 0)
        self.assertEqual(states, again)
        self.assertEqual(factory.recorded_pid(self.files), 123)
        self.spawn.start.assert_called_once()
        kwargs = self.spawn.start.call_args.kwargs
        self.assertEqual((kwargs["cwd"], kwargs["stdin"]), ("/repo", "null"))
        self.assertEqual(Path(kwargs["out"].name), self.files.runs() / "factory-lane-1.log")
        self.assertTrue(kwargs["out"].closed)

    def test_startup_record_prevents_a_second_launch_before_publication(self):
        def publish_after_second_start(_delay):
            states, already = factory.start(self.files, "/repo", "1", [], self.spawn)
            self.assertEqual(already, 0)
            self.assertEqual(states[0].pid, 123)
            self.assertEqual(states[0].actor, "")
            self.publish(_delay)

        with patch.object(adapter, "caffeinate_argv", return_value=[]):
            states, already = factory.start(self.files, "/repo", "1", [], self.spawn, publish_after_second_start)
        self.assertEqual(already, 1)
        self.assertEqual(states[0].pid, self.state.pid)
        self.spawn.start.assert_called_once()

    def test_existing_foreground_loop_is_reused_without_a_factory_pid(self):
        self.files.write(self.state)
        states, already = factory.start(self.files, "/repo", "1", [], self.spawn)
        self.assertEqual(already, 0)
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
        with self.assertRaisesRegex(RuntimeError, r"loop exited 2; see .*factory-123\.log"):
            factory.start(self.files, "/repo", "1", [], self.spawn)

    def test_launcher_records_every_observed_exit_code(self):
        for code, reason in ((0, "clean"), (2, "crash"), (-9, "signal"), (-15, "signal")):
            with self.subTest(code=code):
                (self.files.runs() / "factory.log").unlink(missing_ok=True)
                self.child.poll.return_value = code
                self.files.remove(123)
                with self.assertRaises(RuntimeError):
                    factory.start(self.files, "/repo", "1", [], self.spawn)
                records = [json.loads(line) for line in (self.files.runs() / "factory.log").read_text().splitlines()]
                self.assertEqual(len(records), 1)
                self.assertEqual((records[0]["pid"], records[0]["lane"], records[0]["t"]), (123, 1, 42))
                self.assertEqual(records[0]["reason"], reason)
                self.assertIn(str(code), records[0]["detail"])

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
                  patch.object(cli.loop, "profile_of", return_value=RepoProfile()),
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
        args = argparse.Namespace(op="start", repo=None, lanes=None)
        who = Identity(actor="owner", home=self.temp.name)
        for already in (False, True):
            output = io.StringIO()
            with (patch.object(cli.repos, "repo_root", return_value="/repo"),
                  patch.object(cli.loop, "files_of", return_value=self.files),
                  patch.object(factory, "version", return_value="1"),
                  patch.object(cli.loop, "profile_of", return_value=RepoProfile()),
                  patch.object(factory, "start", return_value=([self.state], 0 if already else 1)) as start,
                  patch.object(cli.dash, "run", return_value=0) as dash,
                  redirect_stdout(output)):
                self.assertEqual(cli.run(args, Env({}), self.spawn, who, Path("/code")), 0)
            argv = start.call_args.args[3]
            self.assertEqual(argv[1:], ["/code/tl.py", "loop", "--repo", "/repo", "--wait-drained"])
            dash.assert_called_once_with("ensure", Env({}), self.spawn)
            self.assertIn("already running" if already else "started", output.getvalue())
        self.spawn.start.assert_not_called()

    def test_factory_parser_defaults_and_options(self):
        parser = argparse.ArgumentParser()
        cli.add_parser(parser.add_subparsers(dest="cmd"))
        self.assertIsNone(parser.parse_args(["factory", "start"]).repo)
        logs = parser.parse_args(["factory", "logs"])
        self.assertEqual((logs.n, logs.follow), (50, False))
        logs = parser.parse_args(["factory", "logs", "-n", "3", "-f", "--repo", "/repo"])
        self.assertEqual((logs.n, logs.follow, logs.repo), (3, True, "/repo"))
        self.assertTrue(parser.parse_args(["factory", "stop", "--now"]).now)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["factory", "supervise"])


class Lanes(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.files = LoopFiles(ConfigDir(Path(temp.name)), "repo-key", lambda pid: True, lambda: 42)
        self.spawn = Mock(spec=Spawner)
        self.children = [Mock(pid=pid) for pid in (123, 124, 125)]
        for child in self.children:
            child.poll.return_value = None
        self.spawn.start.side_effect = self.children
        self.who = Identity(actor="owner", home=temp.name)

    def state(self, pid, **fields):
        return LoopState(pid=pid, started=40, t=41, repo="/repo", version="1", actor="loop", code_dir="/code", **fields)

    def publish(self, _delay):
        for child in self.children:
            if self.files.read(child.pid):
                self.files.write(self.state(child.pid))

    def start(self, lanes=3):
        with patch.object(adapter, "caffeinate_argv", return_value=[]):
            return factory.start(self.files, "/repo", "1", [], self.spawn, self.publish, lanes=lanes)

    def invoke(self, op, *, count=3, profile_error=None, **options):
        args = argparse.Namespace(op=op, repo=None, lanes=None, lane=1, n=50, follow=False, now=False)
        for key, value in options.items():
            setattr(args, key, value)
        output, errors = io.StringIO(), io.StringIO()
        with (patch.object(cli.repos, "repo_root", return_value="/repo"),
              patch.object(cli.loop, "files_of", return_value=self.files),
              patch.object(cli.loop, "profile_of", return_value=RepoProfile(slots=SlotsConfig(count=count)),
                           side_effect=profile_error),
              patch.object(cli.dash, "run", return_value=0), patch.object(cli.dash, "url"),
              redirect_stdout(output), redirect_stderr(errors)):
            result = cli.run(args, Env({}), self.spawn, self.who, Path("/code"))
        return result, output.getvalue(), errors.getvalue()

    def test_three_lanes_have_distinct_logs_and_second_start_spawns_none(self):
        states, added = self.start()
        self.assertEqual((len(states), added), (3, 3))
        self.assertEqual(len({state.log for state in states}), 3)
        for state in states:
            self.assertEqual(factory.log_path(self.files, state), self.files.runs() / f"factory-{state.pid}.log")
        again, added = self.start()
        self.assertEqual((again, added), (states, 0))
        self.assertEqual(self.spawn.start.call_count, 3)
        self.assertEqual(factory.recorded_pid(self.files), 123)

    def test_two_live_lanes_are_topped_up_by_one(self):
        self.files.write(self.state(121))
        self.files.write(self.state(122))
        states, added = self.start()
        self.assertEqual((len(states), added), (3, 1))
        self.spawn.start.assert_called_once()
        self.assertEqual(factory.recorded_pid(self.files), 121)

    def test_smaller_target_never_spawns_or_stops_existing_lanes(self):
        for pid in (121, 122, 123):
            self.files.write(self.state(pid))
        states, added = self.start(lanes=2)
        self.assertEqual((len(states), added), (3, 0))
        self.spawn.start.assert_not_called()
        self.spawn.stop_pid.assert_not_called()

    def test_numbered_live_logs_reserve_their_lane_numbers(self):
        for lane, pid in ((1, 121), (2, 122)):
            self.files.write(self.state(pid, log=str(self.files.runs() / f"factory-lane-{lane}.log")))
        self.start()
        self.assertEqual(Path(self.spawn.start.call_args.kwargs["out"].name).name, "factory-lane-3.log")

    def test_reuses_vacant_lane_number_without_renumbering_live_lane(self):
        self.start()
        self.files.remove(124)
        self.spawn.start.side_effect = None
        child = Mock(pid=126)
        child.poll.return_value = None
        self.spawn.start.return_value = child

        def publish(_delay):
            self.files.write(self.state(126))

        with patch.object(adapter, "caffeinate_argv", return_value=[]):
            factory.start(self.files, "/repo", "1", [], self.spawn, publish, lanes=3)
        self.assertEqual(Path(self.spawn.start.call_args.kwargs["out"].name).name, "factory-lane-2.log")
        self.assertEqual(factory.lane_states(self.files, self.files.live())[3].pid, 125)

    def test_waits_for_every_child_and_preserves_child_log(self):
        published = []

        def publish(_delay):
            pid = 123 + len(published)
            self.files.write(self.state(pid, log=f"/child-{pid}.log"))
            published.append(pid)

        with patch.object(adapter, "caffeinate_argv", return_value=[]):
            states, _ = factory.start(self.files, "/repo", "1", [], self.spawn, publish, lanes=3)
        self.assertEqual(published, [123, 124, 125])
        self.assertEqual([state.log for state in states], [f"/child-{pid}.log" for pid in published])
        self.assertEqual(factory.log_path(self.files, states[0]), Path("/child-123.log"))

    def test_timeout_names_the_lane_that_did_not_publish(self):
        def publish(_delay):
            self.files.write(self.state(123))

        with self.assertRaisesRegex(RuntimeError, r"loop pid 124 has not published state; see .*factory-124\.log"):
            factory.start(self.files, "/repo", "1", [], self.spawn, publish, lanes=2)

    def test_failure_names_failed_lane_log_and_leaves_existing_lane(self):
        existing = self.state(120)
        self.files.write(existing)
        self.children[1].poll.return_value = 2
        with self.assertRaisesRegex(RuntimeError, r"loop exited 2; see .*factory-124\.log"):
            self.start()
        self.assertEqual(self.files.read(120), existing)

    def test_caffeinate_only_once_for_first_new_lane(self):
        self.spawn.start.side_effect = [*self.children, Mock()]
        with patch.object(adapter, "caffeinate_argv", return_value=["caffeinate", "-w", "123"]) as awake:
            factory.start(self.files, "/repo", "1", [], self.spawn, self.publish, lanes=3)
        awake.assert_called_once_with(123)
        self.assertEqual(self.spawn.start.call_count, 4)

    def test_default_lane_count_and_start_messages(self):
        for count, wanted in ((3, 3), (0, 1)):
            with self.subTest(count=count), patch.object(factory, "start", return_value=([], wanted)) as start:
                result, output, _ = self.invoke("start", count=count)
                self.assertEqual(result, 0)
                self.assertEqual(start.call_args.kwargs["lanes"], wanted)
                self.assertIn(f"started {wanted} more lane(s)", output)
        with patch.object(factory, "start", return_value=([self.state(123), self.state(124)], 0)):
            self.assertIn("already running (2 lanes)", self.invoke("start")[1])

    def test_profile_failure_refuses_start(self):
        for error in (RuntimeError("profile unreadable"), SystemExit(78)):
            with self.subTest(error=error), patch.object(factory, "start") as start:
                result, _, errors = self.invoke("start", profile_error=error)
                self.assertEqual(result, 1)
                self.assertIn("tl factory:", errors)
                start.assert_not_called()

    def test_explicit_lanes_override_the_profile_default(self):
        with patch.object(factory, "start", return_value=([], 2)) as start:
            result, _, _ = self.invoke("start", count=3, lanes=2)
        self.assertEqual(result, 0)
        self.assertEqual(start.call_args.kwargs["lanes"], 2)

    def test_status_and_stop_name_every_lane(self):
        for pid in (123, 124, 125):
            self.files.write(self.state(pid, bead=f"tl-{pid}", log=f"/loop-{pid}.log"))
        result, output, _ = self.invoke("status")
        self.assertEqual(result, 0)
        self.assertIn("LANES running=3 wanted=3", output)
        for pid in (123, 124, 125):
            self.assertIn(f"PID {pid}\nVERSION 1\nLOG /loop-{pid}.log\nBEAD tl-{pid}", output)
        result, output, _ = self.invoke("stop")
        self.assertEqual(result, 0)
        for pid in (123, 124, 125):
            self.assertIn(f"STOP after the current bead: loop pid {pid}", output)
            self.assertEqual(self.files.stop_for(pid, 40), "after")

    def test_status_shows_last_exit_for_each_lane_even_when_none_are_running(self):
        self.start()
        for pid, reason in ((123, "crash"), (124, "signal"), (123, "low_disk")):
            self.files.write_exit({"pid": pid, "started": 40, "t": 42, "reason": reason})
        for pid in (123, 124, 125):
            self.files.remove(pid)
        result, output, _ = self.invoke("status")
        self.assertEqual(result, 1)
        self.assertIn("LANES running=0 wanted=3", output)
        self.assertIn("LANE 1 LAST EXIT pid=123 time=42 reason=low_disk", output)
        self.assertIn("LANE 2 LAST EXIT pid=124 time=42 reason=signal", output)
        self.assertNotIn("reason=crash", output)

    def test_stop_without_live_lanes_reports_not_running(self):
        result, output, errors = self.invoke("stop")
        self.assertEqual((result, output, errors), (1, "not running\n", ""))
        self.spawn.start.assert_not_called()
        self.spawn.stop_pid.assert_not_called()

    def test_logs_select_lane_two_and_refuse_missing_lane(self):
        self.start()
        with patch.object(factory, "lines", return_value=iter(["lane two\n"])) as lines:
            result, output, _ = self.invoke("logs", lane=2)
        self.assertEqual((result, output), (0, "lane two\n"))
        self.assertEqual(lines.call_args.args[0], self.files.runs() / "factory-124.log")
        result, _, errors = self.invoke("logs", lane=4)
        self.assertEqual(result, 1)
        self.assertIn("no live lane 4", errors)

    def test_parser_accepts_positive_lane_counts_only(self):
        parser = argparse.ArgumentParser()
        cli.add_parser(parser.add_subparsers(dest="cmd"))
        self.assertIsNone(parser.parse_args(["factory", "start"]).lanes)
        self.assertEqual(parser.parse_args(["factory", "start", "--lanes", "3"]).lanes, 3)
        self.assertEqual(parser.parse_args(["factory", "logs", "--lane", "2"]).lane, 2)
        self.assertEqual(parser.parse_args(["factory", "logs"]).lane, 1)
        for op, flag in (("start", "--lanes"), ("logs", "--lane")):
            for value in ("0", "-1", "abc"):
                with self.subTest(op=op, value=value), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    parser.parse_args(["factory", op, flag, value])
