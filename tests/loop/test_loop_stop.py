"""Loop tests, part 2: network, health, stop requests, self-update. Split from test_loop."""
import io
import os
import threading
from contextlib import redirect_stdout
from unittest import mock

import support.paths  # noqa: F401
from support import (
    looptest,
)
from support.spawn import real_spawner

from loop.test_loop import LoopBase
from taskloop.cli import loop_cmd
from taskloop.contracts.env import snapshot


class StopRequestsLogic(LoopBase):
    """`tl stop` writes one LoopCommand naming the live loops; a loop it does not name (started later) ignores it."""

    def setUp(self):
        super().setUp()
        self.repo_s = str(self.repo)
        self.old_pid = os.getppid()  # a live process that is no loop of this test
        self.files = looptest.files(self.repo_s)

    def old_loop(self):
        looptest.write_state(self.repo_s, pid=self.old_pid, started=self.clock.t)

    def stop(self, now=False):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(self.main(["stop", "--repo", self.repo_s] + (["--now"] if now else [])), 0)
        return self.files.command().get()

    def test_the_command_names_the_running_loops(self):
        self.old_loop()
        looptest.write_state(self.repo_s, pid=os.getpid(), started=self.clock.t)
        for now in (False, True):
            with self.subTest(now=now):
                cmd = self.stop(now)
                assert cmd is not None
                self.assertEqual({t.pid for t in cmd.targets}, {self.old_pid, os.getpid()})
                self.assertEqual(cmd.action, "stop_now" if now else "stop_after_current")
                self.assertEqual(cmd.t, self.clock.t)

    def test_a_stop_for_a_pid_and_start_is_ignored_by_a_loop_with_the_same_pid_and_another_start(self):
        self.old_loop()  # pid P, started clock.t
        self.stop(now=True)
        self.assertEqual(self.files.stop_for(self.old_pid, self.clock.t), "now")
        self.assertEqual(self.files.stop_for(self.old_pid, self.clock.t + 50), "")  # the pid recycled by a loop started later
        looptest.write_state(self.repo_s, pid=self.old_pid, started=self.clock.t + 50)  # that loop's state replaces the old one
        with self.files.lock():
            self.files.clean_command()
        self.assertFalse(looptest.command(self.repo_s).exists())  # and it does not keep the old loop's command alive

    def test_a_stop_applies_to_the_loops_it_names_only(self):
        self.old_loop()
        for now in (False, True):
            self.stop(now)
            self.assertEqual(self.files.stop_for(self.old_pid, self.clock.t), "now" if now else "after")
            self.assertEqual(self.files.stop_for(os.getpid(), self.clock.t), "")

    def test_cleanup_keeps_the_command_while_a_named_loop_lives_and_drops_it_after(self):
        self.old_loop()
        self.stop()
        with self.files.lock():
            self.files.clean_command()
            self.assertTrue(looptest.command(self.repo_s).exists())
            self.files.remove(self.old_pid)
            self.files.clean_command()
        self.assertFalse(looptest.command(self.repo_s).exists())

    def test_a_stop_waits_for_a_registration_in_progress_and_names_the_new_loop(self):
        self.old_loop()
        attempted, finished, errors = threading.Event(), threading.Event(), []

        def stop():
            attempted.set()
            try:
                loop_cmd.cmd_stop(mock.Mock(repo=self.repo_s, now=True), snapshot(), spawner=real_spawner())
            except Exception as e:
                errors.append(e)
            finally:
                finished.set()
        with redirect_stdout(io.StringIO()):
            with self.files.lock():
                thread = threading.Thread(target=stop)
                thread.start()
                self.assertTrue(attempted.wait(2))
                self.assertFalse(finished.wait(0.05))
                looptest.write_state(self.repo_s, pid=os.getpid(), started=self.clock.t)
            thread.join(2)
        self.assertEqual(errors, [])
        cmd = self.files.command().get()
        assert cmd is not None
        self.assertEqual({t.pid for t in cmd.targets}, {self.old_pid, os.getpid()})
