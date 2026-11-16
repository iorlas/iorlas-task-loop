"""Publication persistence: strict reads and the fenced record after a confirmed push."""

import sqlite3
from collections.abc import Callable
from dataclasses import astuple, dataclass
from enum import Enum, auto
from typing import Final

from pydantic import BaseModel, ConfigDict

from taskloop.attempt_reads import PublishedRow, StoreUnavailable, as_nullable_text, as_text
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey
from taskloop.factory_schema import LATER, PUBLISHED, marks
from taskloop.factory_store import current

ROW: Final = """SELECT p.task_id,p.repo_id,p.end_commit,s.path,v.verdict,v.reason,x.claim,b.commit_sha,b.remote_head,b.published_at
FROM attempt p LEFT JOIN factory_commit v ON v.attempt_id=p.attempt_id
LEFT JOIN slot_release x ON x.attempt_id=p.attempt_id LEFT JOIN published_branch b ON b.attempt_id=p.attempt_id
LEFT JOIN slot s ON s.repo_id=p.repo_id AND s.name=p.slot
WHERE p.attempt_id=? AND p.dispatch_token=? AND p.generation=?"""
# Inside the write transaction: still committed at X, not abandoned, still the task's current attempt.
FENCE: Final = """SELECT 1 FROM attempt p JOIN factory_commit v ON v.attempt_id=p.attempt_id
WHERE p.attempt_id=? AND p.dispatch_token=? AND p.generation=? AND v.verdict='committed' AND p.end_commit=?
AND NOT EXISTS (SELECT 1 FROM slot_release x WHERE x.attempt_id=p.attempt_id AND x.claim<>'kept')
AND NOT """ + LATER
ABANDONED: Final = "SELECT 1 FROM slot_release WHERE attempt_id=? AND claim<>'kept'"


class PublishRow(BaseModel):
    """The attempt's publication preconditions, decoded before any Git call."""

    model_config = ConfigDict(frozen=True, strict=True)

    task_id: str
    repo_id: str
    commit: str | None
    slot_path: str | None
    verdict: str | None
    reason: str | None
    abandoned: bool
    published: PublishedRow | None


class RecordOutcome(Enum):
    RECORDED = auto()
    ABANDONED = auto()
    CHANGED = auto()


def _already(values: tuple[object, ...]) -> PublishedRow:
    """A stored published row: (commit_sha, remote_head, published_at)."""
    if not isinstance(values[2], (int, float)):
        raise StoreUnavailable("Malformed publication time")
    return PublishedRow(as_text(values[0]), as_text(values[1]), float(values[2]))


def _row(row: tuple[object, ...]) -> PublishRow:
    published = None if row[7] is None else _already(row[7:10])
    abandoned = row[6] is not None and as_text(row[6]) != "kept"
    return PublishRow(task_id=as_text(row[0]), repo_id=as_text(row[1]), commit=as_nullable_text(row[2]),
                      slot_path=as_nullable_text(row[3]), verdict=as_nullable_text(row[4]), reason=as_nullable_text(row[5]),
                      abandoned=abandoned, published=published)


@dataclass(frozen=True)
class PublishStore:
    """Own publication SQL using the attempt store's injected connection and transaction providers."""

    store: AttemptStore

    def _connect(self) -> sqlite3.Connection:
        con = self.store.connect()
        if con is None or not current(con):
            raise StoreUnavailable("Factory database unavailable or incompatible")
        return con

    def read(self, key: AttemptKey) -> PublishRow | None:
        found: tuple[object, ...] | None = self._connect().execute(ROW, astuple(key)).fetchone()
        return None if found is None else _row(found)

    def record(self, key: AttemptKey, commit: str, clock: Callable[[], float]) -> PublishedRow | RecordOutcome:
        """After a push, record once if the attempt is still current and verified at the pushed commit."""
        con = self._connect()
        with self.store.begin(con):
            existing = con.execute("SELECT commit_sha,remote_head,published_at FROM published_branch WHERE attempt_id=?",
                                   (key.attempt_id,)).fetchone()
            if existing is not None:
                return _already(existing)
            if con.execute(FENCE, (*astuple(key), commit)).fetchone() is None:
                gone = con.execute(ABANDONED, (key.attempt_id,)).fetchone() is not None
                return RecordOutcome.ABANDONED if gone else RecordOutcome.CHANGED
            values = (*astuple(key), commit, commit, clock())
            con.execute(f"INSERT INTO published_branch ({PUBLISHED}) VALUES ({marks(PUBLISHED)})", values)
        return RecordOutcome.RECORDED
