"""The admission's row writes, inside the caller's write transaction: a new `reservation`, the admitted `attempt` row and the
slot's counter (`generation`, the last reservation generation issued for it)."""

import sqlite3
from collections.abc import Mapping
from dataclasses import astuple
from typing import Final

from pydantic import BaseModel, ValidationError

from taskloop.admit_rows import Current, Free, Previous, Task
from taskloop.attempt_types import AttemptKey
from taskloop.factory_schema import ATTEMPT_ADMITTED, LATER, REPEATED, RESERVATION, marks
from taskloop.repo import RepoId
from taskloop.step import Step, decode_step, encode_step
from taskloop.task_content import TaskContentDigest
from taskloop.task_content_store import TaskContentStore
from taskloop.workflow_read import Pin, pinned

_PREVIOUS = f"""SELECT p.generation,p.number,p.adapter,p.backlog,p.task_id,p.repo_id,p.slot,p.model,p.effort,p.access_policy,
{REPEATED},
p.phase='captured' AND EXISTS (SELECT 1 FROM reservation r WHERE r.repo_id=p.repo_id AND r.slot=p.slot AND r.attempt_id=p.attempt_id
 AND r.generation=p.generation)
AND EXISTS (SELECT 1 FROM execution e WHERE e.attempt_id=p.attempt_id AND e.answer_kind='valid' AND e.rc=0 AND e.timed_out=0
 AND e.effect IN ('commit','keep') AND e.session_state='complete')
AND NOT EXISTS (SELECT 1 FROM factory_commit v WHERE v.attempt_id=p.attempt_id),
p.tracker_root,p.seq,p.slot_head,p.step,p.label,p.harness,p.provider,p.compaction_token_limit
FROM attempt p WHERE p.attempt_id=? AND p.dispatch_token=? AND p.generation=?"""

_CURRENT = """SELECT p.attempt_id,p.dispatch_token,p.generation,
EXISTS (SELECT 1 FROM factory_commit v WHERE v.attempt_id=p.attempt_id AND v.verdict='committed')
AND EXISTS (SELECT 1 FROM slot_release x WHERE x.attempt_id=p.attempt_id AND x.claim='kept')
AND EXISTS (SELECT 1 FROM published_branch b WHERE b.attempt_id=p.attempt_id AND b.commit_sha=p.end_commit),
p.step,p.end_commit,p.tracker_root,p.seq,p.label
FROM attempt p WHERE p.adapter='beads' AND p.backlog=? AND p.task_id=? ORDER BY p.seq DESC LIMIT 1"""


def unheld(con: sqlite3.Connection, repo_id: RepoId, free: Free, generation: int) -> tuple[str, str] | None:
    """The slot's name and park destination, when unreserved with its counter below `generation`."""
    row: tuple[object, ...] | None = con.execute(
        "SELECT name FROM slot s WHERE repo_id=? AND name=? AND generation<? AND NOT EXISTS "
        "(SELECT 1 FROM reservation r WHERE r.repo_id=s.repo_id AND r.slot=s.name)",
        (repo_id, free.name, generation),
    ).fetchone()
    if row is None:
        return None
    if not isinstance(row[0], str):
        raise sqlite3.DatabaseError("Malformed slot row")
    return row[0], free.park_commit


def reserve(con: sqlite3.Connection, repo_id: RepoId, slot: str, key: AttemptKey) -> None:
    """The new reservation of a free slot for the attempt `key`, and the slot's counter, inside the caller's write
    transaction."""
    held = {"slot": slot, "repo_id": repo_id, "generation": key.reservation_generation, "attempt_id": key.attempt_id}
    con.execute(f"INSERT INTO reservation ({RESERVATION}) VALUES ({marks(RESERVATION)})", _bound(RESERVATION, held))
    issue(con, repo_id, slot, key.reservation_generation)


def insert_attempt(con: sqlite3.Connection, attempt: Mapping[str, object], content_digest: TaskContentDigest | None = None) -> None:
    """The admitted attempt row, inside the caller's write transaction."""
    raw_step = attempt["step"]
    if not isinstance(raw_step, str):
        raise sqlite3.IntegrityError("Admission requires an agent step")
    step = decode_step(raw_step)
    values = _bound(ATTEMPT_ADMITTED, {"source_checks_id": None, "repair_context": None, **attempt, "step": encode_step(step)})
    if step is Step.PLAN and content_digest is None:
        raise sqlite3.IntegrityError("Plan admission requires task-content evidence")
    con.execute(f"INSERT INTO attempt ({ATTEMPT_ADMITTED}) VALUES ({marks(ATTEMPT_ADMITTED)})", values)
    if step is Step.PLAN and content_digest is not None:
        TaskContentStore.insert(con, str(attempt["attempt_id"]), content_digest)


PIN: Final = ("workflow_digest", "workflow_sha")  # the attempt columns that name its stored workflow file and its commit
PIN_SQL: Final = f"{PIN[0]}, {PIN[1]}"


def pin_columns(con: sqlite3.Connection, pin: Pin) -> dict[str, object]:
    """Store the pin's bytes (once, keyed by their sha256) and name them for a new attempt row, inside the caller's write
    transaction; a task keeps the exact file it was admitted with."""
    con.execute("INSERT OR IGNORE INTO workflow_file (digest, content) VALUES (?, ?)", (pin.digest, pin.content))
    return dict(zip(PIN, (pin.digest, pin.sha), strict=True))


