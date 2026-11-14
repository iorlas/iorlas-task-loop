"""Atomic conflict admission; no external writes and no effects in its write transaction."""

import sqlite3
from dataclasses import astuple

from git_porcelain import Repo

from taskloop.admit import AdmitUnavailable, free_slots
from taskloop.admit_rows import reserve
from taskloop.attempt_loads import retained_on
from taskloop.attempt_reads import StoreConnection, StoreRefused, StoreUnavailable, as_int, as_text
from taskloop.attempt_types import AttemptKey
from taskloop.land_conflict.abort_models import transition
from taskloop.land_conflict.cleanup_models import transition as cleanup_transition
from taskloop.land_conflict.models import AdmissionRefused, Outcome, Record, Request, Save, SavePhase, Slot
from taskloop.land_conflict.release_models import ReleasePhase
from taskloop.land_conflict.reservation_store import owns
from taskloop.land_store import require_checked
from taskloop.repo import RepoId
from taskloop.slot_release import free
from taskloop.slots import Probe, SlotGit


def existing(con: sqlite3.Connection, request: Request) -> Record | None:
    row = con.execute("SELECT data FROM land_conflict WHERE implement_id=?", (request.source.attempt_id,)).fetchone()
    if row is None:
        return None
    record = Record.model_validate_json(as_text(row[0]))
    if not request.matches(record.inputs) or request.checks != record.request.checks:
        raise AdmissionRefused(Outcome.SOURCE)
    return record


