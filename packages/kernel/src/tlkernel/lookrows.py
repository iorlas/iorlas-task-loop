"""The items of one owner-look bead as the `kv` row `look:<look bead>` of factory.db: a JSON list of gallery items. Two writers change
it (the engine filing new items, the owner's answer), so a write is a compare-and-set on the body that was read: the row changes only
if no one else wrote since, and a lost race re-reads and decides again. The bead's metadata is never written for items, so a hold or any
other key the owner set meanwhile is not overwritten. A look bead from before the row has its items in metadata `looks` (or its
description): the first write seeds the row from that."""
import json
import time
from collections.abc import Callable

from tlkernel.gallery import Item
from tlkernel.looprows import LoopRows
from tlkernel.paths import ConfigDir

PREFIX = "look:"
TRIES = 8


class LookRaced(Exception):
    """Every try lost to another writer."""


class LookRows:
    def __init__(self, cfg: ConfigDir, *, quiet: bool = False) -> None:
        self.rows = LoopRows(cfg, "", quiet=quiet)

    def raw(self, look_bead: str) -> str | None:
        found = self.rows.select("SELECT v FROM kv WHERE k=?", (PREFIX + look_bead,))
        return found[0][0] if found else None

    def items(self, look_bead: str) -> list[Item] | None:
        """The row's items, None when the bead has no row (or its body is not a list)."""
        text = self.raw(look_bead)
        try:
            body = json.loads(text) if text is not None else None
        except ValueError:
            return None
        return [e for e in body if isinstance(e, dict)] if isinstance(body, list) else None

    def modify(self, look_bead: str, seed: Callable[[], list[Item]], fn: Callable[[list[Item]], list[Item] | None]) -> list[Item] | None:
        """Read the items (`seed()` when there is no row yet), let `fn` change them, store the result if the row is still as read.
        `fn` runs again after a lost race, so it only computes. -> the stored items, None when `fn` answered None (nothing to write)."""
        for _ in range(TRIES):
            text = self.raw(look_bead)
            have = self.items(look_bead) if text is not None else None
            new = fn(have if have is not None else seed())
            if new is None:
                return None
            if self._swap(look_bead, text, json.dumps(new, ensure_ascii=False)):
                return new
        raise LookRaced(look_bead)

    def _swap(self, look_bead: str, old: str | None, body: str) -> bool:
        with self.rows.transaction() as con:
            if old is None:
                got = con.execute("INSERT INTO kv (k, v, t) VALUES (?, ?, ?) ON CONFLICT(k) DO NOTHING",
                                  (PREFIX + look_bead, body, time.time()))
            else:
                got = con.execute("UPDATE kv SET v=?, t=? WHERE k=? AND v=?", (body, time.time(), PREFIX + look_bead, old))
            return got.rowcount == 1
