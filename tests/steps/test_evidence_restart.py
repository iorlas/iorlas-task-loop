"""Uncommitted admission evidence stays inert across an intact-database restart."""

import sqlite3
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

import pytest
from check_repeat_bench import Repairing
from round_bench import task
from sqlite_store import Store, begin_immediate
from test_check_repeat import failed, rig
from test_repeat import CONTENT_DIGEST

from taskloop.admit import AdmitRefused, AdmitRequest, AdmitResult, Admitted, AttemptAdmission
from taskloop.admit_chain import ChainAdmission, NextAdmission, NextStepRequest, RepeatRequest
from taskloop.agents.settings import AgentSetting
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, FileRef
from taskloop.check_repeat.repair import CheckRepeat
from taskloop.check_repeat.store import CheckRepeatStore
from taskloop.evidence_files import EvidenceFiles
from taskloop.factory_schema import SCHEMA
from taskloop.git_views import GitProfileFiles
from taskloop.ids import NativeIds
from taskloop.launch import Launched
from taskloop.operations import Failed, Started

__all__ = ["rig"]

Begin = Callable[[sqlite3.Connection], AbstractContextManager[None]]
Call = Callable[[], AdmitResult | Started | Failed]
Build = Callable[[sqlite3.Connection, EvidenceFiles, Begin], Call]
Rows = tuple[tuple[tuple[object, ...], ...], ...]


class Interrupted(BaseException):
    """Stop admission without turning the interruption into a normal refusal."""


class Launcher:
    """Observe dispatch requests without executing the admitted repair."""

    def __init__(self, con: sqlite3.Connection) -> None:
        self.store = AttemptStore(lambda: con)

    def launch(self, backlog: str, task_id: str, minutes: int) -> Launched:
        found = self.store.attempt_of(backlog, task_id)
        assert found is not None
        return Launched(found[0], (7, "start", "boot"))


class InterruptedFiles(EvidenceFiles):
    def __init__(self, root: Path, *, inside: bool) -> None:
        super().__init__(root)
        self.inside = inside
        self.key: AttemptKey | None = None
        self.ref: FileRef | None = None

    def put_input(self, key: AttemptKey, text: str) -> FileRef:
        self.key, self.ref = key, super().put_input(key, text)
        if not self.inside:
            raise Interrupted
        return self.ref


@contextmanager
def interrupted_commit(con: sqlite3.Connection) -> Generator[None]:
    with begin_immediate(con):
        yield
        raise Interrupted  # SQLite rolls back the unfinished transaction before the connection disappears.


def rows(con: sqlite3.Connection) -> Rows:
    return tuple(tuple(con.execute(f"SELECT * FROM {table} ORDER BY rowid"))
                 for table in ("attempt", "reservation", "slot", "task_content"))


def initial(con: sqlite3.Connection, files: EvidenceFiles, begin: Begin, bench: Repairing) -> AttemptAdmission:
    return AttemptAdmission(
        lambda: con, begin, files, bench.tracker.inspect, bench.checkouts, bench.tracker.claim, bench.tracker.unclaim,
        lambda: bench.now, lambda _path: True, bench.files, ids=NativeIds(),
    )


def request(bench: Repairing, task_id: str = "tl-1") -> AdmitRequest:
    return AdmitRequest(task_id, "tasks", "/tracker", bench.slot.repo.path, AgentSetting(model="m", effort="high"), 1000, "auto")


def protect(bench: Repairing) -> tuple[dict[Path, bytes], AttemptKey]:
    """Keep a separate committed admission, unrelated evidence, and user files alongside the interrupted work."""
    bench.adopt("s2")
    bench.tracker.beads["tl-2"] = task("tl-2")
    files = EvidenceFiles(bench.tmp)
    admitted = initial(bench.con, files, begin_immediate, bench).admit(request(bench, "tl-2"))
    assert isinstance(admitted, Admitted)
    files.put_input(AttemptKey("unrelated", "unrelated-token", 1), "Unrelated retained evidence\n")
    user = bench.tmp / "attempts" / "user-notes.bin"
    user.write_bytes(b"User data\x00\xff\n")
    retained = {path: path.read_bytes() for path in (bench.tmp / "attempts").rglob("*") if path.is_file()}
    return retained, admitted.key