class ConflictStore(StoreConnection):
    def completed(self, key: AttemptKey) -> Save | None:
        """Historical completion grants only a result read, independently of current slot custody."""
        with self._connection() as con:
            row = con.execute(
                "SELECT save_data FROM land_conflict WHERE operation_id=? AND dispatch_token=? AND generation=?",
                astuple(key),
            ).fetchone()
        try:
            saved = None if row is None or row[0] is None else Save.model_validate_json(as_text(row[0]))
        except ValueError as error:
            raise StoreUnavailable("Malformed retained conflict save") from error
        return saved if (saved is not None and saved.key == key and saved.release is not None
                         and saved.release.phase is ReleasePhase.COMPLETE) else None

    def saved(self, key: AttemptKey) -> Save | None:
        with self._connection() as con:
            if not owns(con, key):
                raise StoreRefused("stale_reservation")
            row = con.execute("SELECT save_data FROM land_conflict WHERE operation_id=?", (key.attempt_id,)).fetchone()
        if row is None:
            raise StoreRefused("stale_reservation")
        try:
            return None if row[0] is None else Save.model_validate_json(as_text(row[0]))
        except ValueError as error:
            raise StoreUnavailable("Malformed retained conflict save") from error

    def save(self, key: AttemptKey, previous: Save | None, updated: Save) -> Save:
        value = Save.model_validate(updated.model_dump())
        if value.key != key or (value.release is not None and value.release.phase is ReleasePhase.COMPLETE):
            raise StoreRefused("stale_reservation")
        progress = {SavePhase.CAPTURE: SavePhase.OBJECT, SavePhase.OBJECT: SavePhase.REF, SavePhase.REF: SavePhase.COMPLETE}
        if previous is None:
            if value.phase is not SavePhase.CAPTURE:
                raise StoreRefused("stale_reservation")
        elif previous.phase is SavePhase.COMPLETE and value.phase is SavePhase.COMPLETE:
            if (previous.model_dump(exclude={"abort", "cleanup", "release"})
                    != value.model_dump(exclude={"abort", "cleanup", "release"})
                    or previous == value
                    or (previous.abort != value.abort and not transition(previous.abort, value.abort))
                    or (previous.cleanup != value.cleanup and not cleanup_transition(previous.cleanup, value.cleanup))
                    or (previous.release != value.release and (
                        previous.release is not None or value.release is None
                        or previous.model_dump(exclude={"release"}) != value.model_dump(exclude={"release"})))):
                raise StoreRefused("stale_reservation")
        elif (progress.get(previous.phase) is not value.phase
              or previous.model_dump(exclude={"phase", "tree", "commit"}) != value.model_dump(exclude={"phase", "tree", "commit"})
              or (previous.tree is not None and previous.tree != value.tree)
              or (previous.commit is not None and previous.commit != value.commit)):
            raise StoreRefused("stale_reservation")
        with self._connection(write=True) as con:
            if not owns(con, key):
                raise StoreRefused("stale_reservation")
            if value.release is not None:
                _release_admission(con, key, value)
            changed = con.execute(
                "UPDATE land_conflict SET save_data=? WHERE operation_id=? AND save_data IS ?",
                (value.model_dump_json(), key.attempt_id, None if previous is None else previous.model_dump_json()),
            ).rowcount
            if changed != 1:
                raise StoreRefused("stale_reservation")
        return value

    def release(self, key: AttemptKey, previous: Save, updated: Save) -> Save:
        """Complete the frozen release and remove exactly its reservation in one transaction."""
        value = Save.model_validate(updated.model_dump())
        if (previous.key != key or value.key != key or previous.release is None or value.release is None
                or previous.release.phase is not ReleasePhase.PENDING or value.release.phase is not ReleasePhase.COMPLETE
                or previous.model_dump(exclude={"release"}) != value.model_dump(exclude={"release"})
                or previous.release.model_dump(exclude={"phase"}) != value.release.model_dump(exclude={"phase"})):
            raise StoreRefused("stale_reservation")
        with self._connection(write=True) as con:
            if not owns(con, key):
                raise StoreRefused("stale_reservation")
            _release_admission(con, key, value)
            changed = con.execute(
                "UPDATE land_conflict SET save_data=? WHERE operation_id=? AND save_data IS ?",
                (value.model_dump_json(), key.attempt_id, previous.model_dump_json()),
            ).rowcount
            removed = free(con, value.repo_id, value.slot, key.attempt_id, key.reservation_generation)
            if changed != 1 or removed != 1:
                raise StoreRefused("stale_reservation")
        return value

    def load(self, key: AttemptKey) -> Record:
        with self._connection() as con:
            if not owns(con, key):
                raise StoreRefused("stale_reservation")
            row = con.execute("SELECT data FROM land_conflict WHERE operation_id=?", (key.attempt_id,)).fetchone()
        if row is None:
            raise StoreRefused("stale_reservation")
        return Record.model_validate_json(as_text(row[0]))

    def find(self, request: Request) -> Record | None:
        with self._connection() as con:
            return existing(con, request)

    def observe(self, repo: Repo, git: SlotGit, request: Request, probe: Probe) -> tuple[Slot, ...]:
        with self._connection() as con:
            before = {as_text(name): (as_text(path), as_int(generation)) for name, path, generation in con.execute(
                "SELECT name,path,generation FROM slot WHERE repo_id=?", (request.repo_id,)).fetchall()}
            views = free_slots(con, repo, git, RepoId(request.repo_id), probe)
            if not isinstance(views, tuple):
                if isinstance(views, AdmitUnavailable):
                    raise StoreUnavailable(views.detail)
                raise AdmissionRefused(Outcome.NO_SLOT)
            heads = {info.path: info.head for info in repo.worktrees()}
        return tuple(Slot(name=view.name, path=str(view.path), generation=before[view.name][1], head=head)
                     for view in views if (head := heads.get(view.path)) is not None
                     and view.name in before and before[view.name][0] == str(view.path))

    def insert(self, proposed: Record, slots: tuple[Slot, ...]) -> tuple[Record, bool]:
        request = proposed.request
        with self._connection(write=True) as con:
            found = existing(con, request)
            if found is not None:
                return found, False
            inputs = retained_on(con, request.source)
            if inputs is None or not request.matches(inputs) or inputs != proposed.inputs:
                raise AdmissionRefused(Outcome.SOURCE)
            checked = con.execute(
                "SELECT after_attempt_id,target_commit FROM checks_attempt "
                "WHERE attempt_id=? AND dispatch_token=? AND generation=?", astuple(request.checks),
            ).fetchone()
            if checked != (request.source.attempt_id, request.checked):
                raise AdmissionRefused(Outcome.SOURCE)
            require_checked(con, request.checks.attempt_id, conflict=True)
            chosen = next((slot for slot in slots if con.execute(
                "SELECT 1 FROM slot s WHERE s.repo_id=? AND s.name=? AND s.path=? AND s.generation=? "
                "AND NOT EXISTS (SELECT 1 FROM reservation q WHERE q.repo_id=s.repo_id AND q.slot=s.name)",
                (request.repo_id, slot.name, slot.path, slot.generation),
            ).fetchone() is not None), None)
            if chosen is None:
                raise AdmissionRefused(Outcome.NO_SLOT)
            key = AttemptKey(proposed.key.attempt_id, proposed.key.dispatch_token, chosen.generation + 1)
            record = proposed.model_copy(update={"key": key, "slot": chosen.name, "slot_path": chosen.path, "base": chosen.head})
            reserve(con, RepoId(request.repo_id), chosen.name, key)
            con.execute(
                "INSERT INTO land_conflict (operation_id,dispatch_token,implement_id,checks_id,repo_id,slot,generation,data) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (key.attempt_id, key.dispatch_token, request.source.attempt_id, request.checks.attempt_id,
                 request.repo_id, chosen.name, key.reservation_generation, record.model_dump_json()),
            )
        return record, True


def _release_admission(con: sqlite3.Connection, key: AttemptKey, saved: Save) -> None:
    row = con.execute("SELECT data FROM land_conflict WHERE operation_id=?", (key.attempt_id,)).fetchone()
    record = Record.model_validate_json(as_text(row[0]))
    if (saved.release is None or saved.release.work.base != record.base or record.key != key
            or (saved.repo_id, saved.slot, str(saved.slot_path), saved.source, saved.target)
            != (record.request.repo_id, record.slot, record.slot_path, record.request.checked, record.request.target)):
        raise StoreRefused("stale_reservation")
