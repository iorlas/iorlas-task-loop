"""SQL owner for attempt status, listing, chains and execution; no admission or release writer."""

import json
import math
import sqlite3
from dataclasses import astuple, replace
from typing import Literal

from any_agent.procs import Worker

from taskloop import answer_failures, attempt_reads
from taskloop.attempt_loads import AttemptLoads, verdict_of
from taskloop.attempt_reads import StoreConnection, StoreRefused, StoreUnavailable, as_int, as_nullable_text, as_text
from taskloop.attempt_types import (
    ATTEMPTS,
    Admission,
    AnswerState,
    AttemptKey,
    AttemptRecord,
    ChainLink,
    EntryIdentity,
    Evidence,
    ExecutionFacts,
    FileRef,
    Replaced,
    Verdict,
)
from taskloop.drain.models import ActionKind, Identity, Owner, Role, owners
from taskloop.drain.store import blocked, pending
from taskloop.factory_schema import EVIDENCE, FACTS, REPEATED, SUCCESSOR, VERDICT
from taskloop.recovery.execution_models import Callback
from taskloop.recovery.models import Intent, Outcome, Result
from taskloop.recovery.state_store import fence

# A registration write (the entry's or the harness's) waits at most this for the write lock, so it finishes well inside
# the registered start's fixed 5 s window; every other write keeps the library's 5 s.
REGISTRATION_BUSY_MS = 1500


def configure_registration(con: sqlite3.Connection) -> None:
    """Keep registration lock waits inside the registered start's fixed window."""
    con.execute(f"PRAGMA busy_timeout={REGISTRATION_BUSY_MS}")


STEP = """SELECT p.number,p.base_commit,p.end_commit,p.input_path,p.input_digest,e.effect,e.commit_paths,
CASE WHEN p.repair_context IS NULL THEN p.previous_attempt_id ELSE
(SELECT previous_attempt_id FROM attempt WHERE attempt_id=p.previous_attempt_id) END
FROM attempt p LEFT JOIN execution e ON e.attempt_id=p.attempt_id"""


RELEASED = "SELECT head,released_at,claim FROM slot_release"


