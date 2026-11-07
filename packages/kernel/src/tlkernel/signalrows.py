"""The owner's requests to a live run as `signal` rows in factory.db (kind `owner_request`, one row per post, the OwnerRequest it
adds in `payload`). `take` merges the run's untaken rows into one OwnerRequest and marks them taken, in one transaction, so a request
posted while the run takes is never lost or taken twice."""
import json

from tlkernel import wire
from tlkernel.looprows import LoopRows
from tlkernel.paths import ConfigDir
from tlkernel.requests import OwnerRequest

KIND = "owner_request"


def merge(parts: list[OwnerRequest]) -> OwnerRequest | None:
    if not parts:
        return None
    last = parts[-1]
    return OwnerRequest(park=any(p.park for p in parts), stop=any(p.stop for p in parts), notes=[n for p in parts for n in p.notes],
                        by=last.by, t=last.t)


class SignalRows:
    def __init__(self, cfg: ConfigDir, run: str, *, quiet: bool = False) -> None:
        self.cfg, self.run, self.rows = cfg, run, LoopRows(cfg, "", quiet=quiet)

    def post(self, req: OwnerRequest, now: float) -> None:
        with self.rows.transaction() as con:
            con.execute("INSERT INTO signal (run, kind, payload, at) VALUES (?, ?, ?, ?)",
                        (self.run, KIND, json.dumps(wire.dump(req), ensure_ascii=False), now))

    def parts(self, found: list[tuple[str, ...]]) -> list[OwnerRequest]:
        return [wire.load(OwnerRequest, json.loads(payload)) for _id, payload in found]

    def peek(self) -> OwnerRequest | None:
        return merge(self.parts(self.rows.select("SELECT id, payload FROM signal WHERE run=? AND kind=? AND taken IS NULL ORDER BY id",
                                                 (self.run, KIND))))

    def take(self, now: float) -> OwnerRequest | None:
        """The run's pending request, marked taken: each is acted on once."""
        with self.rows.transaction() as con:
            found = con.execute("SELECT id, payload FROM signal WHERE run=? AND kind=? AND taken IS NULL ORDER BY id",
                                (self.run, KIND)).fetchall()
            con.execute("UPDATE signal SET taken=? WHERE run=? AND kind=? AND taken IS NULL", (now, self.run, KIND))
        return merge(self.parts([tuple(r) for r in found]))

    def drop_all(self) -> None:
        """Forget the run's requests (its logs are pruned)."""
        if not self.cfg.factory_db().exists():
            return
        with self.rows.transaction() as con:
            con.execute("DELETE FROM signal WHERE run=? AND kind=?", (self.run, KIND))
