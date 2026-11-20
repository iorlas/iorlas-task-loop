"""The merge slice's durable intents and results; effects never run inside these transactions."""

from taskloop.attempt_reads import StoreConnection, StoreRefused, StoreUnavailable, as_text
from taskloop.drain.models import Owner, Role
from taskloop.merge.models import Work, decode, encode


def stored(data: object) -> Work:
    try:
        return decode(as_text(data))
    except ValueError as error:
        raise StoreUnavailable("Malformed stored merge operation") from error


class MergeStore(StoreConnection):
    def get(self, attempt_id: str) -> Work | None:
        with self._connection() as con:
            row = con.execute("SELECT data FROM merge_operation WHERE attempt_id=?", (attempt_id,)).fetchone()
        return None if row is None else stored(row[0])

    def start(self, work: Work) -> Work:
        with self._connection(write=True) as con:
            con.execute("INSERT INTO merge_operation (attempt_id,data) VALUES (?,?) ON CONFLICT DO NOTHING",
                        (work.attempt_id, encode(work)))
        found = self.get(work.attempt_id)
        if found is None:
            raise StoreRefused("merge_missing")
        return found

    def put(self, previous: Work, work: Work) -> Work:
        with self._connection(write=True) as con:
            changed = con.execute("UPDATE merge_operation SET data=? WHERE attempt_id=? AND data=?",
                                  (encode(work), work.attempt_id, encode(previous))).rowcount
        if changed != 1:
            raise StoreRefused("merge_changed")
        return work

    def active_processes(self) -> tuple[Owner, ...]:
        with self._connection() as con:
            rows = con.execute("SELECT data FROM merge_operation").fetchall()
        works = tuple(stored(row[0]) for row in rows)
        return tuple(Owner(subject=work.attempt_id, role=Role.AGENT, identity=execution.worker)
                     for work in works for execution in work.executions if execution.worker is not None and not execution.ended)