class AttemptReads(StoreConnection):
    """The status reads of agent attempts (the `attempt` table and its chain)."""

    def owns_entry(self, key: AttemptKey, identity: Identity) -> bool:
        """Whether this process is the registered entry of this exact attempt; no unrelated execution reads."""
        with self._connection() as con:
            return con.execute("SELECT 1 FROM attempt WHERE attempt_id=? AND dispatch_token=? AND generation=? "
                               "AND entry_pid=? AND entry_start=? AND entry_boot=?",
                               (*astuple(key), identity.pid, identity.start, identity.boot)).fetchone() is not None

    def drain_processes(self) -> tuple[Owner, ...]:
        """Every recorded execution identity, including historical and already concluded work."""
        with self._connection() as con:
            entries = con.execute("SELECT attempt_id,entry_pid,entry_start,entry_boot FROM attempt").fetchall()
            agents = con.execute("SELECT attempt_id,worker_pid,worker_pgid,worker_start,worker_boot FROM attempt").fetchall()
        return owners(entries, Role.ENTRY, group=False) + owners(agents, Role.AGENT, group=True)

    def state(self, key: AttemptKey) -> tuple[str, bool] | None:
        """Dispatch phase and recorded session conflict, without needing a live reservation (historical reads)."""
        with self._connection() as con:
            row = con.execute(
                "SELECT phase,session_conflict FROM attempt WHERE attempt_id=? AND dispatch_token=? AND generation=?", astuple(key)
            ).fetchone()
            return None if row is None else (as_text(row[0]), bool(as_int(row[1])))

    def attempt_of(self, backlog: str, task_id: str) -> tuple[AttemptKey, str, EntryIdentity | None] | None:
        """The recovery read: a task's current attempt (its highest `seq`) key, phase and registered entry, with no
        reservation or deadline check."""
        with self._connection() as con:
            row: tuple[object, ...] | None = con.execute(
                """SELECT attempt_id,dispatch_token,generation,phase,entry_pid,entry_start,entry_boot FROM attempt
                WHERE adapter='beads' AND backlog=? AND task_id=? ORDER BY seq DESC LIMIT 1""",
                (backlog, task_id),
            ).fetchone()
        if row is None:
            return None
        entry = None if any(value is None for value in row[4:7]) else (as_int(row[4]), as_text(row[5]), as_text(row[6]))
        return AttemptKey(as_text(row[0]), as_text(row[1]), as_int(row[2])), as_text(row[3]), entry

    def step_of(self, attempt_id: str) -> str | None:
        """The step an attempt belongs to (`plan`); None for an attempt id factory.db does not hold."""
        with self._connection() as con:
            row = con.execute("SELECT step FROM attempt WHERE attempt_id=?", (attempt_id,)).fetchone()
        return None if row is None else as_text(row[0])

    def tracker_root(self, key: AttemptKey) -> str | None:
        """The absolute tracker root the attempt's claim was taken at (stored by admission, copied by a repeat)."""
        with self._connection() as con:
            row = con.execute(
                "SELECT tracker_root FROM attempt WHERE attempt_id=? AND dispatch_token=? AND generation=?", astuple(key)
            ).fetchone()
        return None if row is None else as_text(row[0])

    def release_of(self, key: AttemptKey) -> attempt_reads.ReleaseRow | None:
        """The attempt's release, None while it holds (or never held) its reservation."""
        with self._connection() as con:
            row = con.execute(RELEASED + " WHERE attempt_id=? AND dispatch_token=? AND generation=?", astuple(key)).fetchone()
        return None if row is None else attempt_reads._released(row)

    def backlogs(self) -> tuple[str, ...]:
        """Distinct retained backlog identities, including ended attempts, in key order; SELECT only."""
        with self._connection() as con:
            rows: list[tuple[object, ...]] = con.execute(
                "SELECT DISTINCT backlog FROM attempt WHERE adapter='beads' ORDER BY backlog"
            ).fetchall()
        return tuple(as_text(row[0]) for row in rows)

    def current_attempts(self) -> tuple[attempt_reads.AttemptRow, ...]:
        """Select current rows and whole-task step counts in one SQLite snapshot before external status reads."""
        return self._attempts(None, None, latest=True)

    def attempts(self, backlog: str | None = None, task_id: str | None = None) -> tuple[attempt_reads.AttemptRow, ...]:
        return self._attempts(backlog, task_id, latest=False)

    def _attempts(self, backlog: str | None, task_id: str | None, *, latest: bool) -> tuple[attempt_reads.AttemptRow, ...]:
        """Every attempt (or one backlog's, or one task's), by backlog, task and `seq`, the current attempt of each task
        first, with whether it still holds its reservation and its release: SELECT only, no deadline check."""
        predicates = ["p.adapter='beads'"]
        parameters: list[str] = []
        for column, value in (("backlog", backlog), ("task_id", task_id)):
            if value is not None:
                predicates.append(f"p.{column}=?")
                parameters.append(value)
        source = "attempt p"
        if latest:
            source += """ JOIN (SELECT adapter,backlog,task_id,max(seq) seq FROM attempt WHERE adapter='beads'
                GROUP BY adapter,backlog,task_id) latest ON latest.adapter=p.adapter AND latest.backlog=p.backlog
                AND latest.task_id=p.task_id AND latest.seq=p.seq"""
        count = ("(SELECT count(*) FROM attempt n WHERE n.adapter=p.adapter AND n.backlog=p.backlog "
                 "AND n.task_id=p.task_id AND n.step=p.step AND n.seq<=p.seq)") if latest else "NULL"
        with self._connection() as con:
            rows: list[tuple[object, ...]] = con.execute(
                f"""SELECT p.attempt_id,p.dispatch_token,p.generation,p.backlog,p.task_id,p.slot,p.phase,p.entry_pid,p.entry_start,
                p.entry_boot,p.deadline,p.worker_pid,p.worker_pgid,p.number,p.previous_attempt_id,p.repeat_reason,
                {REPEATED},p.seq,
                EXISTS (SELECT 1 FROM reservation r WHERE r.repo_id=p.repo_id AND r.slot=p.slot AND r.attempt_id=p.attempt_id
                 AND r.generation=p.generation),x.head,x.released_at,x.claim,b.commit_sha,b.remote_head,b.published_at,p.step,
                p.label,p.end_commit,p.repeat_listing,
                p.harness,p.provider,p.model,p.effort,p.access_policy,p.source_checks_id,{count},p.repo_id,p.compaction_token_limit
                FROM {source}
                LEFT JOIN slot_release x ON x.attempt_id=p.attempt_id
                LEFT JOIN published_branch b ON b.attempt_id=p.attempt_id
                WHERE {' AND '.join(predicates)}
                ORDER BY p.backlog,p.task_id,p.seq DESC""",
                parameters,
            ).fetchall()
        return tuple(attempt_reads.attempt_row(row) for row in rows)

    def slot_path(self, attempt_id: str) -> str | None:
        """Where the adopted slot of an agent attempt or of a checks attempt is (the `slot` row's path); None for an
        attempt id factory.db does not hold."""
        with self._connection() as con:
            row = con.execute(
                """SELECT s.path FROM attempt p JOIN slot s ON s.repo_id=p.repo_id AND s.name=p.slot WHERE p.attempt_id=?1
                UNION ALL SELECT s.path FROM checks_attempt c JOIN attempt p ON p.attempt_id=c.after_attempt_id
                JOIN slot s ON s.repo_id=p.repo_id AND s.name=c.slot WHERE c.attempt_id=?1 LIMIT 1""", (attempt_id,)).fetchone()
        return None if row is None else as_text(row[0])

    def slot_use(self) -> attempt_reads.SlotUse:
        """Two SELECTs, no write: the free-slot read and the slot-released check both use them."""
        with self._connection() as con:
            free = con.execute(
                """SELECT count(*) FROM slot s
                WHERE NOT EXISTS (SELECT 1 FROM reservation r WHERE r.repo_id=s.repo_id AND r.slot=s.name)"""
            ).fetchone()
            rows: list[tuple[object, ...]] = con.execute("SELECT repo_id,slot FROM reservation").fetchall()
        held = frozenset((as_text(row[0]), as_text(row[1])) for row in rows)
        return attempt_reads.SlotUse(as_int(free[0]), held)

    def slot_names(self) -> tuple[str, ...]:
        """Every adopted slot's name across repos (`s1`, `s2`, ... in number order); SELECT only."""
        with self._connection() as con:
            rows: list[tuple[object, ...]] = con.execute("SELECT DISTINCT name FROM slot").fetchall()
        return tuple(sorted((as_text(row[0]) for row in rows), key=lambda name: (len(name), name)))

    def chain(self, key: AttemptKey) -> tuple[ChainLink, ...]:
        """Attempts 1..n of the key's dispatched step, oldest first, skipping rejected answers replaced by repairs (at most
        ATTEMPTS): the earlier ones are frozen once their successor exists. No reservation check; an absent key, an
        undispatched attempt or a broken chain is StoreUnavailable."""
        found: list[tuple[object, ...]] = []
        with self._connection() as con:
            row: tuple[object, ...] | None = con.execute(
                STEP + " WHERE p.attempt_id=? AND p.dispatch_token=? AND p.generation=?", astuple(key)
            ).fetchone()
            while row is not None and len(found) < ATTEMPTS:
                found.append(row)
                row = None if row[7] is None else con.execute(STEP + " WHERE p.attempt_id=?", (row[7],)).fetchone()
        steps = tuple(attempt_reads._step(each) for each in reversed(found))
        if not steps or [step.number for step in steps] != list(range(1, len(steps) + 1)):
            raise StoreUnavailable("Malformed step chain")
        return steps

    def input_ref(self, key: AttemptKey) -> FileRef:
        """Immutable input reference, including admitted attempts with no execution or registered entry."""
        with self._connection() as con:
            row = con.execute("SELECT input_path,input_digest FROM attempt WHERE attempt_id=? AND dispatch_token=? AND generation=?",
                              astuple(key)).fetchone()
        if row is None:
            raise StoreUnavailable("Attempt input reference unavailable")
        return FileRef(as_text(row[0]), as_text(row[1]))

    def previous_abandoned(self, key: AttemptKey) -> bool:
        """Distinguish fresh admission after abandonment from ordinary step advancement, across restarts."""
        with self._connection() as con:
            row = con.execute(
                "SELECT q.attempt_id,q.dispatch_token,q.generation FROM attempt p JOIN attempt q "
                "ON q.repo_id=p.repo_id AND q.adapter=p.adapter "
                "AND q.backlog=p.backlog AND q.task_id=p.task_id AND q.tracker_root=p.tracker_root AND q.seq<p.seq "
                "WHERE p.attempt_id=? AND p.dispatch_token=? AND p.generation=? "
                "ORDER BY q.seq DESC LIMIT 1", astuple(key),
            ).fetchone()
        released = None if row is None else self.release_of(AttemptKey(as_text(row[0]), as_text(row[1]), as_int(row[2])))
        return released is not None and released.abandoned


