"""Real layer, the profile's Git adapter: the file is read from the commit (`cat-file blob` through
`Repo.tree(rev).read`), never from the working tree; a commit without it is absent and an unknown name no commit. Set-up
runs through `git_porcelain.testing`'s runner under tmp_path."""

import json
from pathlib import Path

import pytest
from git_porcelain.history import Identity
from git_porcelain.testing import apply_hermetic_env, git

from taskloop.git_views import GitProfileFiles
from taskloop.profile import PROFILE_PATH, NoCommit, NotAFile, Refused, Resolved, Unavailable, read_profile, resolve


def test_the_profile_is_read_at_the_commit_not_from_the_working_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    apply_hermetic_env(monkeypatch, identity=Identity("Person", "person@example.invalid"), config={})
    main = tmp_path.resolve() / "repo"
    main.mkdir()
    git(main, "init", "-q", "-b", "main")
    (main / "README").write_text("one\n")
    git(main, "add", "README")
    git(main, "commit", "-q", "-m", "base")
    committed = {"checks": [{"name": "test", "argv": ["just", "test"], "timeout": 60}], "required": ["test"]}
    (main / PROFILE_PATH).write_text(json.dumps(committed))
    git(main, "add", PROFILE_PATH)
    git(main, "commit", "-q", "-m", "profile")
    (main / PROFILE_PATH).write_text(json.dumps({"checks": [], "target": "edited"}))
    files = GitProfileFiles(main)
    assert files.blob("HEAD", PROFILE_PATH) == json.dumps(committed).encode()
    assert files.blob("HEAD~1", PROFILE_PATH) is None
    assert files.blob("no-such-branch", PROFILE_PATH) == NoCommit()
    found = resolve(files, "HEAD", "main")
    assert isinstance(found, Resolved)
    assert (found.checks[0].argv, found.required, found.target) == (("just", "test"), ("test",), "main")


def started(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    apply_hermetic_env(monkeypatch, identity=Identity("Person", "person@example.invalid"), config={})
    main = tmp_path.resolve() / "repo"
    main.mkdir()
    git(main, "init", "-q", "-b", "main")
    return main


def test_a_symlink_or_submodule_entry_is_not_a_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    main = started(tmp_path, monkeypatch)
    (main / "target.json").write_text("{}")
    (main / PROFILE_PATH).symlink_to("target.json")
    git(main, "add", "target.json", PROFILE_PATH)
    git(main, "commit", "-q", "-m", "link")
    git(main, "rm", "-q", "--cached", PROFILE_PATH)
    git(main, "update-index", "--add", "--cacheinfo", f"160000,{'1' * 40},{PROFILE_PATH}")
    git(main, "commit", "-q", "-m", "submodule")
    files = GitProfileFiles(main)
    assert files.blob("HEAD~1", PROFILE_PATH) == NotAFile("120000")
    assert files.blob("HEAD", PROFILE_PATH) == NotAFile("160000")
    assert read_profile(files, "HEAD") == Refused(
        "not_a_file", detail=".task-loop.json at HEAD is not a regular file (mode 160000)")


def test_a_path_that_is_no_repository_is_unavailable_not_no_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    apply_hermetic_env(monkeypatch, identity=Identity("Person", "person@example.invalid"), config={})
    found = GitProfileFiles(tmp_path.resolve()).blob("HEAD", PROFILE_PATH)
    assert isinstance(found, Unavailable)
