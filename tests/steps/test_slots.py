"""Managed slots through real SQLite and the owning semantic Git fake; nothing here creates a worktree for the person."""

import sqlite3
from contextlib import AbstractContextManager
from pathlib import Path

import pytest
from doubles import FakeSlotFiles, PinnedViews, linked_into
from git_porcelain import GitUnavailable, RepoIdentity, WorktreeInfo
from git_porcelain.testing import FakeRemote, FakeRepo
from sqlite_store import begin_immediate

from taskloop.attempt_reads import SlotUse, StoreUnavailable
from taskloop.attempt_store import AttemptStore
from taskloop.repo import RepoId
from taskloop.slots import Adopted, NotAdopted, SlotGit, SlotsUnavailable, SlotView, Unclean, adopt, folder_name, observe, slot_names


def derived(repo: FakeRepo, root: Path, name: str) -> Path:
    return root.resolve() / folder_name(repo.identity()) / name


def add(repo: FakeRepo, root: Path, *names: str) -> None:
    """What a person does before adoption: `git worktree add --detach <derived path>`."""
    for name in names:
        repo.add_worktree(derived(repo, root, name), "HEAD")


def adopted(con: sqlite3.Connection, repo: FakeRepo, root: Path, count: int) -> tuple[Adopted | NotAdopted, ...]:
    return adopt(lambda: con, begin_immediate, repo, viewed(repo), root, count)


def viewed(repo: FakeRepo) -> SlotGit:
    """The slot views the body opens on the fake: the person's checkout unpinned, a slot only pinned to its pointer's G."""
    return SlotGit(PinnedViews(repo), FakeSlotFiles(repo))


def rid(repo: FakeRepo) -> RepoId:
    return RepoId(repo.identity().key)


def unavailable(*, with_dirty: bool = False) -> tuple[WorktreeInfo, ...]:
    raise GitUnavailable("git exited 128")


def unlocked(_slot_path: str) -> bool:
    """The free rule's lock probe: no other holder."""
    return True


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
        ("unborn", "unborn"),
        ("attached", "attached"),
        ("dirty", "dirty"),
        ("missing", "git_unavailable"),
        ("listing", "git_unavailable"),
    ],
)
def test_unusable_worktree_is_refused_with_its_reason(
    factory: sqlite3.Connection, repo: FakeRepo, root: Path, monkeypatch: pytest.MonkeyPatch, reason: str, expected: Unclean
) -> None:
    path = derived(repo, root, "s1")
    if reason == "elsewhere":
        repo.add_worktree(root / "elsewhere" / "s1", "HEAD")
    elif reason == "main":
        monkeypatch.setattr(repo, "worktrees", lambda *, with_dirty=False: (WorktreeInfo(path, None, "main", True, None),))
    elif reason == "unborn":  # a linked worktree on an unborn branch: the fake makes linked worktrees only at a commit
        monkeypatch.setattr(repo, "worktrees", lambda *, with_dirty=False: (WorktreeInfo(path, None, "orphan", False, None),))
    elif reason == "attached":
        add(repo, root, "s1")
        repo.worktree(path).checkout_new("task/tl-1")
    elif reason in ("dirty", "missing"):
        add(repo, root, "s1")
        if reason == "dirty":
            repo.worktree(path).write_file("scratch", "x")
        else:
            repo.drop_checkout(path)
    elif reason == "listing":
        monkeypatch.setattr(repo, "worktrees", unavailable)
    assert adopted(factory, repo, root, 1) == (NotAdopted("s1", expected, path),)  # where to add the worktree
    assert factory.execute("SELECT count(*) FROM slot").fetchone() == (0,)


def test_adopt_refuses_without_a_current_store(factory: sqlite3.Connection, repo: FakeRepo, root: Path) -> None:
    add(repo, root, "s1")
    path = derived(repo, root, "s1")
    assert adopt(lambda: None, begin_immediate, repo, viewed(repo), root, 1) == (NotAdopted("s1", "store_unavailable", path),)
    factory.execute("PRAGMA user_version=1")
    assert adopted(factory, repo, root, 1) == (NotAdopted("s1", "store_unavailable", path),)


