"""A profile the running install cannot parse has a distinct process exit."""
import io
import sys
import unittest
from contextlib import redirect_stderr
from os import EX_CONFIG
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.app.wire.slots import cfg_source, load_cfg, load_profile, profile_source
from taskloop.contracts import config
from taskloop.contracts.ports import Git
from taskloop.contracts.slots import SlotGitError


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

    def test_absent_local_and_committed_profiles_use_defaults(self):
        git = mock.Mock(spec=Git)
        git.rev_parse.return_value = "abc123"
        git.show.side_effect = SlotGitError("file does not exist at that commit")
        git.ls_tree.return_value = []
        with mock.patch.object(Path, "read_text", side_effect=FileNotFoundError("absent")):
            self.assertEqual(profile_source("/repo", None, git), ({}, ""))
            self.assertEqual(cfg_source("/repo", git), (config.RepoProfile(), "origin/main", "abc123"))

    def test_malformed_committed_json_names_path_commit_and_error(self):
        git = mock.Mock(spec=Git)
        git.rev_parse.return_value = "abc123"
        for text in ("{broken", "", "   "):
            with self.subTest(text=text):
                git.show.return_value = text
                with self.assertRaises(config.ConfigError) as raised:
                    profile_source("/repo", "origin/main", git)
                self.assertIn("/repo/.task-loop.json at abc123 is unreadable:", str(raised.exception))
                self.assertIn("Expecting", str(raised.exception))

    def test_git_read_failure_is_not_an_absent_profile(self):
        git = mock.Mock(spec=Git)
        git.rev_parse.return_value = "abc123"
        git.show.side_effect = SlotGitError("cannot read object")
        for entries in ([object()], SlotGitError("cannot read tree")):
            with self.subTest(entries=entries):
                git.ls_tree.side_effect = entries if isinstance(entries, Exception) else None
                git.ls_tree.return_value = entries
                with self.assertRaises(config.ConfigError) as raised:
                    profile_source("/repo", "origin/main", git)
                self.assertIn("/repo/.task-loop.json at abc123 is unreadable: cannot read object", str(raised.exception))

    def test_unreadable_local_profile_fails_and_load_cfg_exits_config(self):
        git = mock.Mock(spec=Git)
        for error in (PermissionError("access denied"), ValueError("bad JSON"), UnicodeError("bad encoding")):
            with self.subTest(error=error), mock.patch.object(Path, "read_text", side_effect=error):
                with self.assertRaises(config.ConfigError) as raised:
                    profile_source("/repo", None, git)
                self.assertIn(f"/repo/.task-loop.json at working tree is unreadable: {error}", str(raised.exception))
                stderr = io.StringIO()
                with redirect_stderr(stderr), self.assertRaises(SystemExit) as exited:
                    load_cfg("/repo", git)
                self.assertEqual(exited.exception.code, EX_CONFIG)
                self.assertIn(str(raised.exception), stderr.getvalue())

    def test_base_hint_ignores_future_local_engine_keys(self):
        git = mock.Mock(spec=Git)
        git.rev_parse.return_value = "abc123"
        git.show.return_value = '{"engine": {"base": "origin/release"}}'
        local = '{"engine": {"base": "origin/release", "future_prepare": {}}}'
        with mock.patch.object(Path, "read_text", return_value=local):
            profile, base, commit = cfg_source("/repo", git)
        self.assertEqual((base, commit, profile.engine.base), ("origin/release", "abc123", "origin/release"))
        git.rev_parse.assert_called_once_with("/repo", "origin/release^{commit}")

    def test_malformed_local_json_is_not_a_default_profile(self):
        git = mock.Mock(spec=Git)
        with mock.patch.object(Path, "read_text", return_value="{broken"), self.assertRaises(config.ConfigError) as raised:
            profile_source("/repo", None, git)
        self.assertIn("/repo/.task-loop.json at working tree is unreadable: Expecting", str(raised.exception))

    def test_malformed_committed_profile_exits_config_with_original_cause(self):
        git = mock.Mock(spec=Git)
        git.rev_parse.return_value = "abc123"
        git.show.return_value = "{broken"
        stderr = io.StringIO()
        with mock.patch.object(Path, "read_text", return_value="{}"), redirect_stderr(stderr), self.assertRaises(SystemExit) as exited:
            cfg_source("/repo", git)
        self.assertEqual(exited.exception.code, EX_CONFIG)
        self.assertIsInstance(exited.exception.__cause__, config.ConfigError)
        self.assertIn("/repo/.task-loop.json at abc123 is unreadable:", stderr.getvalue())

    def test_unknown_committed_field_still_exits_config(self):
        git = mock.Mock(spec=Git)
        git.rev_parse.return_value = "abc123"
        git.show.return_value = '{"engine": {"future_prepare": {}}}'
        patched = mock.patch.object(Path, "read_text", return_value="{}")
        with patched, redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exited:
            cfg_source("/repo", git)
        self.assertEqual(exited.exception.code, EX_CONFIG)
