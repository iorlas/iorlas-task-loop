"""The queue refs on real git: Q(N) chains on Q(N-1) with merge-tree's tree, a conflict is a result, and a dropped ref is gone."""
import subprocess
from pathlib import Path
from unittest import mock

import pytest
import support.paths  # noqa: F401

# isort: split
from taskloop.adapters.spawner import RealSpawner
from taskloop.app.land.cmds import Cmds
from taskloop.app.land.queue_refs import Conflict, Made, QueueRefs
from tlkernel.env import snapshot

ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def git(repo: Path, *argv: str) -> str:
    env = {**ENV, "PATH": "/usr/bin:/bin:/run/current-system/sw/bin"}
    done = subprocess.run(["git", *argv], cwd=repo, capture_output=True, text=True, check=True, env=env)
    return done.stdout.strip()


def commit(repo: Path, branch: str, base: str, name: str, lines: dict[int, str]) -> str:
    git(repo, "checkout", "-q", "-b", branch, base)
    text = (repo / name).read_text().splitlines() if (repo / name).exists() else [f"l{i}" for i in range(20)]
    for n, value in lines.items():
        text[n] = value
    (repo / name).write_text("\n".join(text) + "\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", branch)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path):
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "f.txt").write_text("\n".join(f"l{i}" for i in range(20)) + "\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "seed")
    return tmp_path


def refs(repo: Path) -> QueueRefs:
    return QueueRefs(Cmds(RealSpawner(snapshot()), mock.Mock(), str(repo)), str(repo))


def test_q_of_the_second_pr_has_the_first_in_it_and_the_first_q_as_parent(repo):
    main = git(repo, "rev-parse", "main")
    a = commit(repo, "a", main, "f.txt", {2: "A"})
    b = commit(repo, "b", main, "f.txt", {12: "B"})
    q = refs(repo)
    one, two = q.make(1, main, a), None
    assert isinstance(one, Made)
    two = q.make(2, one.q, b)
    assert isinstance(two, Made)
    assert git(repo, "rev-parse", f"{two.q}^") == one.q and git(repo, "rev-parse", f"{one.q}^") == main
    body = git(repo, "show", f"{two.q}:f.txt").splitlines()
    assert body[2] == "A" and body[12] == "B"
    assert git(repo, "rev-parse", two.ref) == two.q and two.ref.startswith("refs/tl/queue/2-")


def test_a_conflict_is_a_result_and_leaves_no_ref(repo):
    main = git(repo, "rev-parse", "main")
    a = commit(repo, "a", main, "f.txt", {2: "A"})
    c = commit(repo, "c", main, "f.txt", {2: "C"})
    q = refs(repo)
    one = q.make(1, main, a)
    assert isinstance(one, Made)
    got = q.make(2, one.q, c)
    assert isinstance(got, Conflict) and "CONFLICT" in got.why and "f.txt" in got.why
    assert git(repo, "for-each-ref", "refs/tl/queue/").count("\n") == 0 and "2-" not in git(repo, "for-each-ref", "refs/tl/queue/")


def test_a_dropped_ref_is_gone(repo):
    main = git(repo, "rev-parse", "main")
    a = commit(repo, "a", main, "f.txt", {2: "A"})
    q = refs(repo)
    one = q.make(1, main, a)
    assert isinstance(one, Made) and git(repo, "for-each-ref", "refs/tl/queue/")
    q.drop(one.ref)
    assert git(repo, "for-each-ref", "refs/tl/queue/") == ""