def _pin_of(con: sqlite3.Connection, previous_id: str) -> tuple[str, str]:
    row = con.execute(f"SELECT {PIN_SQL} FROM attempt WHERE attempt_id=?", (previous_id,)).fetchone()
    if row is None:
        raise sqlite3.DatabaseError("The earlier attempt is absent")
    return str(row[0]), str(row[1])


def copied_pin(con: sqlite3.Connection, previous_id: str) -> dict[str, object]:
    """The workflow columns of an earlier attempt, for a repeat of it: the same stored file, never a new read."""
    return dict(zip(PIN, _pin_of(con, previous_id), strict=True))


def stored_pin(con: sqlite3.Connection, previous_id: str) -> Pin:
    """The workflow an earlier attempt was admitted with, read from the stored bytes and never from Git; stored bytes that
    are missing or no longer load are a database fault (`sqlite3.DatabaseError`) or a `WorkflowRefusal`."""
    digest, sha = _pin_of(con, previous_id)
    row = con.execute("SELECT content FROM workflow_file WHERE digest=?", (digest,)).fetchone()
    if row is None:
        raise sqlite3.DatabaseError("The stored workflow file is absent")
    return pinned(bytes(row[0]), sha)


def issue(con: sqlite3.Connection, repo_id: object, slot: object, generation: int) -> None:
    """The slot's counter: the last reservation generation issued for it."""
    con.execute("UPDATE slot SET generation=? WHERE repo_id=? AND name=?", (generation, repo_id, slot))


def _bound(columns: str, values: Mapping[str, object]) -> tuple[object, ...]:
    """Values in the order of the owning column list, by name; a missing or extra column is a programming error."""
    names = columns.split(",")
    if set(names) != set(values):
        raise ValueError(f"Columns {sorted(set(names) ^ set(values))} do not match {columns}")
    return tuple(values[name] for name in names)


def _count(value: object) -> int:
    if isinstance(value, int):
        return value
    raise sqlite3.DatabaseError("Malformed stored integer")


def issued(con: sqlite3.Connection, repo_id: RepoId, names: tuple[str, ...]) -> int:
    """The highest generation issued for any of the named slots (0 when none was)."""
    marked = ",".join("?" * len(names))
    found = f"SELECT coalesce(max(generation),0) FROM slot WHERE repo_id=? AND name IN ({marked})"
    row = con.execute(found, (repo_id, *names)).fetchone()
    return _count(None if row is None else row[0])


def next_seq(con: sqlite3.Connection, backlog: str, task_id: str) -> int:
    row = con.execute(
        "SELECT coalesce(max(seq),0)+1 FROM attempt WHERE adapter='beads' AND backlog=? AND task_id=?", (backlog, task_id),
    ).fetchone()
    return _count(None if row is None else row[0])


def task_attempted(con: sqlite3.Connection, backlog: str, task_id: str) -> bool:
    """Only an abandoned current attempt whose claim was returned permits a fresh admission."""
    found = con.execute(
        """SELECT EXISTS (SELECT 1 FROM slot_release r WHERE r.attempt_id=p.attempt_id
        AND r.claim IN ('unclaimed','not_held')) FROM attempt p
        WHERE p.adapter='beads' AND p.backlog=? AND p.task_id=? ORDER BY p.seq DESC LIMIT 1""", (backlog, task_id),
    ).fetchone()
    return found is not None and not found[0]


def transfer(con: sqlite3.Connection, previous: AttemptKey, key: AttemptKey, repo_id: object, slot: object) -> bool:
    """Move one reservation inside its successor's admission transaction, fencing the predecessor."""
    moved = con.execute(
        "UPDATE reservation SET attempt_id=?,generation=? WHERE repo_id=? AND slot=? AND attempt_id=? AND generation=?",
        (key.attempt_id, key.reservation_generation, repo_id, slot, previous.attempt_id, previous.reservation_generation),
    ).rowcount
    if moved == 1:
        issue(con, repo_id, slot, key.reservation_generation)
    return moved == 1


def _decode[T: BaseModel](model: type[T], row: tuple[object, ...] | None) -> T | None:
    if row is None:
        return None
    try:
        fields = dict(zip(model.model_fields, row, strict=True))
        if "step" in fields:
            raw_step = fields["step"]
            if not isinstance(raw_step, str):
                raise ValueError("Admission requires an agent step")
            fields["step"] = decode_step(raw_step)
        return model.model_validate(fields)
    except (ValidationError, ValueError) as error:
        raise sqlite3.DatabaseError("Malformed admission row") from error


def previous(con: sqlite3.Connection, key: AttemptKey) -> Previous | None:
    return _decode(Previous, con.execute(_PREVIOUS, astuple(key)).fetchone())


def current(con: sqlite3.Connection, backlog: str, task_id: str) -> Current | None:
    return _decode(Current, con.execute(_CURRENT, (backlog, task_id)).fetchone())


def task_of(con: sqlite3.Connection, key: AttemptKey) -> Task | None:
    row = con.execute(
        "SELECT p.backlog,p.task_id,p.tracker_root,p.repo_id,p.step,NOT " + LATER + ",p.end_commit FROM attempt p "
        "WHERE p.attempt_id=? AND p.dispatch_token=? AND p.generation=?", astuple(key),
    ).fetchone()
    return _decode(Task, row)
