"""Admit an attempt that continues a task's step: a repeat (`admit_repeat`) is the step's next attempt, which takes over
the reservation its previous attempt holds in the same transaction, so the slot is never released between attempts. It
claims nothing: the tracker root and D are copied from the previous attempt. The only writer that moves a reservation
row from one attempt to the next; the attempt row and the slot's counter are written through `admit`'s shared writes.
"""

import secrets
import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from uuid import uuid4

from taskloop.admit import AdmitRefused, Admitted, AdmitUnavailable, as_count, deadline_refusal, insert_attempt, issue, open_store, why
from taskloop.attempt_types import ATTEMPTS, AttemptKey, FileRef, RepeatReason
from taskloop.evidence_files import EvidenceError, EvidenceFiles

# The previous attempt under the write lock: its numbers, its copied choices, a successor, the held reservation, a valid
# clean answer with its session complete, of effect `commit`/`keep` (the rule check of `factory_commit` and the verdict), no verdict, the
# tracker root its claim was taken at (copied: a repeat claims nothing), its task-wide order, D and step (all carried on).
PREVIOUS = """SELECT p.generation,p.number,p.adapter,p.backlog,p.task_id,p.repo_id,p.slot,p.model,p.effort,p.sandbox,
EXISTS (SELECT 1 FROM attempt s WHERE s.previous_attempt_id=p.attempt_id),
p.phase='captured' AND EXISTS (SELECT 1 FROM reservation r WHERE r.repo_id=p.repo_id AND r.slot=p.slot AND r.attempt_id=p.attempt_id
 AND r.generation=p.generation)
AND EXISTS (SELECT 1 FROM execution e WHERE e.attempt_id=p.attempt_id AND e.answer_kind='valid' AND e.rc=0 AND e.timed_out=0
 AND e.effect IN ('commit','keep') AND e.session_state='complete')
AND NOT EXISTS (SELECT 1 FROM verification v WHERE v.attempt_id=p.attempt_id),
p.tracker_root,p.seq,p.slot_head,p.step
FROM attempt p WHERE p.attempt_id=? AND p.dispatch_token=? AND p.generation=?"""


@dataclass(frozen=True)
class RepeatRequest:
    """The step's next attempt: `previous` is the current attempt it repeats, `text` its complete admitted input."""

    previous: AttemptKey
    text: str
    deadline: float
    reason: RepeatReason


class _Lost(Exception):
    """No reservation row moved from the previous attempt: roll the new attempt back."""


class ChainAdmission:
    def __init__(
        self,
        connect: Callable[[], sqlite3.Connection | None],
        begin: Callable[[sqlite3.Connection], AbstractContextManager[None]],
        files: EvidenceFiles,
        clock: Callable[[], float],
    ) -> None:
        self.connect, self.begin, self.files, self.clock = connect, begin, files, clock

    def admit_repeat(self, request: RepeatRequest) -> Admitted | AdmitRefused | AdmitUnavailable:
        """The next attempt N of `previous` (P), its input written first under N's key: in one write transaction, every
        check re-read under the lock, insert N (P's choices, number + 1, generation + 1) and move the held reservation
        from P to N, fenced on P and its generation. Afterwards every fenced write of P is refused."""
        refused = deadline_refusal(self.clock, request.deadline)
        if refused is not None:
            return refused
        previous = request.previous
        key = AttemptKey(uuid4().hex, secrets.token_hex(16), previous.reservation_generation + 1)
        try:
            ref = self.files.put_input(key, request.text)
        except (EvidenceError, UnicodeError, OSError) as error:
            return AdmitRefused("input", detail=why(error))
        try:
            return self._takeover(open_store(self.connect), request, key, ref)
        except _Lost:
            return AdmitRefused("task_attempted")
        except sqlite3.IntegrityError as error:  # caught after the rollback: a concurrent repeat's UNIQUE number or previous
            return AdmitRefused("task_attempted", detail=why(error))
        except sqlite3.Error as error:
            return AdmitUnavailable("store", detail=why(error))

    def _takeover(self, con: sqlite3.Connection, request: RepeatRequest, key: AttemptKey, ref: FileRef) -> Admitted | AdmitRefused:
        previous = request.previous
        with self.begin(con):
            row: tuple[object, ...] | None = con.execute(PREVIOUS, (previous.attempt_id, previous.dispatch_token,
                                                                    previous.reservation_generation)).fetchone()
            if row is None:
                return AdmitRefused("not_repeatable")
            if row[10]:
                return AdmitRefused("task_attempted")
            number = row[1]
            if not isinstance(number, int) or number >= ATTEMPTS:
                return AdmitRefused("repeat_cap")
            if not row[11]:
                return AdmitRefused("not_repeatable")
            refused = deadline_refusal(self.clock, request.deadline)
            if refused is not None:
                return refused
            insert_attempt(con, {
                "attempt_id": key.attempt_id, "dispatch_token": key.dispatch_token, "generation": key.reservation_generation,
                "adapter": row[2], "backlog": row[3], "task_id": row[4], "tracker_root": row[12], "repo_id": row[5], "slot": row[6],
                "input_path": ref.path, "input_digest": ref.digest, "schema_version": 1, "model": row[7], "effort": row[8],
                "sandbox": row[9], "deadline": request.deadline, "number": number + 1, "previous_attempt_id": previous.attempt_id,
                "repeat_reason": request.reason, "seq": as_count(row[13]) + 1, "slot_head": row[14], "step": row[15],
            })
            moved = con.execute(
                """UPDATE reservation SET attempt_id=?,generation=generation+1 WHERE repo_id=? AND slot=? AND attempt_id=?
                AND generation=?""",
                (key.attempt_id, row[5], row[6], previous.attempt_id, previous.reservation_generation),
            )
            if moved.rowcount != 1:
                raise _Lost
            issue(con, row[5], row[6], key.reservation_generation)
        return Admitted(key, str(row[6]))
