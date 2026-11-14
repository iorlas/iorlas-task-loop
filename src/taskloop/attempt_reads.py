"""The attempt store's connection and its status reads (SELECT only, no reservation or deadline check): a task's current
attempt (its highest `seq`), every attempt (with its release and its published task branch), a dispatch phase, an
attempt's tracker root, its release, the attempts of one step, and the slots' use. `AttemptStore` adds the fenced writes."""

import json
import sqlite3
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import astuple, dataclass

from sqlite_store import begin_immediate

from taskloop.agents.settings import AgentSetting, decode_setting
from taskloop.attempt_types import ATTEMPTS, EFFECTS, AttemptKey, ChainLink, Effect, EntryIdentity, FileRef
from taskloop.check_repeat.feedback import stored_source
from taskloop.drain.models import Identity, Owner, Role, owners
from taskloop.factory_schema import REPEATED, current


@dataclass(frozen=True)
class ReleaseRow:
    """How an attempt ended its reservation (`slot_release`): where the slot was left, when, whether it was abandoned
    (the task can be started again) and the tracker claim's state."""

    head: str
    released_at: float
    claim: str
    checks_abandoned: bool = False  # a checks attempt's own abandon flag: its claim is its implement attempt's, still kept

    @property
    def abandoned(self) -> bool:
        """An abandon never keeps the claim; a settled release always does. A checks attempt's abandon keeps it (the
        implement attempt's abandon, which follows, returns it)."""
        return self.claim != "kept" or self.checks_abandoned


@dataclass(frozen=True)
class PublishedRow:
    """The attempt's verified commit on origin's `task/<id>` (`published_branch`): X pushed, the remote tip confirmed (X,
    or a later commit that contains X), and when."""

    commit: str
    remote_head: str
    published_at: float


type RunChoices = AgentSetting


@dataclass(frozen=True)
class AttemptRow:
    """One attempt as the status reads see it; the key is for further reads only, never for display. `successor`: a
    later attempt of the step names this one (it was repeated, so it is fenced and superseded)."""

    key: AttemptKey
    backlog: str
    task_id: str
    slot: str
    phase: str
    entry: EntryIdentity | None
    deadline: float
    worker: tuple[int, int] | None  # the agent's pid and process group, once registered
    number: int
    previous_attempt_id: str | None
    repeat_reason: str | None
    successor: bool
    step: str  # the step the attempt belongs to (`plan`)
    seq: int = 1  # the attempt's order among its task's attempts
    held: bool = False  # it still holds its reservation
    release: ReleaseRow | None = None
    published: PublishedRow | None = None
    label: str | None = None  # the approval label a round took the task under (`attempt.label`); None: started by hand
    end_commit: str | None = None  # X, once stored
    repeat_listing: tuple[str, ...] = ()  # a repeat's: what the verification that led to it listed
    source_checks_id: str | None = None
    run: RunChoices | None = None  # the agent's harness, provider, model, effort and sandbox as admitted
    try_number: int | None = None  # whole-task step count, captured with current selection
    repo_id: str = ""


@dataclass(frozen=True)
class SlotUse:
    """Every adopted slot of factory.db against the reservation rows, across repos: `free`, the adopted slots with no
    reservation row (not proof a slot is free: it may be dirty or locked); `held`, each reserved (repo_id, slot), every
    backlog's: a repeat's takeover rewrites the row's attempt but keeps the slot reserved. The release (`slot_release`)
    is the one owner of a row's removal."""

    free: int
    held: frozenset[tuple[str, str]]


class StoreUnavailable(Exception):
    """No progress was acknowledged by the store."""


