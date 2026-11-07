"""A profile the running install cannot parse has a distinct process exit."""
import io
import sys
from contextlib import redirect_stderr
from os import EX_CONFIG
from pathlib import Path
from unittest import mock

import pytest

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from tlslots.config import cfg_source, load_cfg, load_profile, profile_source
from tlkernel import config
from tlkernel.gitport import Git
from tlkernel.slots import SlotGitError


class ProfileConfig(Case):
    def test_unknown_field_and_wrong_type_preserve_diagnostic_and_exit_config(self):
        for data in ({"engine": {"future_prepare": {}}}, {"engine": []}):
            with self.subTest(data=data):
                with pytest.raises(config.ConfigError) as original:
                    config.load(data)
                stderr = io.StringIO()
                with redirect_stderr(stderr), pytest.raises(SystemExit) as exited:
                    load_profile(data)
                assert exited.value.code == EX_CONFIG
                assert stderr.getvalue() == f"task-loop: {original.value}\n"

    def test_understood_profile_still_loads(self):
        assert load_profile({}) == config.RepoProfile()

    def test_absent_local_and_committed_profiles_use_defaults(self):
        git = mock.Mock(spec=Git)
        git.rev_parse.return_value = "abc123"
        git.show.side_effect = SlotGitError("file does not exist at that commit")
        git.ls_tree.return_value = []
        with mock.patch.object(Path, "read_text", side_effect=FileNotFoundError("absent")):
            assert profile_source("/repo", None, git) == ({}, "")
            assert cfg_source("/repo", git) == (config.RepoProfile(), "origin/main", "abc123")

    def test_malformed_committed_json_names_path_commit_and_error(self):
        git = mock.Mock(spec=Git)
        git.rev_parse.return_value = "abc123"
        for text in ("{broken", "", "   "):
            with self.subTest(text=text):
                git.show.return_value = text
                with pytest.raises(config.ConfigError) as raised:
                    profile_source("/repo", "origin/main", git)
                assert "/repo/.task-loop.json at abc123 is unreadable:" in str(raised.value)
                assert "Expecting" in str(raised.value)

    def test_git_read_failure_is_not_an_absent_profile(self):
        git = mock.Mock(spec=Git)
        git.rev_parse.return_value = "abc123"
        git.show.side_effect = SlotGitError("cannot read object")
        for entries in ([object()], SlotGitError("cannot read tree")):
            with self.subTest(entries=entries):
                git.ls_tree.side_effect = entries if isinstance(entries, Exception) else None
                git.ls_tree.return_value = entries
                with pytest.raises(config.ConfigError) as raised:
                    profile_source("/repo", "origin/main", git)
                assert "/repo/.task-loop.json at abc123 is unreadable: cannot read object" in str(raised.value)

    def test_unreadable_local_profile_fails_and_load_cfg_exits_config(self):
        git = mock.Mock(spec=Git)
        for error in (PermissionError("access denied"), ValueError("bad JSON"), UnicodeError("bad encoding")):
            with self.subTest(error=error), mock.patch.object(Path, "read_text", side_effect=error):
                with pytest.raises(config.ConfigError) as raised:
                    profile_source("/repo", None, git)
                assert f"/repo/.task-loop.json at working tree is unreadable: {error}" in str(raised.value)
                stderr = io.StringIO()
                with redirect_stderr(stderr), pytest.raises(SystemExit) as exited:
                    load_cfg("/repo", git)
                assert exited.value.code == EX_CONFIG
                assert str(raised.value) in stderr.getvalue()

    def test_base_hint_ignores_future_local_engine_keys(self):
        git = mock.Mock(spec=Git)
        git.rev_parse.return_value = "abc123"
        git.show.return_value = '{"engine": {"base": "origin/release"}}'
        local = '{"engine": {"base": "origin/release", "future_prepare": {}}}'
        with mock.patch.object(Path, "read_text", return_value=local):
            profile, base, commit = cfg_source("/repo", git)
        assert (base, commit, profile.engine.base) == ("origin/release", "abc123", "origin/release")
        git.rev_parse.assert_called_once_with("/repo", "origin/release^{commit}")

    def test_malformed_local_json_is_not_a_default_profile(self):
        git = mock.Mock(spec=Git)
        with mock.patch.object(Path, "read_text", return_value="{broken"), pytest.raises(config.ConfigError) as raised:
            profile_source("/repo", None, git)
        assert "/repo/.task-loop.json at working tree is unreadable: Expecting" in str(raised.value)

    def test_malformed_committed_profile_exits_config_with_original_cause(self):
        git = mock.Mock(spec=Git)
        git.rev_parse.return_value = "abc123"
        git.show.return_value = "{broken"
        stderr = io.StringIO()
        with mock.patch.object(Path, "read_text", return_value="{}"), redirect_stderr(stderr), pytest.raises(SystemExit) as exited:
            cfg_source("/repo", git)
        assert exited.value.code == EX_CONFIG
        assert isinstance(exited.value.__cause__, config.ConfigError)
        assert "/repo/.task-loop.json at abc123 is unreadable:" in stderr.getvalue()

    def test_unknown_committed_field_still_exits_config(self):
        git = mock.Mock(spec=Git)
        git.rev_parse.return_value = "abc123"
        git.show.return_value = '{"engine": {"future_prepare": {}}}'
        patched = mock.patch.object(Path, "read_text", return_value="{}")
        with patched, redirect_stderr(io.StringIO()), pytest.raises(SystemExit) as exited:
            cfg_source("/repo", git)
        assert exited.value.code == EX_CONFIG
