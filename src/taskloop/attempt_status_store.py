"""SQL owner for attempt status, listing and chains."""

from dataclasses import astuple

from taskloop import attempt_reads
from taskloop.attempt_reads import StoreConnection, StoreUnavailable, as_int, as_text
from taskloop.attempt_types import ATTEMPTS, AttemptKey, ChainLink, EntryIdentity, FileRef
from taskloop.drain.models import Identity, Owner, Role, owners
from taskloop.factory_schema import REPEATED

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
