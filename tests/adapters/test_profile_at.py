"""profile_at: the one reader of .task-loop.json, at a commit or in a working tree."""
import json
from unittest import mock

import pytest

from taskloop.adapters import profile_at as pa
from tlkernel.config import ConfigError
from tlkernel.gitfacts import TreeEntry
from tlkernel.gitport import Git
from tlkernel.slots import SlotGitError


def git_with(text: str | None) -> mock.Mock:
    git = mock.create_autospec(Git, instance=True)
    git.ls_tree.return_value = [] if text is None else [TreeEntry(mode="100644", kind="blob", oid="abc", path=pa.FILE)]
    if text is None:
        git.show.side_effect = SlotGitError("no such path")
    else:
        git.show.return_value = text
    return git


def test_a_commit_with_no_profile_has_none():
    assert pa.profile_at(git_with(None), "/r", "c1") is None


def test_a_committed_profile_is_typed():
    got = pa.profile_at(git_with(json.dumps({"engine": {"base": "origin/dev"}})), "/r", "c1")
    assert got is not None and got.engine.base == "origin/dev"


def test_a_key_the_profile_does_not_know_is_refused():
    with pytest.raises(ConfigError):
        pa.profile_at(git_with(json.dumps({"engine": {"nope": 1}})), "/r", "c1")


def test_a_profile_that_is_not_an_object_is_refused():
    with pytest.raises(ValueError):
        pa.raw_at(git_with("[1]"), "/r", "c1")


def test_a_working_tree_without_the_file_has_none(tmp_path):
    assert pa.raw_in(tmp_path) is None


def test_a_working_tree_file_is_read(tmp_path):
    (tmp_path / pa.FILE).write_text('{"engine": {}}')
    assert pa.raw_in(tmp_path) == {"engine": {}}


def test_a_git_read_failure_of_a_profile_that_exists_is_not_an_absent_profile():
    git = git_with("{}")
    git.show.side_effect = SlotGitError("cannot read object")
    with pytest.raises(SlotGitError):
        pa.raw_at(git, "/r", "c1")
