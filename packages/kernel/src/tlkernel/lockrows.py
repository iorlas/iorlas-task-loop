"""A worktree's engine lock as one `lease` row (kind `run`, name `engine:<worktree key>`, the EngineLock in `body`, pid and start in the
columns) in factory.db. The take is still serialised by the kernel lock `ConfigDir.engine_take`; the row is the record. A row that does
not decode is Refused (never read as no lock)."""
import json

from tlkernel import wire
from tlkernel.ids import loop_key
from tlkernel.locks import EngineLock
from tlkernel.looprows import LoopRows
from tlkernel.paths import ConfigDir
from tlkernel.wire import Refused

KIND = "run"


class EngineLockRows:
    def __init__(self, cfg: ConfigDir, wt: object, *, quiet: bool = False) -> None:
        self.cfg, self.name, self.rows = cfg, f"engine:{loop_key(wt)}", LoopRows(cfg, "", quiet=quiet)

    def body(self) -> str | None:
        found = self.rows.select("SELECT body FROM lease WHERE kind=? AND name=?", (KIND, self.name))
        return found[0][0] if found else None

    def exists(self) -> bool:
        return self.body() is not None

    def need(self) -> EngineLock | None:
        text = self.body()
        if text is None:
            return None
        try:
            body = json.loads(text)
            return wire.load(EngineLock, body)
        except (ValueError, TypeError) as err:
            raise Refused(f"engine lock {self.name} in {self.cfg.factory_db()} is torn or of another version: {err}") from None

    def get(self) -> EngineLock | None:
        try:
            return self.need()
        except Refused:
            return None

    def write(self, rec: EngineLock) -> None:
        with self.rows.transaction() as con:
            con.execute("INSERT INTO lease (kind, name, holder, pid, start_id, since, body) VALUES (?, ?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT(kind, name) DO UPDATE SET holder=excluded.holder, pid=excluded.pid, start_id=excluded.start_id, "
                        "since=excluded.since, body=excluded.body",
                        (KIND, self.name, rec.by, rec.pid, rec.start, rec.started, json.dumps(wire.dump(rec), ensure_ascii=False)))

    def delete(self) -> None:
        with self.rows.transaction() as con:
            con.execute("DELETE FROM lease WHERE kind=? AND name=?", (KIND, self.name))
