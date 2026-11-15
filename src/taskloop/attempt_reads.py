"""The attempt store's connection boundary, status models and SQL-free codecs."""

import json
import sqlite3
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass

from sqlite_store import begin_immediate

from taskloop.agents.settings import AgentSetting, decode_setting
from taskloop.attempt_types import EFFECTS, AttemptKey, ChainLink, Effect, EntryIdentity, ExecutionFacts, FileRef, Verdict, Verified
from taskloop.check_repeat.feedback import stored_source
from taskloop.factory_store import current


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
    later attempt of the step names this one (a repeat or answer repair fences and supersedes it)."""

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

    def warm(self) -> None:
        """Open (and on first use check) this store's connection now; StoreUnavailable when it cannot."""
        with self._connection():
            pass

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


def attempt_row(row: tuple[object, ...]) -> AttemptRow:
    """Decode one status/listing projection, including its optional release and publication."""
    entry = None if any(value is None for value in row[7:10]) else (as_int(row[7]), as_text(row[8]), as_text(row[9]))
    if not isinstance(row[10], (int, float)):
        raise StoreUnavailable("Malformed deadline")
    key = AttemptKey(as_text(row[0]), as_text(row[1]), as_int(row[2]))
    worker = None if row[11] is None or row[12] is None else (as_int(row[11]), as_int(row[12]))
    return AttemptRow(
        key, as_text(row[3]), as_text(row[4]), as_text(row[5]), as_text(row[6]), entry, float(row[10]), worker,
        as_int(row[13]), as_nullable_text(row[14]), as_nullable_text(row[15]), bool(as_int(row[16])), as_text(row[25]),
        as_int(row[17]), bool(as_int(row[18])), _released(row[19:22]), _published(row[22:25]),
        as_nullable_text(row[26]), as_nullable_text(row[27]), as_listed(row[28]), _source(row[34], row[15]),
        stored_setting(row[29], row[30], row[31], row[32], row[33], row[37]), as_nullable_int(row[35]), as_text(row[36]),
    )


def _facts_values(facts: ExecutionFacts) -> tuple[object, ...]:
    return (
        facts.rc,
        facts.timed_out,
        facts.stop,
        facts.watch,
        facts.work,
        facts.stands,
        facts.answered,
        facts.reason,
        facts.http_status,
        *(facts.tokens or (None, None, None)),  # unknown counts stay NULL, never 0
        *(facts.cumulative or (None, None, None)),
        facts.turns,
        facts.session,
        facts.usage_incomplete,
    )


def _verdict_values(result: Verdict) -> tuple[str, str | None, str | None, int]:
    if isinstance(result, Verified):
        return "verified", None, result.blob, int(result.reused)
    return "rejected", str(result.reason), None, 0


def _source(value: object, reason: object) -> str | None:
    try:
        return stored_source(value, reason)
    except ValueError as error:
        raise StoreUnavailable("Malformed check-repeat source") from error
