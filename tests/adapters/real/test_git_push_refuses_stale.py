"""A push through the Git port never moves a ref backwards or deletes one (the 2026-11-05 main rewind). A plain push of a stale ref was
always refused by git; `+refspec` and `:ref` are the ways to rewrite origin, and the port refuses both. A non-fast-forward move is
push_lease with the sha the caller last saw, and only then."""

import os
import subprocess
from pathlib import Path

import pytest

from taskloop.adapters.git import RealGit
from taskloop.contracts.env import snapshot
from taskloop.contracts.slots import SlotGitError


def sh(*a: str, cwd: Path) -> str:
    return subprocess.run(["git", *a], cwd=str(cwd), check=True, capture_output=True, text=True).stdout.strip()


def commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name)
    sh("add", name, cwd=repo)
    sh("-c", "user.email=a@b", "-c", "user.name=n", "commit", "-q", "-m", name, cwd=repo)
    return sh("rev-parse", "HEAD", cwd=repo)


@pytest.fixture
def world(tmp_path: Path):
    root = Path(os.path.realpath(tmp_path))
    origin, a, b = root / "o.git", root / "a", root / "b"
    sh("init", "-q", "--bare", "-b", "main", str(origin), cwd=root)
    sh("clone", "-q", str(origin), str(a), cwd=root)
    commit(a, "base")
    sh("push", "-q", "origin", "HEAD:main", cwd=a)
    sh("clone", "-q", str(origin), str(b), cwd=root)
    first = commit(a, "from-a")  # A moves main on; B stays stale
    sh("push", "-q", "origin", "HEAD:main", cwd=a)
    sh("push", "-q", "origin", "HEAD:refs/heads/side", cwd=a)
    commit(b, "from-b")  # B diverges
    return origin, b, first, RealGit(snapshot(), pinned=False)


def test_a_stale_diverged_plain_push_is_refused_and_origin_keeps_the_commit(world):
    origin, b, first, git = world
    with pytest.raises(SlotGitError):
        git.push(str(b), "origin", "HEAD:main")
    assert sh("rev-parse", "main", cwd=origin) == first


def test_a_plus_refspec_cannot_rewrite_origin(world):
    origin, b, first, git = world
    with pytest.raises(SlotGitError):
        git.push(str(b), "origin", "+HEAD:main")
    assert sh("rev-parse", "main", cwd=origin) == first


def test_a_push_never_deletes_a_ref(world):
    origin, b, first, git = world
    with pytest.raises(SlotGitError):
        git.push(str(b), "origin", ":refs/heads/side")
    assert sh("rev-parse", "side", cwd=origin) == first


def test_a_fast_forward_push_still_goes_through(world):
    origin, b, _, git = world
    sh("-c", "user.email=a@b", "-c", "user.name=n", "pull", "-q", "--rebase", "origin", "main", cwd=b)
    git.push(str(b), "origin", "HEAD:main")
    assert sh("rev-parse", "main", cwd=origin) == sh("rev-parse", "HEAD", cwd=b)


def test_a_lease_moves_a_ref_only_from_the_sha_the_caller_saw(world):
    origin, b, first, git = world
    outcome = git.push_lease(str(b), "origin", "HEAD:refs/heads/main", "0" * 40)
    assert not outcome.ok
    assert sh("rev-parse", "main", cwd=origin) == first
    outcome = git.push_lease(str(b), "origin", "HEAD:refs/heads/main", first)
    assert outcome.ok
    assert sh("rev-parse", "main", cwd=origin) == sh("rev-parse", "HEAD", cwd=b)


def test_a_lease_with_no_expected_sha_is_a_plain_push_that_cannot_rewrite(world):
    origin, b, _, git = world
    assert not git.push_lease(str(b), "origin", "HEAD:refs/heads/main", "").ok
    assert git.push_lease(str(b), "origin", "HEAD:refs/heads/wip", "").ok
    assert sh("rev-parse", "wip", cwd=origin) == sh("rev-parse", "HEAD", cwd=b)