class StoreRefused(Exception):
    """The authoritative admission or reservation fence does not match."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def as_text(value: object) -> str:
    if isinstance(value, str):
        return value
    raise StoreUnavailable("Malformed stored text")


def stored_setting(harness: object, provider: object, model: object, effort: object, policy: object,
                   compaction_token_limit: object) -> AgentSetting:
    try:
        return decode_setting(as_text(harness), as_text(provider), as_text(model), as_text(effort), as_text(policy),
                              as_nullable_int(compaction_token_limit))
    except ValueError as error:
        raise StoreUnavailable("Malformed stored agent setting") from error


def as_int(value: object) -> int:
    if isinstance(value, int):
        return value
    raise StoreUnavailable("Malformed stored integer")


def as_nullable_int(value: object) -> int | None:
    return None if value is None else as_int(value)


def as_nullable_text(value: object) -> str | None:
    return None if value is None else as_text(value)


def as_listed(value: object) -> tuple[str, ...]:
    """The stored `commit_paths` JSON array (NULL for an answer that is not valid)."""
    if value is None:
        return ()
    try:
        paths = json.loads(as_text(value))
    except ValueError as error:
        raise StoreUnavailable("Malformed stored paths") from error
    if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
        raise StoreUnavailable("Malformed stored paths")
    return tuple(str(path) for path in paths)


def stored_effect(value: object) -> Effect | None:
    """A stored answer effect, NULL for no valid answer; any other value is a broken row."""
    effect = next((effect for effect in EFFECTS if effect == value), None)
    if (effect is None) != (value is None):
        raise StoreUnavailable("Invalid stored effect")
    return effect


STEP = """SELECT p.number,p.base_commit,p.end_commit,p.input_path,p.input_digest,e.effect,e.commit_paths,p.previous_attempt_id
FROM attempt p LEFT JOIN execution e ON e.attempt_id=p.attempt_id"""


RELEASED = "SELECT head,released_at,claim FROM slot_release"


def _released(row: tuple[object, ...]) -> ReleaseRow | None:
    """A release row (head, released_at, claim), None for the all-NULL row of a LEFT JOIN without one."""
    if row[0] is None:
        return None
    if not isinstance(row[1], (int, float)):
        raise StoreUnavailable("Malformed release time")
    return ReleaseRow(as_text(row[0]), float(row[1]), as_text(row[2]))


def _published(row: tuple[object, ...]) -> PublishedRow | None:
    """A published row (commit_sha, remote_head, published_at), None for the all-NULL row of a LEFT JOIN without one."""
    if row[0] is None:
        return None
    if not isinstance(row[2], (int, float)):
        raise StoreUnavailable("Malformed publication time")
    return PublishedRow(as_text(row[0]), as_text(row[1]), float(row[2]))


def _step(row: tuple[object, ...]) -> ChainLink:
    """A dispatched attempt: its B is recorded (a broken chain otherwise)."""
    base, commit = as_text(row[1]), as_nullable_text(row[2])
    return ChainLink(as_int(row[0]), base, commit, stored_effect(row[5]), as_listed(row[6]), FileRef(as_text(row[3]), as_text(row[4])))


class StoreConnection:
    """factory.db's connection for one store: the current schema checked on every use, a write in `begin`'s transaction,
    and any sqlite3 error reported as StoreUnavailable. No query of its own: each store adds the reads of its own tables."""

    def __init__(
        self,
        connect: Callable[[], sqlite3.Connection | None],
        begin: Callable[[sqlite3.Connection], AbstractContextManager[None]] = begin_immediate,
    ) -> None:
        """`begin` is the writer transaction; a composition on a Store passes its begin_immediate, which evicts a failed shared writer."""
        self.connect, self.begin = connect, begin

    @contextmanager
    def _connection(self, *, write: bool = False) -> Generator[sqlite3.Connection]:
        try:
            con = self.connect()
            if con is None or not current(con):
                raise StoreUnavailable("Factory database unavailable or incompatible")
            if write:
                with self.begin(con):
                    yield con
            else:
                yield con
        except (sqlite3.Error, ValueError) as error:
            raise StoreUnavailable("Factory database operation failed") from error


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

    def release_of(self, key: AttemptKey) -> ReleaseRow | None:
        """The attempt's release, None while it holds (or never held) its reservation."""
        with self._connection() as con:
            row = con.execute(RELEASED + " WHERE attempt_id=? AND dispatch_token=? AND generation=?", astuple(key)).fetchone()
        return None if row is None else _released(row)

    def backlogs(self) -> tuple[str, ...]:
        """Distinct retained backlog identities, including ended attempts, in key order; SELECT only."""
        with self._connection() as con:
            rows: list[tuple[object, ...]] = con.execute(
                "SELECT DISTINCT backlog FROM attempt WHERE adapter='beads' ORDER BY backlog"
            ).fetchall()
        return tuple(as_text(row[0]) for row in rows)

    def current_attempts(self) -> tuple[AttemptRow, ...]:
        """Select current rows and whole-task step counts in one SQLite snapshot before external status reads."""
        return self._attempts(None, None, latest=True)

    def attempts(self, backlog: str | None = None, task_id: str | None = None) -> tuple[AttemptRow, ...]:
        return self._attempts(backlog, task_id, latest=False)

    def _attempts(self, backlog: str | None, task_id: str | None, *, latest: bool) -> tuple[AttemptRow, ...]:
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
        found: list[AttemptRow] = []
        for row in rows:
            entry = None if any(value is None for value in row[7:10]) else (as_int(row[7]), as_text(row[8]), as_text(row[9]))
            if not isinstance(row[10], (int, float)):
                raise StoreUnavailable("Malformed deadline")
            key = AttemptKey(as_text(row[0]), as_text(row[1]), as_int(row[2]))
            worker = None if row[11] is None or row[12] is None else (as_int(row[11]), as_int(row[12]))
            found.append(
                AttemptRow(key, as_text(row[3]), as_text(row[4]), as_text(row[5]), as_text(row[6]), entry, float(row[10]), worker,
                           as_int(row[13]), as_nullable_text(row[14]), as_nullable_text(row[15]), bool(as_int(row[16])), as_text(row[25]),
                           as_int(row[17]), bool(as_int(row[18])), _released(row[19:22]), _published(row[22:25]),
                           as_nullable_text(row[26]), as_nullable_text(row[27]), as_listed(row[28]), _source(row[34], row[15]),
                           stored_setting(row[29], row[30], row[31], row[32], row[33], row[37]),
                           as_nullable_int(row[35]), as_text(row[36]))
            )
        return tuple(found)

    def slot_path(self, attempt_id: str) -> str | None:
        """Where the adopted slot of an agent attempt or of a checks attempt is (the `slot` row's path); None for an
        attempt id factory.db does not hold."""
        with self._connection() as con:
            row = con.execute(
                """SELECT s.path FROM attempt p JOIN slot s ON s.repo_id=p.repo_id AND s.name=p.slot WHERE p.attempt_id=?1
                UNION ALL SELECT s.path FROM checks_attempt c JOIN attempt p ON p.attempt_id=c.after_attempt_id
                JOIN slot s ON s.repo_id=p.repo_id AND s.name=c.slot WHERE c.attempt_id=?1 LIMIT 1""", (attempt_id,)).fetchone()
        return None if row is None else as_text(row[0])

    def slot_use(self) -> SlotUse:
        """Two SELECTs, no write: the free-slot read and the slot-released check both use them."""
        with self._connection() as con:
            free = con.execute(
                """SELECT count(*) FROM slot s
                WHERE NOT EXISTS (SELECT 1 FROM reservation r WHERE r.repo_id=s.repo_id AND r.slot=s.name)"""
            ).fetchone()
            rows: list[tuple[object, ...]] = con.execute("SELECT repo_id,slot FROM reservation").fetchall()
        held = frozenset((as_text(row[0]), as_text(row[1])) for row in rows)
        return SlotUse(as_int(free[0]), held)

    def slot_names(self) -> tuple[str, ...]:
        """Every adopted slot's name across repos (`s1`, `s2`, ... in number order); SELECT only."""
        with self._connection() as con:
            rows: list[tuple[object, ...]] = con.execute("SELECT DISTINCT name FROM slot").fetchall()
        return tuple(sorted((as_text(row[0]) for row in rows), key=lambda name: (len(name), name)))

    def chain(self, key: AttemptKey) -> tuple[ChainLink, ...]:
        """Attempts 1..n of the key's dispatched step, oldest first, followed through `previous_attempt_id` (at most
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
        steps = tuple(_step(each) for each in reversed(found))
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


def _source(value: object, reason: object) -> str | None:
    try:
        return stored_source(value, reason)
    except ValueError as error:
        raise StoreUnavailable("Malformed check-repeat source") from error
