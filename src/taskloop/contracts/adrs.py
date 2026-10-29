"""The decision store of one repo: ADR documents plus the log of plans that cited them. One reader and one writer; the engine and `tl`
write it, the dashboard reads it. It lives under the task-loop state dir (decisions/<repo key>/), not in the repo: the engine and
`tl` write only there and to bd, never into a checkout."""
from pathlib import Path

from taskloop.contracts import paths, wire
from taskloop.contracts.ids import loop_key
from taskloop.contracts.ledger import Adr, AdrUse
from taskloop.contracts.stores import AskDocs, JsonlStore, JsonStore


def is_adr_id(text: str) -> bool:
    """ADR-<n>: the id of a decision (also what keeps a path out of a lookup)."""
    return text.startswith("ADR-") and text[4:].isascii() and text[4:].isdigit()


def decode_use(data: object) -> AdrUse:
    return wire.load(AdrUse, data)


class AdrFiles:
    def __init__(self, cfg: paths.ConfigDir, repo: str) -> None:
        self.cfg, self.repo = cfg, loop_key(repo)

    def of(self, key: str) -> JsonStore[Adr]:
        return JsonStore(self.cfg.adr(self.repo, key), Adr)

    def keys(self) -> list[str]:
        return self.cfg.adr_ids(self.repo)


class AdrStore:
    def __init__(self, docs: AskDocs, uses: JsonlStore[AdrUse]) -> None:
        self.docs, self.log = docs, uses

    @classmethod
    def at(cls, cfg: paths.ConfigDir, repo: str) -> "AdrStore":
        return cls(AdrFiles(cfg, repo), JsonlStore(Path(cfg.adr_uses(loop_key(repo))), decode_use))

    def all(self) -> list[Adr]:
        names = self.docs.keys()
        found = (self.docs.of(k).read() for k in names)
        return sorted((a for a in found if a is not None), key=lambda a: a.n)

    def in_force(self) -> list[Adr]:
        return [a for a in self.all() if a.retired_t is None]

    def retire(self, adr: str, by: str, now: float) -> str:
        """Prune a decision in force. -> "" or why not (unknown, or already retired)."""
        found = self.get(adr)
        if found is None:
            return f"{adr} is not a decision of this repo"
        if found.retired_t is not None:
            return f"{adr} is already retired"
        self.put(found.model_copy(update={"retired_by": by, "retired_t": now}))
        return ""

    def get(self, adr: str) -> Adr | None:
        return self.docs.of(adr).read() if is_adr_id(adr) else None

    def add(self, adr: Adr) -> Adr:
        """File the ADR under the next free number; `adr.id` and `adr.n` are replaced."""
        n = max([a.n for a in self.all()], default=0) + 1
        done = adr.model_copy(update={"id": f"ADR-{n}", "n": n})
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
