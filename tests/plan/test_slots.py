"""Managed slots through real SQLite and the owning semantic Git fake; nothing here creates a worktree for the person."""

import sqlite3
from contextlib import AbstractContextManager
from pathlib import Path

import pytest
from git_porcelain import GitUnavailable, WorktreeInfo
from git_porcelain.testing import FakeRemote, FakeRepo
from sqlite_store import Store, begin_immediate

from taskloop.composition import open_plan_attempts
from taskloop.plan_schema import SCHEMA
from taskloop.plan_types import AttemptKey
from taskloop.repo import RepoId
from taskloop.slots import Adopted, NotAdopted, SlotsUnavailable, SlotView, Unknown, adopt, observe, slot_names


def derived(repo: FakeRepo, root: Path, name: str) -> Path:
    return root.resolve() / repo.identity().key / name


def add(repo: FakeRepo, root: Path, *names: str) -> None:
    """What a person does before adoption: `git worktree add --detach <derived path>`."""
    for name in names:
        repo.add_worktree(derived(repo, root, name), "HEAD")


def adopted(con: sqlite3.Connection, repo: FakeRepo, root: Path, count: int) -> tuple[Adopted | NotAdopted, ...]:
    return adopt(lambda: con, begin_immediate, repo, root, count)


def rid(repo: FakeRepo) -> RepoId:
    return RepoId(repo.identity().key)


def unavailable(*, with_dirty: bool = False) -> tuple[WorktreeInfo, ...]:
    raise GitUnavailable("git exited 128")


def test_slot_names_are_s1_to_sn_and_need_one() -> None:
    assert slot_names(3) == ("s1", "s2", "s3")
    with pytest.raises(ValueError, match="at least 1"):
        slot_names(0)


def test_listed_clean_linked_worktree_is_adopted_once(factory: sqlite3.Connection, repo: FakeRepo, root: Path) -> None:
    add(repo, root, "s1", "s2")
    first = adopted(factory, repo, root, 2)
    assert first == (Adopted("s1", derived(repo, root, "s1")), Adopted("s2", derived(repo, root, "s2")))
    repo.worktree(derived(repo, root, "s1")).write_file("scratch", "x")  # an adopted row is never re-checked or re-adopted
    assert adopted(factory, repo, root, 2) == first
    assert factory.execute("SELECT count(*) FROM slot").fetchone() == (2,)


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("not_listed", "not_listed"),
        ("elsewhere", "not_listed"),
        ("main", "main"),
        ("dirty", "dirty"),
        ("missing", "git_unavailable"),
        ("listing", "git_unavailable"),
    ],
)
def test_unusable_worktree_is_refused_with_its_reason(
    factory: sqlite3.Connection, repo: FakeRepo, root: Path, monkeypatch: pytest.MonkeyPatch, reason: str, expected: Unknown
) -> None:
    path = derived(repo, root, "s1")
    if reason == "elsewhere":
        repo.add_worktree(root / "elsewhere" / "s1", "HEAD")
    elif reason == "main":
        monkeypatch.setattr(repo, "worktrees", lambda *, with_dirty=False: (WorktreeInfo(path, None, "main", True, None),))
    elif reason in ("dirty", "missing"):
        add(repo, root, "s1")
        if reason == "dirty":
            repo.worktree(path).write_file("scratch", "x")
        else:
            repo.drop_checkout(path)
    elif reason == "listing":
        monkeypatch.setattr(repo, "worktrees", unavailable)
    assert adopted(factory, repo, root, 1) == (NotAdopted("s1", expected),)
    assert factory.execute("SELECT count(*) FROM slot").fetchone() == (0,)


def test_adopt_refuses_without_a_current_store(factory: sqlite3.Connection, repo: FakeRepo, root: Path) -> None:
    add(repo, root, "s1")
    assert adopt(lambda: None, begin_immediate, repo, root, 1) == (NotAdopted("s1", "store_unavailable"),)
    factory.execute("PRAGMA user_version=1")
    assert adopted(factory, repo, root, 1) == (NotAdopted("s1", "store_unavailable"),)


def test_without_a_slot_row_a_clean_derived_worktree_is_no_slot(factory: sqlite3.Connection, repo: FakeRepo, root: Path) -> None:
    add(repo, root, "s1")  # after a DB discard: the worktree is there, its provenance is not
    assert observe(factory, repo, rid(repo)) == ()


