"""The ownership records of the worktrees tl made, as `kv` rows in factory.db (key `worktree:<repo key>:<worktree key>`, the Owned in `v`).
A record says who made a worktree and is kept until the worktree is removed: evidence, not a lease. An older tl's
`worktrees/<repo>/<key>.json` is read while there is no row, and the next write moves it (dual-read, never dual-write)."""
import json
import time

from taskloop.contracts import wire
from taskloop.contracts.looprows import LoopRows
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.worktrees import Owned


class WorktreeDoc:
    def __init__(self, cfg: ConfigDir, repo_key: str, key: str) -> None:
        self.rows, self.k = LoopRows(cfg, ""), f"worktree:{repo_key}:{key}"

    def get(self) -> Owned | None:
        found = self.rows.select("SELECT v FROM kv WHERE k=?", (self.k,))
        if found:
            try:
                body = json.loads(found[0][0])
                return wire.load(Owned, {k: v for k, v in body.items() if k in wire.keys(Owned)})  # a newer writer's keys are read past
            except (ValueError, TypeError, AttributeError):
                return None
        return None

    def write(self, rec: Owned) -> None:
        with self.rows.transaction() as con:
            con.execute("INSERT INTO kv (k, v, t) VALUES (?, ?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v, t=excluded.t",
                        (self.k, json.dumps(wire.dump(rec), ensure_ascii=False), time.time()))

    def delete(self) -> None:
        with self.rows.transaction() as con:
            con.execute("DELETE FROM kv WHERE k=?", (self.k,))


class WorktreeDocs:
    """The records of one repo: `of(key)` one, `keys()` all (rows)."""

    def __init__(self, cfg: ConfigDir, repo_key: str) -> None:
        self.cfg, self.repo_key = cfg, repo_key

    def of(self, key: str) -> WorktreeDoc:
        return WorktreeDoc(self.cfg, self.repo_key, key)

    def keys(self) -> list[str]:
        prefix = f"worktree:{self.repo_key}:"
        rows = LoopRows(self.cfg, "").select("SELECT k FROM kv WHERE k >= ? AND k < ?", (prefix, prefix[:-1] + ";"))
        return sorted({r[0][len(prefix):] for r in rows})
