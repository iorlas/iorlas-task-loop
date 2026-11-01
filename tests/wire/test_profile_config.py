"""A profile the running install cannot parse has a distinct process exit."""
import io
import sys
import unittest
from contextlib import redirect_stderr
from os import EX_CONFIG
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.app.wire.slots import load_profile
from taskloop.contracts import config


class ProfileConfig(unittest.TestCase):
    def test_unknown_field_and_wrong_type_preserve_diagnostic_and_exit_config(self):
        for data in ({"engine": {"future_prepare": {}}}, {"engine": []}):
            with self.subTest(data=data):
                with self.assertRaises(config.ConfigError) as original:
                    config.load(data)
                stderr = io.StringIO()
                with redirect_stderr(stderr), self.assertRaises(SystemExit) as exited:
                    load_profile(data)
                self.assertEqual(exited.exception.code, EX_CONFIG)
                self.assertEqual(stderr.getvalue(), f"task-loop: {original.exception}\n")

    def test_understood_profile_still_loads(self):
        self.assertEqual(load_profile({}), config.RepoProfile())
