"""Real layer, the profile's Git adapter: the file is read from the commit (`cat-file blob` through
`Repo.tree(rev).read`), never from the working tree; a commit without it is absent and an unknown name no commit. Set-up
runs through `git_porcelain.testing`'s runner under tmp_path."""

import json
from pathlib import Path

import pytest
from git_porcelain.history import Identity
from git_porcelain.testing import apply_hermetic_env, git

from taskloop.composition import GitProfileFiles
from taskloop.profile import PROFILE_PATH, NoCommit, Resolved, resolve


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
