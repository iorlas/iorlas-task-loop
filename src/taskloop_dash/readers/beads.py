"""bd, read only: a repo's beads (listed once, kept until bd's marker moves), one bead with its comments, and the repo a link means."""

import json
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from taskloop.contracts.bead import Bead as TypedBead
from taskloop.contracts.ids import BeadId, loop_key
from taskloop.contracts.ports import BdFailure, BeadQuery
from taskloop_dash.env import Bead, Env
from taskloop_dash.readers.records import Records

MAX_AGE = 60  # seconds a listing is kept when bd's marker did not move
SETTLE = 5  # seconds a listing is kept whatever the marker says
SHARED = 30  # seconds another process's listing on disk is good enough
DETAIL_TTL = 15  # seconds a successful comments read is kept


@dataclass(frozen=True)
class Observation:
    """Last good rows and their observation time; a failed attempt only changes the error."""

    rows: list[Bead] = field(default_factory=list)
    ok_at: float | None = None
    error: str = ""
    marker: float = 0.0


def row_of(b: TypedBead) -> dict[str, Any]:
    """A typed bead as the dash's views read it: a dict, its dependencies as {id, type, title, status}."""
    out = b.to_dict()
    out["dependencies"] = [{k: d.get(k) for k in ("id", "type", "title", "status")} for d in out["dependencies"]]
    return out


def basename(path: object) -> str:
    return os.path.basename(str(path or "").rstrip("/\\"))


class Beads:
    def __init__(self, env: Env, records: Records) -> None:
        self.env, self.records = env, records
        self.observed: dict[str, Observation] = {}

    @staticmethod
    def _key(repo: str, bead: str = "") -> str:
        return f"comments:{repo}:{bead}" if bead else "beads:" + repo

    def health(self, repo: str, bead: str = "") -> tuple[float | None, str]:
        obs = self.observed.get(self._key(repo, bead), Observation())
        return obs.ok_at, obs.error

    def _observe(self, key: str, read: Callable[[], list[Bead]], marker: float = 0.0) -> Observation:
        try:
            rows = read()
        except (BdFailure, ValueError, OSError) as exc:
            obs = replace(self.observed.get(key, Observation()), error=str(exc) or type(exc).__name__)
            self.env.ttl.drop(key)
        else:
            obs = Observation(rows, self.env.clock(), marker=marker)
            self.env.ttl.put(key, obs)
        self.observed[key] = obs
        return obs

    def beads_of(self, repo: str) -> list[Bead]:
        """bd list for one repo, re-run only when bd's last-touched marker moved (or every minute)."""
        env, clock = self.env, self.env.clock
        try:
            m = (Path(repo) / ".beads" / "last-touched").stat().st_mtime
        except OSError:
            m = 0
        key = self._key(repo)
        hit = env.ttl.peek(key)
        if hit:
            obs: Observation = hit[1]
            age = clock() - obs.ok_at if obs.ok_at is not None else MAX_AGE
            if age < SETTLE or (obs.marker == m and age < MAX_AGE):
                return obs.rows
        disk = env.config.beads_cache(repo)
        if key not in self.observed:  # reuse another process's success, preserving its original observation time
            shared = self._shared(disk, m)
            if shared is not None:
                self.observed[key] = shared
                env.ttl.put(key, shared)
                return shared.rows
        obs = self._observe(key, lambda: self._list(repo), m)
        if not obs.error:
            self._share(disk, obs)
        return obs.rows

    def _list(self, repo: str) -> list[Bead]:
        return [row_of(b) for b in self.env.ports.store(repo).find(BeadQuery(include_closed=True))]

    def _shared(self, disk: Path, marker: float) -> Observation | None:
        try:
            c = json.loads(disk.read_text(encoding="utf-8"))
            if isinstance(c, dict) and self.env.clock() - float(c["t"]) < SHARED and c.get("m") == marker and isinstance(c["beads"], list):
                return Observation(c["beads"], float(c["t"]), marker=marker)
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def _share(self, disk: Path, obs: Observation) -> None:
        try:
            disk.parent.mkdir(parents=True, exist_ok=True)
            tmp = disk.with_name(f"{disk.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            tmp.write_text(json.dumps({"t": obs.ok_at, "m": obs.marker, "beads": obs.rows}), encoding="utf-8")
            os.replace(str(tmp), str(disk))
        except OSError:
            pass

    def show(self, repo: str, bead: BeadId) -> dict[str, Any] | None:
        """One bead as a row, None when bd does not know it or cannot answer."""
        try:
            found = self.env.ports.store(repo).show(bead) if repo else None
        except (BdFailure, ValueError, OSError):
            return None
        return row_of(found) if found else None

    def comments(self, repo: str, bead: BeadId) -> list[dict[str, Any]]:
        key = self._key(repo, bead)
        hit = self.env.ttl.peek(key)
        if hit and self.env.clock() - hit[0] < DETAIL_TTL:
            return hit[1].rows
        return self._observe(key, lambda: [c.to_dict() for c in self.env.ports.store(repo).comments(bead)]).rows

    def resolve_repo(self, repo: str, bead: str = "") -> str:
        """Resolve a registered repository's immutable dashboard key."""
        known = self.records.repos()
        return next((p for p in known if loop_key(p) == repo), "")

