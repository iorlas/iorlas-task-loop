"""Killed rounds finish the same saved session, then retain completion across restarts."""

from collections.abc import Generator, Mapping, Sequence
from pathlib import Path

import pytest
from doubles import PinnedViews
from git_porcelain import Sha
from git_porcelain.api import PushResult
from git_porcelain.testing import FakeRemote, FakeWorktree
from killed_rounds_bench import OWNER, PLAN, WORKER, Effects, Killed, RestartFactory, connect
from plan_fixtures import PLAN_TEXT
from round_bench import Tracker, task

from taskloop.attempt_reads import PublishedRow
from taskloop.attempt_types import AttemptKey, SlotFiles, Verified
from taskloop.drain.models import Seen
from taskloop.release_proof import RecoveryReason
from taskloop.slot_release import AlreadyReleased, NotReleased


@pytest.fixture
def factory(
    tmp_path: Path, slot: FakeWorktree, checkouts: PinnedViews, slot_files: SlotFiles, monkeypatch: pytest.MonkeyPatch,
) -> Generator[RestartFactory]:
    built = RestartFactory(connect(tmp_path / "factory.db", initialize=True), tmp_path, slot, checkouts, slot_files,
                           Tracker(task("tl-1")), Effects(), monkeypatch)
    try:
        yield built
    finally:
        built.con.close()


def identity(factory: RestartFactory) -> tuple[object, ...]:
    row = factory.con.execute(
        "SELECT attempt_id,dispatch_token,generation,entry_pid,entry_start,entry_boot,session_ref FROM attempt",
    ).fetchone()
    assert row is not None
    return row


def artifacts(factory: RestartFactory) -> dict[str, bytes]:
    root = factory.tmp / "attempts"
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def assert_completed(factory: RestartFactory, remote: FakeRemote, attempt: AttemptKey) -> Verified:
    assert factory.con.execute("SELECT count(*) FROM attempt").fetchone() == (1,)
    assert factory.con.execute("SELECT count(*) FROM slot").fetchone() == (1,)
    assert factory.con.execute("SELECT * FROM reservation").fetchall() == []
    assert factory.tracker.claims == ["tl-1"] and factory.effects.claims
    assert factory.tracker.beads["tl-1"].assignee == "taskloop"
    assert len(factory.effects.calls) == 2
    assert "resume" not in factory.effects.calls[0].argv and "resume" in factory.effects.calls[1].argv
    captured = factory.store.collect(attempt)
    assert captured is not None and captured.answer.kind == "valid" and captured.session_state == "complete"
    verified = factory.ports().verifier.verify(attempt)
    assert isinstance(verified, Verified)
    tip = factory.tip("tl-1")
    tree = factory.slot.repo.tree(tip)
    assert tree is not None and tree.read(PLAN) == PLAN_TEXT.encode()
    base = factory.con.execute("SELECT base_commit FROM attempt").fetchone()
    assert base is not None and base[0] is not None
    assert [commit.sha for commit in factory.slot.repo.history([tip], not_on=[base[0]])] == [tip]
    assert remote.branches()["task/tl-1"] == tip
    assert factory.con.execute("SELECT count(*) FROM slot_release").fetchone() == (1,)
    return verified


@pytest.fixture
def delivery_counts(
    factory: RestartFactory, remote: FakeRemote, monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[Path], list[str], list[str]]:
    parks: list[Path] = []
    pushes: list[str] = []
    deliveries: list[str] = []
    park, push = FakeWorktree.park, FakeWorktree.push

    def parked(slot: FakeWorktree, base: str, *, clean_keep: Sequence[str] | None = None, keep_ignored: bool = False) -> Sha:
        result = park(slot, base, clean_keep=clean_keep, keep_ignored=keep_ignored)
        parks.append(slot.path)
        return result

    def pushed(
        slot: FakeWorktree, dst: str, *, remote: str = "origin", hook_env: Mapping[str, str] | None = None,
        head: Sha | None = None,
    ) -> PushResult:
        before = dict(remote_state.branches())
        result = push(slot, dst, remote=remote, hook_env=hook_env, head=head)
        pushes.append(dst)
        if before != remote_state.branches():
            deliveries.append(dst)
        factory.effects.after("push")
        return result

    remote_state = remote
    monkeypatch.setattr(FakeWorktree, "park", parked)
    monkeypatch.setattr(FakeWorktree, "push", pushed)
    return parks, pushes, deliveries