def test_observe_reports_free_held_and_unknown_lowest_first(
    factory: sqlite3.Connection, repo: FakeRepo, root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    names = tuple(f"s{n}" for n in range(1, 11))
    add(repo, root, *names)
    assert all(isinstance(result, Adopted) for result in adopted(factory, repo, root, 10))
    factory.execute("INSERT INTO reservation (slot,repo_id,cwd,generation,attempt_id) VALUES ('s2',?,?,1,'a')", (rid(repo), "x"))
    repo.worktree(derived(repo, root, "s2")).write_file("scratch", "x")  # held wins over dirty
    repo.worktree(derived(repo, root, "s3")).write_file("scratch", "x")
    repo.drop_worktree(derived(repo, root, "s4"))
    repo.drop_checkout(derived(repo, root, "s5"))
    views = observe(factory, repo, rid(repo))
    assert [view.name for view in views] == list(names)
    assert views[0] == SlotView("s1", derived(repo, root, "s1"), "free")
    assert views[1] == SlotView("s2", derived(repo, root, "s2"), "held", attempt_id="a")
    assert [(v.state, v.reason) for v in views[2:5]] == [("unknown", "dirty"), ("unknown", "not_listed"), ("unknown", "git_unavailable")]
    monkeypatch.setattr(repo, "worktrees", unavailable)
    after = observe(factory, repo, rid(repo))
    assert after[1].state == "held" and {(v.state, v.reason) for v in after if v.name != "s2"} == {("unknown", "git_unavailable")}


def test_main_checkout_at_a_slot_path_is_never_free(
    factory: sqlite3.Connection, repo: FakeRepo, root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    add(repo, root, "s1")
    adopted(factory, repo, root, 1)
    path = derived(repo, root, "s1")
    monkeypatch.setattr(repo, "worktrees", lambda *, with_dirty=False: (WorktreeInfo(path, None, "main", True, None),))
    assert observe(factory, repo, rid(repo)) == (SlotView("s1", path, "unknown", "main"),)


def test_store_failure_never_shows_a_free_slot(factory: sqlite3.Connection, repo: FakeRepo, root: Path) -> None:
    add(repo, root, "s1")
    adopted(factory, repo, root, 1)
    factory.execute("DROP TABLE reservation")
    assert observe(factory, repo, rid(repo)) == (SlotView("s1", derived(repo, root, "s1"), "unknown", "store_unavailable"),)
    factory.execute("DROP TABLE slot")
    with pytest.raises(SlotsUnavailable):
        observe(factory, repo, rid(repo))


def test_two_repos_each_have_their_own_s1(factory: sqlite3.Connection, repo: FakeRepo, root: Path, tmp_path: Path) -> None:
    remote = FakeRemote("https://example.invalid/other.git")
    remote.advance("main", {"README": "two"})
    other = FakeRepo.clone(remote, tmp_path / "other")
    for each in (repo, other):
        add(each, root, "s1")
        assert adopted(factory, each, root, 1) == (Adopted("s1", derived(each, root, "s1")),)
    factory.execute("INSERT INTO reservation (slot,repo_id,cwd,generation,attempt_id) VALUES ('s1',?,?,1,'a')", (rid(repo), "x"))
    assert observe(factory, repo, rid(repo))[0].state == "held"
    assert observe(factory, other, rid(other))[0].state == "free"


def test_v1_factory_database_is_refused_loudly(tmp_path: Path) -> None:
    path = tmp_path / "factory.db"
    old = sqlite3.connect(path, isolation_level=None)
    old.execute("CREATE TABLE reservation (slot TEXT PRIMARY KEY)")
    old.execute("PRAGMA user_version=1")
    old.close()
    attempts = open_plan_attempts(path, tmp_path, lambda: ("/bin/codex", {}))
    collected = attempts.collect(AttemptKey("a", "t", 1))
    assert (collected.status, collected.reason) == ("unavailable", "collect")
    executed = attempts.execute(AttemptKey("a", "t", 1))
    assert (executed.status, executed.reason) == ("unavailable", "store")
    store = Store(SCHEMA)
    repo = FakeRepo.init(tmp_path / "repo")
    refused = adopt(lambda: store.shared_rw(path), store.begin_immediate, repo, tmp_path / "slots", 1)
    assert refused == (NotAdopted("s1", "store_unavailable"),)
    store.close_shared()


def test_readopting_under_another_root_is_reported_not_moved(
    factory: sqlite3.Connection, repo: FakeRepo, root: Path, tmp_path: Path
) -> None:
    add(repo, root, "s1")
    adopted(factory, repo, root, 1)
    elsewhere = tmp_path / "elsewhere"
    add(repo, elsewhere, "s1")
    assert adopted(factory, repo, elsewhere, 1) == (NotAdopted("s1", "other_root"),)
    assert factory.execute("SELECT cwd FROM slot").fetchall() == [(str(derived(repo, root, "s1")),)]


def test_a_root_inside_the_main_checkout_is_refused(factory: sqlite3.Connection, repo: FakeRepo) -> None:
    inside = repo.path / ".slots"
    add(repo, inside, "s1")
    assert adopted(factory, repo, inside, 1) == (NotAdopted("s1", "inside_checkout"),)
    assert factory.execute("SELECT count(*) FROM slot").fetchone() == (0,)


def test_nothing_pending_takes_no_write_lock(factory: sqlite3.Connection, repo: FakeRepo, root: Path) -> None:
    add(repo, root, "s1")
    adopted(factory, repo, root, 1)
    taken: list[int] = []

    def begin(con: sqlite3.Connection) -> AbstractContextManager[None]:
        taken.append(1)
        return begin_immediate(con)

    assert adopt(lambda: factory, begin, repo, root, 1) == (Adopted("s1", derived(repo, root, "s1")),)
    repo.worktree(derived(repo, root, "s1")).write_file("dirty", "x")
    assert adopt(lambda: factory, begin, repo, root, 2) == (Adopted("s1", derived(repo, root, "s1")), NotAdopted("s2", "not_listed"))
    assert taken == []

