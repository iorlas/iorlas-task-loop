"""DB bead listings, live bd drawer details, and registered repository identities."""

import os
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from taskloop_dash.env import Bead, Env
from taskloop_dash.readers.records import Records
from tlkernel import beadrows
from tlkernel.beadrows import row_of
from tlkernel.beadsport import BdFailure
from tlkernel.ids import BeadId, loop_key

DETAIL_TTL = 15  # seconds a successful comments read is kept


@dataclass(frozen=True)
class Observation:
    """Last good rows and their observation time; a failed attempt only changes the error."""

    rows: list[Bead] = field(default_factory=list)
    ok_at: float | None = None
    error: str = ""


def basename(path: object) -> str:
    return os.path.basename(str(path or "").rstrip("/\\"))


class Beads:
    def __init__(self, env: Env, records: Records) -> None:
        self.env, self.records = env, records
        self.observed: dict[str, Observation] = {}

    @staticmethod
    def _key(repo: str, bead: str) -> str:
        return f"comments:{repo}:{bead}"

    def health(self, repo: str, bead: str = "") -> tuple[float | None, str]:
        if not bead:
            _, ok_at, error = beadrows.read_repo(self.env.config.factory_db(), loop_key(repo))
            return ok_at, error
        obs = self.observed.get(self._key(repo, bead), Observation())
        return obs.ok_at, obs.error

    def _observe(self, key: str, read: Callable[[], list[Bead]]) -> Observation:
        try:
            rows = read()
        except (BdFailure, ValueError, OSError) as exc:
            obs = replace(self.observed.get(key, Observation()), error=str(exc) or type(exc).__name__)
            self.env.ttl.drop(key)
        else:
            obs = Observation(rows, self.env.clock())
            self.env.ttl.put(key, obs)
        self.observed[key] = obs
        return obs

    def beads_of(self, repo: str) -> list[Bead]:
        """The indexer's only cached listing; this server read never calls bd."""
        return beadrows.read_repo(self.env.config.factory_db(), loop_key(repo))[0]

    def show(self, repo: str, bead: BeadId) -> dict[str, object] | None:
        """One bead as a row, None when bd does not know it or cannot answer."""
        try:
            found = self.env.ports.store(repo).show(bead) if repo else None
        except (BdFailure, ValueError, OSError):
            return None
        return row_of(found) if found else None

    def comments(self, repo: str, bead: BeadId) -> list[dict[str, object]]:
        key = self._key(repo, bead)
        hit = self.env.ttl.peek(key)
        if hit and self.env.clock() - hit[0] < DETAIL_TTL:
            return hit[1].rows
        return self._observe(key, lambda: [c.to_dict() for c in self.env.ports.store(repo).comments(bead)]).rows

    def resolve_repo(self, repo: str, bead: str = "") -> str:
        """Resolve a registered repository's immutable dashboard key."""
        known = self.records.repos()
        return next((p for p in known if loop_key(p) == repo), "")

