"""Executor repository names preserve safe origin and folder names."""

from unittest import mock

import pytest
from tlkernel import check_files

from tlgate.executor_names import executor_repo


@pytest.mark.parametrize("name", ["owner/name", "Repo_1.x-y", "a/b/c"])
def test_safe_names_are_preserved(workdir, name):
    git = mock.Mock()
    git.common_dir.return_value = str(workdir / ".git")
    with mock.patch("tlgate.executor_names.reponame.repo_name", return_value=name) as naming:
        assert executor_repo(git, str(workdir / "slot")) == name
    naming.assert_called_once_with(str(workdir))


@pytest.mark.parametrize("name", ["", ".", "..", "../repo", "owner/..", "/repo", "repo/", "a//b", "-repo", "a b", "é", "a\\b"])
def test_unsafe_names_use_hashed_key(workdir, name):
    git = mock.Mock()
    git.common_dir.return_value = str(workdir / ".git")
    with mock.patch("tlgate.executor_names.reponame.repo_name", return_value=name):
        assert executor_repo(git, str(workdir)) == str(check_files.repo_key(git, str(workdir)))


def test_unknown_common_dir_uses_worktree_folder(workdir):
    git = mock.Mock()
    git.common_dir.return_value = ""
    assert executor_repo(git, str(workdir / "repo")) == "repo"


def test_origin_name_is_read_from_common_repository(workdir):
    dot = workdir / "repo" / ".git"
    dot.mkdir(parents=True)
    (dot / "config").write_text('[remote "origin"]\nurl = git@example.com:owner/name.git\n')
    git = mock.Mock()
    git.common_dir.return_value = str(dot)
    assert executor_repo(git, str(workdir / "slot")) == "owner/name"