@pytest.mark.parametrize("boundary", ["session", "capture", "verify", "release", "push", "publish"])
def test_restart_completes_and_delivers_once(
    factory: RestartFactory, remote: FakeRemote, monkeypatch: pytest.MonkeyPatch, boundary: str,
    delivery_counts: tuple[list[Path], list[str], list[str]],
) -> None:
    parks, pushes, deliveries = delivery_counts
    with pytest.raises(Killed, match="session"):
        factory.round()
    original = identity(factory)
    key = factory.store.attempt_of("tasks", "tl-1")
    assert key is not None
    attempt = key[0]
    reservation = factory.con.execute("SELECT * FROM reservation").fetchall()
    original_artifacts = artifacts(factory)
    assert original_artifacts and original[-1] == "saved-session"
    assert factory.slot.read_file(PLAN) == PLAN_TEXT
    factory = factory.reopen()
    factory.effects.stop = "" if boundary == "session" else boundary
    if boundary != "session":
        with pytest.raises(Killed, match=boundary):
            for _ in range(3):
                factory.round()
        assert identity(factory) == original
        if boundary == "capture":
            assert factory.con.execute("SELECT answer_kind FROM execution").fetchone() == ("validation_pending",)
        factory = factory.reopen()
    try:
        for _ in range(3):
            if factory.con.execute("SELECT count(*) FROM published_branch").fetchone() == (1,):
                break
            factory.round()
        assert identity(factory) == original
        assert reservation
        verified = assert_completed(factory, remote, attempt)
        assert parks == [factory.slot.path] and deliveries == ["task/tl-1"]
        assert pushes == ["task/tl-1"] * (2 if boundary == "push" else 1)
        retained = artifacts(factory)
        assert original_artifacts.items() <= retained.items()
        # Stop returning this task to admission while retaining its external claim state.
        monkeypatch.setattr(factory.tracker, "show", lambda _task: None)
        for _ in range(2):
            factory = factory.reopen()
            factory.round()
            ports = factory.ports()
            assert ports.verifier.verify(attempt) == verified
            assert isinstance(ports.releaser.release(attempt, False), AlreadyReleased)
            assert isinstance(ports.publisher.publish(attempt), PublishedRow)
            assert artifacts(factory) == retained and identity(factory) == original
        assert len(factory.effects.calls) == 2 and factory.tracker.claims == ["tl-1"]
        assert factory.con.execute("SELECT count(*) FROM attempt").fetchone() == (1,)
        assert parks == [factory.slot.path] and deliveries == ["task/tl-1"]
        assert pushes == ["task/tl-1"] * (2 if boundary == "push" else 1)
    finally:
        factory.con.close()


@pytest.mark.parametrize("pid", [42, OWNER.pid, WORKER.pid])
@pytest.mark.parametrize("seen", [Seen.ALIVE, Seen.UNKNOWN])
def test_reopened_completion_waits_for_every_recovery_process(
    factory: RestartFactory, pid: int, seen: Seen,
) -> None:
    with pytest.raises(Killed):
        factory.round()
    original = identity(factory)
    factory = factory.reopen()
    factory.effects.stop = "verify"
    with pytest.raises(Killed, match="verify"):
        factory.round()
        factory.round()
    factory = factory.reopen()
    try:
        factory.effects.processes.states[pid] = seen
        before = artifacts(factory)
        reservation = factory.con.execute("SELECT * FROM reservation").fetchall()
        found = factory.store.attempt_of("tasks", "tl-1")
        assert found is not None
        refused = factory.releaser().release(found[0], False)
        assert isinstance(refused, NotReleased) and refused.detail
        assert refused.reason is (RecoveryReason.RUNNING if seen is Seen.ALIVE else RecoveryReason.UNKNOWN)
        factory.round()
        assert factory.con.execute("SELECT * FROM reservation").fetchall() == reservation
        assert factory.con.execute("SELECT count(*) FROM slot_release").fetchone() == (0,)
        assert artifacts(factory) == before and identity(factory) == original
        assert factory.tracker.beads["tl-1"].assignee == "taskloop"
        factory.effects.processes.states.clear()
        factory = factory.reopen()
        factory.round()
        assert factory.con.execute("SELECT * FROM reservation").fetchall() == []
        assert factory.con.execute("SELECT count(*) FROM slot_release").fetchone() == (1,)
        assert artifacts(factory) == before and identity(factory) == original
        assert len(factory.effects.calls) == 2
    finally:
        factory.con.close()