class AttemptStore(AttemptLoads, AttemptReads):
    """The fenced writes of an admitted attempt; the reads they need are `AttemptLoads`', the status reads `AttemptReads`'."""

    @staticmethod
    def repair_session(con: sqlite3.Connection, key: AttemptKey, session: str) -> None:
        """Seed the repair's already validated session inside its admission transaction, before entry registration."""
        changed = con.execute(
            "UPDATE attempt SET session_ref=? WHERE attempt_id=? AND dispatch_token=? AND generation=? "
            "AND phase='admitted' AND session_ref IS NULL AND repair_context IS NOT NULL", (session, *astuple(key)),
        ).rowcount
        if changed != 1:
            raise StoreRefused("changed_admission")

    def replace_worker(self, con: sqlite3.Connection, current: AttemptRecord, intent: Intent, worker: Identity) -> int:
        """Only the recovery transaction calls this; admission and original session remain frozen."""
        previous = current.worker
        if (previous is None or current.revision != intent.attempt_revision
                or (previous.pid, previous.pgid, previous.start, previous.boot)
                != (intent.worker.pid, intent.worker.pgid, intent.worker.start, intent.worker.boot)):
            raise StoreRefused("worker_mismatch")
        con.execute("UPDATE attempt SET worker_pid=?,worker_pgid=?,worker_start=?,worker_boot=?,rev=rev+1 WHERE attempt_id=? AND rev=?",
                    (worker.pid, worker.pgid, worker.start, worker.boot, intent.key.attempt_id, current.revision))
        return current.revision + 1

    def renew(self, con: sqlite3.Connection, current: AttemptRecord, deadline: float) -> AttemptRecord:
        """Only recovery calls this, after proof and snapshot comparison under the same writer lock."""
        if current.admission.repair is not None:
            return current
        admission = replace(current.admission, deadline=max(current.admission.deadline, deadline))
        changed = con.execute(
            "UPDATE attempt SET deadline=?,rev=rev+1 WHERE attempt_id=? AND dispatch_token=? AND generation=? AND rev=?",
            (admission.deadline, *astuple(admission.key), current.revision),
        ).rowcount
        if changed != 1:
            raise StoreRefused("changed_admission")
        return replace(current, admission=admission, revision=current.revision + 1)

    def recovery(
        self, con: sqlite3.Connection, key: AttemptKey, now: float, *, allow_expired: bool = False,
    ) -> AttemptRecord | Result:
        """Read eligibility inside the recovery store's transaction; no attempt facts are changed."""
        row = con.execute(
            f"""SELECT {SUCCESSOR},EXISTS(SELECT 1 FROM slot_release r WHERE r.attempt_id=p.attempt_id),
            EXISTS(SELECT 1 FROM execution e WHERE e.attempt_id=p.attempt_id)
            FROM attempt p WHERE p.attempt_id=? AND p.dispatch_token=? AND p.generation=?""", astuple(key),
        ).fetchone()
        if row is None or row[0] or row[1]:
            return Result(outcome=Outcome.INELIGIBLE, explanation="The attempt is missing, superseded or released.")
        if row[2]:
            return Result(outcome=Outcome.CAPTURED, explanation="The saved execution requires collection, not another agent.")
        try:
            record = self._load(con, key)
        except StoreRefused as error:
            outcome = Outcome.UNRESOLVED if str(error) == "unregistered_entry" else Outcome.INELIGIBLE
            return Result(outcome=outcome, explanation=f"The attempt cannot be recovered: {error}.")
        if record is None:
            return Result(outcome=Outcome.INELIGIBLE, explanation="The attempt is absent.")
        return self._recovery_session(con, record, now, allow_expired=allow_expired)

    def _recovery_session(
        self, con: sqlite3.Connection, record: AttemptRecord, now: float, *, allow_expired: bool = False,
    ) -> AttemptRecord | Result:
        if (not math.isfinite(now) or not math.isfinite(record.admission.deadline)
                or ((not allow_expired or record.admission.repair is not None) and now >= record.admission.deadline)):
            return Result(outcome=Outcome.EXPIRED, explanation="The attempt's existing allowance has expired.")
        if record.phase != "registered" or record.worker is None:
            return Result(outcome=Outcome.UNRESOLVED, explanation="Complete entry and worker registration is required for stop proof.")
        if not record.session_ref or record.session_conflict:
            return Result(outcome=Outcome.INELIGIBLE, explanation="The attempt has no consistent saved session.")
        other = con.execute(
            f"""SELECT 1 FROM attempt p WHERE p.session_ref=? AND p.harness=? AND p.attempt_id<>?
            AND NOT {SUCCESSOR} AND NOT EXISTS(SELECT 1 FROM slot_release r WHERE r.attempt_id=p.attempt_id)""",
            (record.session_ref, record.admission.setting.harness.value, record.admission.key.attempt_id),
        ).fetchone()
        if other is not None:
            return Result(outcome=Outcome.INELIGIBLE, explanation="Another current attempt owns the saved session in this harness.")
        return record

    def register_entry(
        self, key: AttemptKey, entry: EntryIdentity, now: float, replacing: Replaced | None = None,
        renewed: float | None = None,
    ) -> Literal["accepted", "conflict", "refused"]:
        """The only writer of entry_*: one winner while `admitted`; a replacement names the exact stored identity.

        Refused when the key, the held reservation or the deadline does not match. `_load` cannot serve this read: it
        refuses exactly the unregistered row. A replacement of a stored entry from another boot than the registering
        one also renews the deadline in the same write, past or not, to the later of the stored one and `renewed` (at
        most once per reboot: the new entry is this boot's); a renewed deadline that is not finite or not after `now`
        is refused and writes nothing. A same-boot replacement or a first registration never renews.
        """
        with self._connection(write=True) as con:
            if blocked(con) and not any(action.kind is ActionKind.DISPATCH and action.subject == key.attempt_id
                                        for action in pending(con)):
                return "refused"
            row: tuple[object, ...] | None = con.execute(
                """SELECT p.phase,p.deadline,p.entry_pid,p.entry_start,p.entry_boot,p.repair_context FROM attempt p
                JOIN reservation r ON r.slot=p.slot AND r.repo_id=p.repo_id AND r.generation=p.generation AND r.attempt_id=p.attempt_id
                WHERE p.attempt_id=? AND p.dispatch_token=? AND p.generation=?""",
                astuple(key),
            ).fetchone()
            if row is None or not isinstance(deadline := row[1], (int, float)):
                return "refused"
            stored = None if None in row[2:5] else (as_int(row[2]), as_text(row[3]), as_text(row[4]))
            if renewed is not None and stored is not None and stored[2] != entry[2] and row[5] is None:
                deadline = max(deadline, renewed) if math.isfinite(renewed) else now
            if now >= deadline:
                return "refused"
            if row[0] != "admitted":
                return "conflict"
            if entry == stored or stored != (None if replacing is None else replacing.identity):
                return "conflict"  # replacing an identity with itself would only bump rev under a live dispatch read
            # the row was read in this same immediate transaction, so no revision predicate is needed
            con.execute(
                "UPDATE attempt SET entry_pid=?,entry_start=?,entry_boot=?,deadline=?,rev=rev+1 WHERE attempt_id=?",
                (*entry, deadline, key.attempt_id),
            )
            return "accepted"

    def dispatch(self, expected: AttemptRecord, base: str) -> Literal["accepted", "conflict"]:
        """`base` is the slot HEAD read just before this write; it is recorded once, with the phase change."""
        with self._connection(write=True) as con:
            current = self._fence(con, expected.admission)
            if current.phase != "admitted" or current.revision != expected.revision:
                return "conflict"
            con.execute(
                "UPDATE attempt SET phase='dispatching',base_commit=?,rev=rev+1 WHERE attempt_id=? AND rev=?",
                (base, expected.admission.key.attempt_id, expected.revision),
            )
            return "accepted"

    def register(self, admission: Admission, worker: Worker) -> Literal["accepted", "already_same", "conflict"]:
        with self._connection(write=True) as con:
            fence(con, admission.key, None)
            current = self._fence(con, admission)
            if current.worker is not None:
                return "already_same" if current.worker == worker else "conflict"
            if current.phase != "dispatching":
                return "conflict"
            con.execute(
                """UPDATE attempt SET phase='registered',worker_pid=?,worker_pgid=?,worker_start=?,worker_boot=?,rev=rev+1
                WHERE attempt_id=? AND rev=?""",
                (worker.pid, worker.pgid, worker.start, worker.boot, admission.key.attempt_id, current.revision),
            )
            return "accepted"

    def session(self, admission: Admission, ref: str, callback: Callback | None = None) -> Literal["accepted", "already_same", "conflict"]:
        with self._connection(write=True) as con:
            current = self._owned(con, admission, callback)
            if current.worker is None:
                raise StoreRefused("unregistered_worker")
            if current.session_ref == ref:
                return "already_same"
            if current.session_ref is not None:
                con.execute("UPDATE attempt SET session_conflict=1,rev=rev+1 WHERE attempt_id=?", (admission.key.attempt_id,))
                con.execute("UPDATE execution SET session_state='conflict' WHERE attempt_id=?", (admission.key.attempt_id,))
                return "conflict"
            con.execute("UPDATE attempt SET session_ref=?,rev=rev+1 WHERE attempt_id=?", (ref, admission.key.attempt_id))
            return "accepted"

    def capture(
        self,
        admission: Admission,
        worker: Worker | None,
        facts: ExecutionFacts,
        evidence: Evidence,
        session_state: Literal["complete", "pending", "conflict", "fault"],
        callback: Callback | None = None,
    ) -> Literal["accepted", "already_same", "conflict"]:
        with self._connection(write=True) as con:
            current = self._owned(con, admission, callback)
            if current.worker is None or (worker is not None and current.worker != worker):
                raise StoreRefused("worker_mismatch")
            if current.session_conflict:
                session_state = "conflict"  # a recorded differing session is never stored as complete
            old = self._execution(con, admission.key)
            if old is not None:
                if old.facts != facts or old.evidence != evidence or self._callback(con, admission.key) != callback:
                    return "conflict"
                if old.session_state in ("pending", "fault") and session_state in ("complete", "conflict"):
                    con.execute(
                        "UPDATE execution SET session_state=? WHERE attempt_id=? AND session_state IN ('pending','fault')",
                        (session_state, admission.key.attempt_id),
                    )
                    return "accepted"
                return "already_same"
            if current.phase != "registered":
                return "conflict"
            refs = tuple(value for ref in astuple(evidence) for value in ref)
            values = (*astuple(admission.key), *attempt_reads._facts_values(facts), *refs, session_state,
                      None if callback is None else callback.model_dump_json())
            marks = ",".join("?" * len(values))
            con.execute(
                f"INSERT INTO execution (attempt_id,dispatch_token,generation,{FACTS},{EVIDENCE},session_state,recovery_callback) "
                f"VALUES ({marks})", values
            )
            con.execute("UPDATE attempt SET phase='captured',rev=rev+1 WHERE attempt_id=?", (admission.key.attempt_id,))
            return "accepted"

    def answer(
        self, admission: Admission, evidence: Evidence, answer: AnswerState, callback: Callback | None = None,
    ) -> Literal["accepted", "already_same", "conflict"]:
        with self._connection(write=True) as con:
            self._owned(con, admission, callback)
            current = self._execution(con, admission.key)
            if current is None or current.evidence != evidence or self._callback(con, admission.key) != callback:
                return "conflict"
            if current.answer.kind != "validation_pending":
                return "already_same" if current.answer == answer else "conflict"
            paths = json.dumps(list(answer.paths)) if answer.kind == "valid" else None
            failure = answer_failures.encode(answer_failures.validate(answer.failure, answer.kind))
            con.execute(
                "UPDATE execution SET answer_kind=?,disposition=?,effect=?,commit_paths=?,commit_message=?,answer_failure=? "
                "WHERE attempt_id=?",
                (answer.kind, answer.disposition, answer.effect, paths, answer.message, failure, admission.key.attempt_id),
            )
            return "accepted"

    def end_commit(self, admission: Admission, commit: str) -> str:
        """Write once the commit the step ends at: X != B for effect `commit`, B itself for `keep` (over saved work: the step's own
        commit of that tree), only for a captured,
        clean valid answer with its session complete, with no verdict stored yet (a `nothing_written` verdict has no commit and
        is never contradicted afterwards). Returns the value now stored: another one than `commit` is the caller's
        `inconsistent`; a refused registration write is StoreRefused."""
        with self._connection(write=True) as con:
            self._fence(con, admission)
            con.execute(
                """UPDATE attempt SET end_commit=?1,rev=rev+1 WHERE attempt_id=?2 AND end_commit IS NULL AND phase='captured'
                AND EXISTS (SELECT 1 FROM execution e WHERE e.attempt_id=?2 AND e.answer_kind='valid' AND e.rc=0
                AND e.timed_out=0 AND e.session_state='complete' AND ((e.effect='commit' AND ?1<>attempt.base_commit)
                OR e.effect='keep'))
                AND NOT EXISTS (SELECT 1 FROM verification v WHERE v.attempt_id=?2)""",
                (commit, admission.key.attempt_id),
            )
            row = con.execute("SELECT end_commit FROM attempt WHERE attempt_id=?", (admission.key.attempt_id,)).fetchone()
        stored = None if row is None else as_nullable_text(row[0])
        if stored is None:
            raise StoreRefused("changed_answer")
        return stored

    def verdict(self, admission: Admission, base: str, commit: str | None, result: Verdict, now: float) -> Verdict:
        """Insert-only: written while the reservation is held, the run was clean, its session state complete, the
        stored valid answer's effect `commit` or `keep`, its base B and its stored `end_commit` exactly the verified ones;
        `nothing_written` alone has no commit (effect `commit`, `end_commit` NULL) and `reused` needs `keep`. An
        existing row is kept, never rewritten. Returns the row now stored."""
        values = attempt_reads._verdict_values(result)
        with self._connection(write=True) as con:
            self._fence(con, admission)
            con.execute(
                f"""INSERT INTO verification (attempt_id,dispatch_token,generation,{VERDICT},observed_at)
                SELECT ?,?,?,?,?,?,?,? FROM execution e JOIN attempt p ON p.attempt_id=e.attempt_id
                WHERE e.attempt_id=? AND e.dispatch_token=? AND e.generation=? AND e.answer_kind='valid'
                AND e.effect IN ('commit','keep') AND e.rc=0 AND e.timed_out=0 AND e.session_state='complete'
                AND p.base_commit=? AND CASE WHEN ?='nothing_written' THEN p.end_commit IS NULL AND e.effect='commit'
                ELSE p.end_commit=? END AND (?=0 OR e.effect='keep')
                ON CONFLICT DO NOTHING""",
                (*astuple(admission.key), *values, now, *astuple(admission.key), base, values[1], commit, values[3]),
            )
            row: tuple[object, ...] | None = con.execute(
                f"SELECT {VERDICT} FROM verification WHERE attempt_id=? AND dispatch_token=? AND generation=?", astuple(admission.key)
            ).fetchone()
        stored = None if row is None else verdict_of(row)
        if stored is None:
            raise StoreRefused("changed_answer")
        return stored
