"""The stdlib hook forwards the whole request and refuses an unavailable judge."""
import io
import subprocess
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.hook import prepush


class PushClient(unittest.TestCase):
    request = "refs/heads/a aaa refs/heads/a bbb\nrefs/heads/b ccc refs/heads/b ddd\n"

    def ask(self, result):
        top = subprocess.CompletedProcess([], 0, "/repo\n", "")
        with (mock.patch.object(prepush.subprocess, "run", side_effect=[top, result]) as run,
              redirect_stderr(io.StringIO())):
            rc = prepush.entry(["/bin/tl", "origin", "url"], self.request, {"TL_LAND": "1"})
        return rc, run

    def test_all_tips_are_forwarded_once_even_with_the_old_marker(self):
        rc, run = self.ask(subprocess.CompletedProcess([], 0, "", ""))
        self.assertEqual(rc, 0)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args.args[0], ["/bin/tl", "judge-push", "--repo", "/repo"])
        self.assertEqual(run.call_args.kwargs["input"], self.request)

    def test_every_nonzero_judge_result_refuses(self):
        for code in (1, 2, 127, -9):
            with self.subTest(code=code):
                self.assertNotEqual(self.ask(subprocess.CompletedProcess([], code, "", "unavailable"))[0], 0)

    def test_a_missing_erroring_or_timed_out_judge_refuses(self):
        for error in (FileNotFoundError("tl"), ValueError("bad argv"), subprocess.TimeoutExpired("tl", 1)):
            with self.subTest(error=error):
                self.assertNotEqual(self.ask(error)[0], 0)

    def test_missing_command_or_failed_repo_discovery_refuses(self):
        with redirect_stderr(io.StringIO()):
            self.assertNotEqual(prepush.entry([], self.request, {}), 0)
            for result in (subprocess.CompletedProcess([], 128, "/repo", "failed"),
                           subprocess.CompletedProcess([], 0, "", "")):
                with mock.patch.object(prepush.subprocess, "run", return_value=result) as run:
                    self.assertNotEqual(prepush.entry(["tl"], self.request, {}), 0)
                    self.assertEqual(run.call_count, 1)

    def test_a_failed_chained_pre_push_hook_refuses(self):
        with (mock.patch.object(prepush, "entry", return_value=0),
              mock.patch.object(prepush, "original_hooks_dir", side_effect=OSError("unreadable")),
              redirect_stderr(io.StringIO())):
            self.assertNotEqual(prepush.githook("pre-push", ["tl"], self.request, {"TL_LAND": "1"}), 0)
