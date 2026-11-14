"""Drain observes conflict workers; only confirmed exit permits restartable saved-work release."""

from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

import land_conflict_bench
import pytest
from git_porcelain import Recorded, Sha
from git_porcelain.testing import FakeRepo, FakeWorktree
from land_conflict_bench import ExecutionCase
from merge_bench import head

from taskloop.attempt_types import AttemptKey
from taskloop.drain.composition import open_drain
from taskloop.drain.drain import Ports, drain, inspect
from taskloop.drain.models import Conclusion, Owner, Role, Seen, State
from taskloop.land_conflict.models import Save
from taskloop.land_conflict.release_models import ReleasePhase
from taskloop.land_conflict.store import ConflictStore
from taskloop.merge.models import Disposition, InProgress, Terminal


@pytest.fixture
def repo(tmp_path: Path) -> FakeRepo:
    return land_conflict_bench.execution_repo(tmp_path)


@pytest.fixture
def execution_case(on_slot: Path, repo: FakeRepo, slot: FakeWorktree, tmp_path: Path) -> Generator[ExecutionCase]:
    author = repo.add_worktree(tmp_path / "base-author", head(slot))
    author.write_file("README", "admitted base\n")
    author.write_file("base-only", "base bytes\n")
    base = author.record("admitted base", paths="all")
    assert isinstance(base, Recorded)
    repo.drop_worktree(author.path)
    slot.park(str(base.sha))
    yield from land_conflict_bench.execution_case(on_slot, repo, slot, tmp_path, lambda wt: wt.remove_file("base-only"))


def edits(slot: FakeWorktree) -> None:
    slot.write_file("README", "saved edits\n")
    slot.write_file("notes", "saved untracked bytes\n")
    slot.write_file(".gitignore", "ignored\n")
    slot.write_file("ignored", "ignored bytes\n")


def contents(c: ExecutionCase) -> dict[str, str | None]:
    return {path: c.slot.read_file(path) for path in ("README", "base-only", "notes", ".gitignore", "ignored")}


def reserved(c: ExecutionCase) -> None:
    assert c.ports.store.load(c.record.key) == c.record
    assert c.con.execute("SELECT * FROM reservation").fetchall() == [
        (c.record.slot, c.record.request.repo_id, c.record.key.reservation_generation, c.record.key.attempt_id),
    ]
    assert c.con.execute("SELECT generation FROM slot WHERE name=?", (c.record.slot,)).fetchone() == (
        c.record.key.reservation_generation,
    )


def interrupted_wait(_seconds: float) -> None:
    raise KeyboardInterrupt


@contextmanager
def watching(c: ExecutionCase, seen: Seen) -> Generator[Ports]:
    def observe(owner: Owner) -> Seen:
        # The conflict worker is independent of the caller and completed setup processes.
        return seen if owner.role is Role.AGENT and owner.subject == c.record.key.attempt_id else Seen.GONE

    with open_drain(c.path) as opened:
        assert isinstance(opened, Ports)
        yield replace(opened, observe=observe, wait=interrupted_wait)


@pytest.mark.parametrize("registered_only", [False, True])
def test_live_and_unknown_workers_keep_custody_across_interrupted_drain(
    execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch, registered_only: bool,
) -> None:
    c = execution_case
    c.gone, c.interrupt = False, registered_only
    c.disposition, c.edit = Disposition.OWNER, edits
    if registered_only:
        with pytest.raises(KeyboardInterrupt):
            c.resume()
    else:
        assert isinstance(c.resume(), InProgress)
    before, checkout = contents(c), (head(c.slot), c.slot.branch(), c.slot.merging(), c.slot.unmerged())
    work = c.ports.merges.get(c.record.key.attempt_id)
    assert work is not None and len(work.executions) == 1 and not work.executions[0].ended
    worker = work.executions[0].worker
    assert worker is not None
    monkeypatch.setattr(FakeWorktree, "park", lambda *_args, **_kwargs: pytest.fail("live work must not be parked"))

    with watching(c, Seen.ALIVE) as ports:
        generation = ports.store.request().generation
        observed = inspect(ports, generation)
        assert observed.conclusion is Conclusion.WAITING
        assert [(owner.subject, owner.role, owner.identity) for owner in observed.active] == [
            (c.record.key.attempt_id, Role.AGENT, worker),
        ]
        assert drain(ports).conclusion is Conclusion.INTERRUPTED
        assert ports.store.boundary().state is State.DRAINING
    c.restart()
    assert isinstance(c.resume(), InProgress)
    reserved(c)
    assert contents(c) == before and c.calls == 1
    assert (head(c.slot), c.slot.branch(), c.slot.merging(), c.slot.unmerged()) == checkout

    with watching(c, Seen.UNKNOWN) as ports:
        observed = inspect(ports, generation)
        assert observed.conclusion is Conclusion.UNAVAILABLE
        assert [(owner.role, owner.identity) for owner in observed.uncertain] == [(Role.AGENT, worker)]
        found = drain(ports)
        assert found.conclusion is Conclusion.UNAVAILABLE and found.generation == generation
        assert ports.store.boundary().state is State.DRAINING
    c.restart()
    assert isinstance(c.resume(), InProgress) and c.calls == 1
    reserved(c)
    assert contents(c) == before
    assert (head(c.slot), c.slot.branch(), c.slot.merging(), c.slot.unmerged()) == checkout
    assert c.ports.store.saved(c.record.key) is None and c.ports.store.completed(c.record.key) is None
    assert not c.ports.repo.branches("task-loop/conflicts/")


