"""Every recoverable lane termination leaves evidence even when disk writes fail."""
import errno
import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import Mock, patch

import support.paths  # noqa: F401

from taskloop.app.loop import exits
from taskloop.app.loop.files import EXIT_REASONS, LoopFiles
from taskloop.app.loop.loop import Loop, LoopArgs
from taskloop.contracts.config import RepoProfile
from taskloop.contracts.loop import LoopState
from taskloop.contracts.paths import ConfigDir


class LaneExits(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.files = LoopFiles(ConfigDir(Path(temp.name)), "repo", lambda _: True, lambda: 42)
        self.directory = self.files.runs()
        (self.directory / "factory-lane-2.log").symlink_to("factory-123.log")
        self.env = Mock(pid=123, repo="/repo", version="1", code_dir="/code")
        self.env.cfgdir = self.files.cfg
        self.env.profile.return_value = RepoProfile()
        self.env.now.return_value = 42
        self.env.actor.return_value = "loop"

    def loop(self):
        return Loop(self.env, self.files, Mock(), LoopArgs())

    def records(self):
        return exits.rows(self.directory / "factory.log")

    def test_exit_reason_vocabulary(self):
        self.assertEqual(EXIT_REASONS, (
            "drained", "until", "max_beads", "stop_request", "signal", "storm", "crash", "profile_ahead",
            "low_disk", "system_exit", "lost",
        ))

    def test_clean_and_signal_exit_once_with_lane_pid_time_and_reason(self):
        for signalled in (False, True):
            with self.subTest(signalled=signalled):
                loop = self.loop()
                if signalled:
                    loop.sigterm.set()
                with patch.object(loop, "run", side_effect=lambda loop=loop: loop.left("drained") or 0):
                    self.assertEqual(loop.main(), 0)
                loop.write_exit()  # an atexit callback cannot duplicate the line
                rec = self.records()[-1]
                self.assertEqual((rec["pid"], rec["t"], rec["lane"]), (123, 42, 2))
                self.assertEqual(rec["reason"], "signal" if signalled else "drained")
        self.assertEqual(len(self.records()), 2)

    def test_crash_disk_full_and_interpreter_exit_preserve_original_exception(self):
        cases = ((RuntimeError("boom"), "crash"), (OSError(errno.ENOSPC, "disk full"), "crash"),
                 (SystemExit(9), "system_exit"), (KeyboardInterrupt(), "signal"))
        for error, reason in cases:
            with self.subTest(error=error):
                loop = self.loop()
                with patch.object(loop, "run", side_effect=error), self.assertRaises(type(error)) as raised:
                    loop.main()
                self.assertIs(raised.exception, error)
                self.assertEqual(self.records()[-1]["reason"], reason)
        self.assertEqual(len(self.records()), len(cases))

    def test_startup_failure_is_inside_exit_boundary(self):
        loop = self.loop()
        with patch.object(loop, "open_log", side_effect=OSError("startup disk failure")), self.assertRaises(OSError):
            loop.main()
        self.assertIn("startup disk failure", str(self.records()[0]["detail"]))

    def test_low_disk_wait_stops_on_signal_and_logs_exit_without_claiming_work(self):
        loop = self.loop()
        self.env.free_bytes.return_value = 0

        def stop_wait(seconds):
            loop.sigterm.set()  # release the real nap even though this test's clock is fixed
            self.assertGreater(seconds, 0)
            self.assertEqual(self.records(), [])
            state = self.files.read(self.env.pid)
            assert state is not None and state.wait is not None
            self.assertEqual(state.wait.reason, "low_disk")
            self.assertFalse(loop.exit)

        self.env.sleep.side_effect = stop_wait
        self.assertEqual(loop.main(), 0)
        self.env.sleep.assert_called_once()
        loop.write_exit()  # the normal boundary and a later callback still write only once
        self.assertEqual(len(self.records()), 1)
        self.assertEqual((self.records()[0]["reason"], self.records()[0]["lane"]), ("signal", 2))
        self.env.fetch.assert_not_called()
        self.env.claim.assert_not_called()

    def test_atexit_callback_records_exit_and_is_unregistered(self):
        loop = self.loop()

        def shutdown():
            callback = register.call_args.args[0]
            callback()
            return 0

        with (patch("taskloop.app.loop.loop.atexit.register") as register,
              patch("taskloop.app.loop.loop.atexit.unregister") as unregister,
              patch.object(loop, "run", side_effect=shutdown)):
            loop.main()
        unregister.assert_called_once_with(loop.write_exit)
        self.assertEqual(len(self.records()), 1)

    def test_failed_writes_fall_back_to_stderr_and_do_not_mask_crash(self):
        loop = self.loop()
        error = RuntimeError("original crash")
        output = io.StringIO()
        with (patch.object(loop, "run", side_effect=error),
              patch.object(Path, "open", side_effect=OSError(errno.ENOSPC, "disk full")),
              patch.object(loop, "open_log"), patch.object(loop, "publish"),
              patch.object(self.files, "lock"), patch.object(self.files, "clean_command"),
              redirect_stderr(output), self.assertRaises(RuntimeError) as raised):
            loop.main()
        self.assertIs(raised.exception, error)
        self.assertIn('"pid": 123', output.getvalue())
        self.assertIn('"reason": "crash"', output.getvalue())
        self.assertIn("original crash", output.getvalue())

    def test_untrappable_death_is_recorded_on_reconciliation_once(self):
        state = LoopState(pid=123, started=40, t=41, repo="/repo", version="1", code_dir="/code", actor="loop")
        self.files.write(state)
        self.files.pid_alive = lambda _: False
        self.assertEqual(self.files.live(), [])
        self.assertEqual(self.files.live(), [])
        self.assertEqual(len(self.records()), 1)
        self.assertEqual(self.records()[0]["reason"], "lost")
        self.assertIn("cause unknown", str(self.records()[0]["detail"]))

    def test_reconciliation_preserves_recorded_reason(self):
        loop = self.loop()
        self.files.write(loop.st)
        loop.left("low_disk")
        loop.write_exit()
        self.files.pid_alive = lambda _: False
        self.files.live()
        self.assertEqual(len(self.records()), 1)
        self.assertEqual(self.records()[0]["reason"], "low_disk")

    def test_last_exit_per_lane_skips_torn_and_legacy_lines(self):
        path = self.directory / "factory.log"
        path.write_text('legacy output\n{"pid":\n[]\n')
        for pid, reason in ((123, "crash"), (456, "signal"), (123, "low_disk")):
            self.files.write_exit({"pid": pid, "t": 42, "started": 40, "reason": reason})
        self.assertEqual([(r["lane"], r["reason"]) for r in exits.last_by_lane(self.directory)],
                         [(2, "low_disk"), (456, "signal")])