def exercise(bench: Repairing, build: Build, *, inside: bool) -> None:
    retained, protected = protect(bench)
    before, claims = rows(bench.con), tuple(bench.tracker.claims)
    reserved = bench.con.execute("SELECT * FROM reservation WHERE attempt_id=?", (protected.attempt_id,)).fetchone()
    files = InterruptedFiles(bench.tmp, inside=inside)
    with pytest.raises(Interrupted):
        build(bench.con, files, interrupted_commit if inside else begin_immediate)()
    assert files.ref is not None and files.key is not None
    orphan = bench.tmp / files.ref.path
    retained[orphan] = orphan.read_bytes()
    bench.con.close()

    con = Store(SCHEMA).open_rw(bench.path)
    assert con is not None
    try:
        assert rows(con) == before  # In particular, the old reservation and generation survive a rollback.
        assert tuple(bench.tracker.claims) == claims
        assert all(path.read_bytes() == content for path, content in retained.items())
        fresh = EvidenceFiles(bench.tmp)
        result = build(con, fresh, begin_immediate)()
        assert isinstance(result, (Admitted, Started))
        store = AttemptStore(lambda: con)
        current = store.attempt_of("tasks", "tl-1")
        assert current is not None
        key = current[0]
        assert key != files.key and key.attempt_id != files.key.attempt_id
        committed_ref = store.input_ref(key)
        assert committed_ref != files.ref
        assert fresh.read(committed_ref)
        assert con.execute("SELECT count(*) FROM attempt WHERE attempt_id=?", (files.key.attempt_id,)).fetchone() == (0,)
        original = tuple(con.execute("SELECT * FROM attempt WHERE attempt_id<>? ORDER BY rowid", (key.attempt_id,)))
        assert original == before[0]
        assert con.execute("SELECT count(*) FROM reservation WHERE attempt_id=? AND generation=?",
                           (key.attempt_id, key.reservation_generation)).fetchone() == (1,)
        assert reserved is not None and reserved in rows(con)[1]
        committed = rows(con)
        retained[bench.tmp / committed_ref.path] = fresh.read(committed_ref).encode("utf-8")
        con.close()
        con = Store(SCHEMA).open_rw(bench.path)
        assert con is not None
        assert rows(con) == committed
        assert AttemptStore(lambda: con).input_ref(key) == committed_ref
        again = build(con, EvidenceFiles(bench.tmp), begin_immediate)()
        assert isinstance(again, (AdmitRefused, Started))
        assert rows(con) == committed
        assert all(path.read_bytes() == content for path, content in retained.items())
    finally:
        con.close()


def test_initial_admission_releases_unreferenced_input_after_reopen(rig: Repairing) -> None:
    def build(con: sqlite3.Connection, files: EvidenceFiles, begin: Begin) -> Call:
        admission = initial(con, files, begin, rig)
        return lambda: admission.admit(request(rig))

    exercise(rig, build, inside=False)
    assert rig.tracker.claims.count("tl-1") == 1


@pytest.mark.parametrize("inside", [False, True], ids=["input-written", "transaction-uncommitted"])
def test_repeat_reopens_with_the_previous_reservation_and_a_fresh_key(rig: Repairing, inside: bool) -> None:
    assert rig.round() == [("tl-1", "plan", "start", "started")]
    previous = rig.store.attempt_of("tasks", "tl-1")
    assert previous is not None
    repeated = RepeatRequest(previous[0], "Retry feedback", 1000, "unsafe", content_digest=CONTENT_DIGEST)

    def build(con: sqlite3.Connection, files: EvidenceFiles, begin: Begin) -> Call:
        admission = ChainAdmission(lambda: con, begin, files, lambda: rig.now, rig.checkouts, rig.files, ids=NativeIds())
        return lambda: admission.admit_repeat(repeated)

    exercise(rig, build, inside=inside)


@pytest.mark.parametrize("inside", [False, True], ids=["input-written", "transaction-uncommitted"])
def test_advance_reopens_without_losing_the_committed_plan(rig: Repairing, inside: bool) -> None:
    rig.by_hand("tl-1")
    previous = rig.store.attempt_of("tasks", "tl-1")
    assert previous is not None
    advanced = NextStepRequest(previous[0], rig.slot.repo.path, AgentSetting(model="m", effort="high"), 1000)

    def build(con: sqlite3.Connection, files: EvidenceFiles, begin: Begin) -> Call:
        admission = NextAdmission(lambda: con, begin, files, rig.tracker.inspect, rig.checkouts, lambda: rig.now,
                                  lambda _path: True, rig.files, ids=NativeIds())
        return lambda: admission.admit_next(advanced)

    exercise(rig, build, inside=inside)


@pytest.mark.parametrize("inside", [False, True], ids=["input-written", "transaction-uncommitted"])
def test_check_repair_reopens_with_a_fresh_key_and_keeps_failed_check_evidence(rig: Repairing, inside: bool) -> None:
    previous, source = failed(rig)

    def build(con: sqlite3.Connection, files: EvidenceFiles, begin: Begin) -> Call:
        admission = CheckRepeat(
            CheckRepeatStore(lambda: con, begin), files, rig.tracker.inspect, rig.checkouts, rig.files, lambda _path: True,
            lambda path: GitProfileFiles(path, rig.checkouts), Launcher(con), rig.observe,
            rig.command, lambda: rig.now, ids=NativeIds(),
        )
        return lambda: admission.repair(rig.request(), previous, source)

    exercise(rig, build, inside=inside)