@dataclass
class Effects:
    parks: int = 0
    releases: int = 0
    interrupt: bool = True


def inject_release_failure(c: ExecutionCase, patch: pytest.MonkeyPatch, *, at_release: bool, after: bool) -> Effects:
    effects = Effects()
    park, release = FakeWorktree.park, ConflictStore.release

    def parking(self: FakeWorktree, base: str, *, clean_keep: Sequence[str] | None = None, keep_ignored: bool = False) -> Sha:
        assert not c.con.in_transaction
        if base != c.record.base:
            return park(self, base, clean_keep=clean_keep, keep_ignored=keep_ignored)
        if effects.interrupt and not at_release and not after:
            raise KeyboardInterrupt
        result = park(self, base, clean_keep=clean_keep, keep_ignored=keep_ignored)
        effects.parks += 1
        if effects.interrupt and not at_release:
            raise KeyboardInterrupt
        return result

    def releasing(self: ConflictStore, key: AttemptKey, previous: Save, updated: Save) -> Save:
        if effects.interrupt and at_release and not after:
            raise KeyboardInterrupt
        result = release(self, key, previous, updated)
        effects.releases += 1
        if effects.interrupt and at_release:
            raise KeyboardInterrupt
        return result

    patch.setattr(FakeWorktree, "park", parking)
    patch.setattr(ConflictStore, "release", releasing)
    return effects


@pytest.mark.parametrize("at_release", [False, True])
@pytest.mark.parametrize("after", [False, True])
def test_confirmed_exit_allows_drain_then_reconciled_release(
    execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch, at_release: bool, after: bool,
) -> None:
    c = execution_case
    c.gone, c.disposition, c.edit = False, Disposition.OWNER, edits
    assert isinstance(c.resume(), InProgress) and c.calls == 1
    before = contents(c)
    checkout = (head(c.slot), c.slot.branch(), c.slot.merging())
    with watching(c, Seen.ALIVE) as ports:
        found = drain(ports)
        assert found.conclusion is Conclusion.INTERRUPTED
        generation = found.generation
        assert generation is not None
    c.restart()
    c.gone = True
    with watching(c, Seen.GONE) as ports:
        found = drain(ports)
        assert found.conclusion is Conclusion.COMPLETE and found.generation == generation
        assert ports.store.boundary().state is State.COMPLETE
    reserved(c)
    assert contents(c) == before and c.ports.store.saved(c.record.key) is None
    assert (head(c.slot), c.slot.branch(), c.slot.merging()) == checkout and c.calls == 1

    effects = inject_release_failure(c, monkeypatch, at_release=at_release, after=after)
    with pytest.raises(KeyboardInterrupt):
        c.resume()
    saved = c.ports.store.completed(c.record.key) or c.ports.store.saved(c.record.key)
    assert saved is not None and saved.release is not None
    assert saved.release.phase is (ReleasePhase.COMPLETE if at_release and after else ReleasePhase.PENDING)
    if not (at_release and after):
        reserved(c)
    assert c.slot.read_file("ignored") == "ignored bytes\n"
    c.restart()
    effects.interrupt = False
    assert c.resume() == saved.release.result and isinstance(saved.release.result, Terminal)
    completed = c.ports.store.completed(c.record.key)
    assert completed is not None and completed.release is not None and completed.release.phase is ReleasePhase.COMPLETE
    assert (completed.ref, completed.commit) == (saved.ref, saved.commit)
    assert c.con.execute("SELECT * FROM reservation").fetchall() == []
    assert c.con.execute("SELECT generation FROM slot WHERE name=?", (c.record.slot,)).fetchone() == (
        c.record.key.reservation_generation,
    )
    assert head(c.slot) == c.record.base and c.slot.branch() is None and not c.slot.merging()
    assert c.slot.read_file("README") == "admitted base\n" and c.slot.read_file("base-only") == "base bytes\n"
    assert c.slot.read_file("ignored") == "ignored bytes\n" and c.slot.read_file("notes") is None
    tree = c.ports.repo.tree(completed.commit or "")
    assert tree is not None and tree.read("README") == b"saved edits\n" and tree.read("notes") == b"saved untracked bytes\n"
    assert dict(c.ports.repo.branches("task-loop/conflicts/")) == {completed.ref.removeprefix("refs/heads/"): completed.commit}
    assert not c.ports.merges.active_processes() and c.calls == 1
    assert (effects.parks, effects.releases) == (1, 1)
    c.restart()
    assert c.resume() == completed.release.result
    assert c.ports.store.completed(c.record.key) == completed and contents(c)["ignored"] == "ignored bytes\n"
    assert (effects.parks, effects.releases, c.calls) == (1, 1, 1)
    with watching(c, Seen.UNKNOWN) as ports:
        assert inspect(ports, generation).conclusion is Conclusion.COMPLETE