def test_without_a_slot_row_a_clean_derived_worktree_is_no_slot(factory: sqlite3.Connection, repo: FakeRepo, root: Path) -> None:
    add(repo, root, "s1")  # after a DB discard: the worktree is there, its provenance is not
    assert observe(factory, repo, viewed(repo), rid(repo), unlocked) == ()


def test_observe_reports_free_held_and_unknown_lowest_first(
    factory: sqlite3.Connection, repo: FakeRepo, root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    names = tuple(f"s{n}" for n in range(1, 11))
    add(repo, root, *names)
    assert all(isinstance(result, Adopted) for result in adopted(factory, repo, root, 10))
    factory.execute("INSERT INTO reservation (slot,repo_id,generation,attempt_id) VALUES ('s2',?,1,'a')", (rid(repo),))
    repo.worktree(derived(repo, root, "s2")).write_file("scratch", "x")  # held wins over dirty
    repo.worktree(derived(repo, root, "s3")).write_file("scratch", "x")
    repo.drop_worktree(derived(repo, root, "s4"))
    repo.drop_checkout(derived(repo, root, "s5"))
    views = observe(factory, repo, viewed(repo), rid(repo), unlocked)
    assert [view.name for view in views] == list(names)
    assert views[0] == SlotView("s1", derived(repo, root, "s1"), "free")
    assert views[1] == SlotView("s2", derived(repo, root, "s2"), "held", attempt_id="a")
    assert [(v.state, v.reason) for v in views[2:5]] == [("unknown", "dirty"), ("unknown", "not_listed"), ("unknown", "git_unavailable")]
    monkeypatch.setattr(repo, "worktrees", unavailable)
    after = observe(factory, repo, viewed(repo), rid(repo), unlocked)
    assert after[1].state == "held" and {(v.state, v.reason) for v in after if v.name != "s2"} == {("unknown", "git_unavailable")}


def test_main_checkout_at_a_slot_path_is_never_free(
    factory: sqlite3.Connection, repo: FakeRepo, root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    add(repo, root, "s1")
    adopted(factory, repo, root, 1)
    path = derived(repo, root, "s1")
    monkeypatch.setattr(repo, "worktrees", lambda *, with_dirty=False: (WorktreeInfo(path, None, "main", True, None),))
    assert observe(factory, repo, viewed(repo), rid(repo), unlocked) == (SlotView("s1", path, "unknown", "main"),)


def test_store_failure_never_shows_a_free_slot(factory: sqlite3.Connection, repo: FakeRepo, root: Path) -> None:
    add(repo, root, "s1")
    adopted(factory, repo, root, 1)
    factory.execute("DROP TABLE reservation")
    unknown = SlotView("s1", derived(repo, root, "s1"), "unknown", "store_unavailable")
    assert observe(factory, repo, viewed(repo), rid(repo), unlocked) == (unknown,)
    factory.execute("DROP TABLE slot")
    with pytest.raises(SlotsUnavailable):
        observe(factory, repo, viewed(repo), rid(repo), unlocked)


def test_two_repos_each_have_their_own_s1(factory: sqlite3.Connection, repo: FakeRepo, root: Path, tmp_path: Path) -> None:
    remote = FakeRemote("https://example.invalid/other.git")
    remote.advance("main", {"README": "two"})
    other = FakeRepo.clone(remote, tmp_path / "other")
    for each in (repo, other):
        add(each, root, "s1")
        assert adopted(factory, each, root, 1) == (Adopted("s1", derived(each, root, "s1")),)
    factory.execute("INSERT INTO reservation (slot,repo_id,generation,attempt_id) VALUES ('s1',?,1,'a')", (rid(repo),))
    assert observe(factory, repo, viewed(repo), rid(repo), unlocked)[0].state == "held"
    assert observe(factory, other, viewed(other), rid(other), unlocked)[0].state == "free"


def test_readopting_under_another_root_is_reported_not_moved(
    factory: sqlite3.Connection, repo: FakeRepo, root: Path, tmp_path: Path
) -> None:
    add(repo, root, "s1")
    adopted(factory, repo, root, 1)
    elsewhere = tmp_path / "elsewhere"
    add(repo, elsewhere, "s1")
    assert adopted(factory, repo, elsewhere, 1) == (NotAdopted("s1", "other_root", derived(repo, elsewhere, "s1")),)
    assert factory.execute("SELECT path FROM slot").fetchall() == [(str(derived(repo, root, "s1")),)]


def test_a_root_inside_the_main_checkout_is_refused(factory: sqlite3.Connection, repo: FakeRepo) -> None:
    inside = repo.path / ".slots"
    add(repo, inside, "s1")
    assert adopted(factory, repo, inside, 1) == (NotAdopted("s1", "inside_checkout", derived(repo, inside, "s1")),)
    assert factory.execute("SELECT count(*) FROM slot").fetchone() == (0,)


def test_nothing_pending_takes_no_write_lock(factory: sqlite3.Connection, repo: FakeRepo, root: Path) -> None:
    add(repo, root, "s1")
    adopted(factory, repo, root, 1)
    taken: list[int] = []

    def begin(con: sqlite3.Connection) -> AbstractContextManager[None]:
        taken.append(1)
        return begin_immediate(con)

    assert adopt(lambda: factory, begin, repo, viewed(repo), root, 1) == (Adopted("s1", derived(repo, root, "s1")),)
    repo.worktree(derived(repo, root, "s1")).write_file("dirty", "x")
    s1, s2 = derived(repo, root, "s1"), derived(repo, root, "s2")
    assert adopt(lambda: factory, begin, repo, viewed(repo), root, 2) == (Adopted("s1", s1), NotAdopted("s2", "not_listed", s2))
    assert taken == []


@pytest.mark.parametrize(("lock", "reason"), [(False, "locked"), (None, "lock_unavailable")])
def test_a_free_looking_slot_whose_lock_is_held_or_unknown_is_never_free(
    factory: sqlite3.Connection, repo: FakeRepo, root: Path, lock: bool | None, reason: str
) -> None:
    """A release still parking it holds the lock: admission must not reserve it. Held slots are never probed."""
    add(repo, root, "s1", "s2")
    adopted(factory, repo, root, 2)
    factory.execute("INSERT INTO reservation (slot,repo_id,generation,attempt_id) VALUES ('s2',?,1,'a')", (rid(repo),))
    probed: list[str] = []

    def probe(slot_path: str) -> bool | None:
        probed.append(slot_path)
        return lock

    views = observe(factory, repo, viewed(repo), rid(repo), probe)
    assert [(view.state, view.reason) for view in views] == [("unknown", reason), ("held", None)]
    assert probed == [str(derived(repo, root, "s1"))]


def test_a_slot_reserved_while_it_was_probed_is_held_not_free(factory: sqlite3.Connection, repo: FakeRepo, root: Path) -> None:
    """The reservation is read again after the probe: a concurrent admission that reserved the slot meanwhile wins."""
    add(repo, root, "s1")
    adopted(factory, repo, root, 1)

    def probe(_slot_path: str) -> bool:
        factory.execute("INSERT INTO reservation (slot,repo_id,generation,attempt_id) VALUES ('s1',?,1,'won')", (rid(repo),))
        return True

    assert observe(factory, repo, viewed(repo), rid(repo), probe) == (SlotView("s1", derived(repo, root, "s1"), "held", attempt_id="won"),)


def test_slot_use_counts_the_adopted_slots_without_a_reservation_row_and_lists_every_row(factory: sqlite3.Connection) -> None:
    store = AttemptStore(lambda: factory)
    assert store.slot_use() == SlotUse(0, frozenset())
    factory.execute("INSERT INTO slot (repo_id,name,path) VALUES ('r','s1','/r/s1'),('r','s2','/r/s2'),('q','s1','/q/s1')")
    factory.execute("INSERT INTO reservation VALUES ('s1','r',1,'a1')")
    assert store.slot_use() == SlotUse(2, frozenset({("r", "s1")}))  # across repos: q's s1 is not r's
    factory.execute("INSERT INTO reservation VALUES ('s2','r',1,'a2'),('s1','q',3,'a3')")
    assert store.slot_use() == SlotUse(0, frozenset({("r", "s1"), ("r", "s2"), ("q", "s1")}))
    with pytest.raises(StoreUnavailable):
        AttemptStore(lambda: None).slot_use()


def test_a_slot_is_read_only_through_its_verified_pinned_view_and_a_redirected_one_is_never_read(
    factory: sqlite3.Connection, repo: FakeRepo, root: Path
) -> None:
    """Adoption and observation run the pointer check and bind its common directory to this repository before the one
    status read, which opens the slot pinned to the verified G; a pointer rewritten to another Git directory, or to a
    well-formed linked Git directory of another repository, is `redirected` with no open of the slot at all."""
    other = FakeRepo.init(root.parent / "other")
    views, files = PinnedViews(repo, other), FakeSlotFiles(repo)
    add(repo, root, "s1", "s2", "s3")
    s1, s2, s3 = (derived(repo, root, name) for name in ("s1", "s2", "s3"))
    files.contents[s2 / ".git"] = b"gitdir: /elsewhere/.git/worktrees/s2\n"
    linked_into(files, s3, other)
    found = adopt(lambda: factory, begin_immediate, repo, SlotGit(views, files), root, 3)
    assert found == (Adopted("s1", s1), NotAdopted("s2", "redirected", s2), NotAdopted("s3", "redirected", s3))
    assert (views.slot_opens(s1), views.slot_opens(s2), views.slot_opens(s3)) == ([files.common / "worktrees/s1"], [], [])
    views.opened.clear()
    linked_into(files, s1, other)  # after adoption: the free slot's pointer now names the other repository
    assert observe(factory, repo, SlotGit(views, files), rid(repo), unlocked) == (SlotView("s1", s1, "unknown", "redirected"),)
    assert views.slot_opens(s1) == [] and (other.identity().root, None) in views.opened  # its identity was read, not the slot


@pytest.mark.parametrize(("origin", "name"), [
    ("git@github.com:iorlas/iorlas-task-loop.git", "iorlas-task-loop"),
    ("https://github.com/iorlas/iorlas-task-loop/", "iorlas-task-loop"),
    ("/srv/git/my repo.git", "my-repo"),
])
def test_the_folder_is_the_origins_readable_name(origin: str, name: str) -> None:
    assert folder_name(RepoIdentity(Path("/checkouts/other"), Path("/checkouts/other/.git"), origin, "0123456789ab")) == name


def test_without_an_origin_the_checkout_folder_names_it() -> None:
    assert folder_name(RepoIdentity(Path("/checkouts/mine"), Path("/checkouts/mine/.git"), None, "0123456789ab")) == "mine"


def test_the_key_joins_the_name_only_when_another_repository_holds_it(factory: sqlite3.Connection, repo: FakeRepo, root: Path) -> None:
    held = root.resolve() / folder_name(repo.identity()) / "s1"
    factory.execute("INSERT INTO slot (repo_id,name,path) VALUES ('another','s1',?)", (str(held),))
    joined = root.resolve() / f"{folder_name(repo.identity())}-{repo.identity().key}"
    repo.add_worktree(joined / "s1", "HEAD")
    assert adopted(factory, repo, root, 1) == (Adopted("s1", joined / "s1"),)
    assert adopted(factory, repo, root, 1) == (Adopted("s1", joined / "s1"),)
