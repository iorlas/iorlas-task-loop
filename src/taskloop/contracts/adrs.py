"""The decisions of one repo as tl reads them: a cache (`kv` rows `adr:<repo key>:<id>`) of the repo's `docs/adr/NNNN-title.md` files at
the base commit, plus the log of plans that cited them. The files are the record (contracts/adrfiles.py): a lane lands each through a
bead, so tl never writes into a checkout. Whoever has git (the engine's plan stage, the owner verbs) calls `sync` with the files it
read at the base; the dashboard only reads the rows."""
from pathlib import Path
from typing import final

from taskloop.contracts import paths, wire
from taskloop.contracts.askstore import AskDocs
from taskloop.contracts.docrows import RowDocs
from taskloop.contracts.ids import loop_key
from taskloop.contracts.ledger import Adr, AdrUse
from taskloop.contracts.stores import JsonlStore


def is_adr_id(text: str) -> bool:
    """ADR-<n>: the id of a decision (also what keeps a path out of a lookup)."""
    return text.startswith("ADR-") and text[4:].isascii() and text[4:].isdigit()


def decode_use(data: object) -> AdrUse:
    return wire.load(AdrUse, data)


def rows(cfg: paths.ConfigDir, repo: str, quiet: bool = False) -> RowDocs[Adr]:
    """The cache rows of one repo's ADRs; an older tl's `decisions/<repo key>/ADR-n.json` is adopted on first read."""
    key = loop_key(repo)
    return RowDocs(cfg, Adr, table="kv", key_col="k", body_col="v", prefix=f"adr:{key}:", quiet=quiet)


@final
class AdrStore:
    def __init__(self, docs: AskDocs, uses: JsonlStore[AdrUse]) -> None:
        self.docs, self.log = docs, uses

    @classmethod
    def at(cls, cfg: paths.ConfigDir, repo: str, quiet: bool = False) -> AdrStore:
        return cls(rows(cfg, repo, quiet), JsonlStore(Path(cfg.adr_uses(loop_key(repo))), decode_use))

    def sync(self, found: list[Adr]) -> None:
        """Make the cache say what the files at the base say: write the changed ADRs, drop the rows of ADRs the files no longer have."""
        have = {a.id: a for a in self.all()}
        for adr in found:
            if have.get(adr.id) != adr:
                self.put(adr)
        for gone in set(have) - {a.id for a in found}:
            self.docs.of(gone).delete()

    def all(self) -> list[Adr]:
        names = self.docs.keys()
        found = (self.docs.of(k).get() for k in names)
        return sorted((a for a in found if a is not None), key=lambda a: a.n)

    def in_force(self) -> list[Adr]:
        return [a for a in self.all() if a.retired_t is None]

    def get(self, adr: str) -> Adr | None:
        return self.docs.of(adr).get() if is_adr_id(adr) else None

    def add(self, adr: Adr) -> Adr:
        """Cache the ADR under the next free number; `adr.id` and `adr.n` are replaced. (Only a cache: the record is the repo's file.)"""
        n = max([a.n for a in self.all()], default=0) + 1
        done = adr.replace(id=f"ADR-{n}", n=n)
        self.docs.of(done.id).write(done)
        return done

    def put(self, adr: Adr) -> None:
        self.docs.of(adr.id).write(adr)

    def use(self, adr: str, bead: str, run: str, now: float) -> None:
        self.log.append(AdrUse(adr=adr, bead=bead, run=run, t=now))

    def uses(self) -> list[AdrUse]:
        return [i.rec for i in self.log.read_from(0).items]

    def reuses(self) -> dict[str, tuple[int, float]]:
        """ADR id -> (plans that cited it, when last)."""
        out: dict[str, tuple[int, float]] = {}
        for u in self.uses():
            n, t = out.get(u.adr, (0, 0.0))
            out[u.adr] = (n + 1, max(t, u.t))
        return out
