"""bd, read only: a repo's beads (listed once, kept until bd's marker moves), one bead with its comments, and the repo a link means."""

import dataclasses
import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any

from taskloop.contracts.bead import Bead as TypedBead
from taskloop.contracts.ports import BdFailure, BeadQuery
from taskloop_dash.env import Bead, Env
from taskloop_dash.readers.records import Records

MAX_AGE = 60  # seconds a listing is kept when bd's marker did not move
SETTLE = 5  # seconds a listing is kept whatever the marker says
SHARED = 30  # seconds another process's listing on disk is good enough


def row_of(b: TypedBead) -> dict[str, Any]:
    """A typed bead as the dash's views read it: a dict, its dependencies as {id, type, title, status}."""
    out = dataclasses.asdict(b)
    out["dependencies"] = [{k: d.get(k) for k in ("id", "type", "title", "status")} for d in out["dependencies"]]
    return out


def basename(path: object) -> str:
    return os.path.basename(str(path or "").rstrip("/\\"))


class Beads:
    def __init__(self, env: Env, records: Records) -> None:
        self.env, self.records = env, records

    def beads_of(self, repo: str) -> list[Bead]:
        """bd list for one repo, re-run only when bd's last-touched marker moved (or every minute)."""
        env, clock = self.env, self.env.clock
        try:
            m = (Path(repo) / ".beads" / "last-touched").stat().st_mtime
        except OSError:
            m = 0
        key = "beads:" + repo
        hit = env.ttl.peek(key)  # (when, (marker, beads))
        if hit and hit[1][0] == m and clock() - hit[0] < MAX_AGE:
            return hit[1][1]
        if hit and clock() - hit[0] < SETTLE:
            return hit[1][1]
        beads: list[Bead] = hit[1][1] if hit else []
        disk = env.config.root / "cache" / ("beads-{}.json".format(hashlib.sha1(repo.encode("utf-8")).hexdigest()[:12]))
        if not hit:  # a fresh process (tl ask list): what another process listed lately is good enough
            try:
                c = json.loads(disk.read_text(encoding="utf-8"))
                if clock() - float(c["t"]) < SHARED and c.get("m") == m and isinstance(c["beads"], list):
                    env.ttl.put(key, (m, c["beads"]))
                    return c["beads"]
            except (OSError, ValueError, KeyError, TypeError):
                pass
        listed = self._list(repo)
        if listed is not None:
            beads = listed
            self._share(disk, m, beads)
        env.ttl.put(key, (m, beads))
        return beads

    def _list(self, repo: str) -> list[Bead] | None:
        try:
            return [row_of(b) for b in self.env.ports.store(repo).find(BeadQuery(include_closed=True))]
        except (BdFailure, ValueError, OSError):
            return None

    def _share(self, disk: Path, m: float, beads: list[Bead]) -> None:
        try:
            disk.parent.mkdir(parents=True, exist_ok=True)
            tmp = disk.with_name(f"{disk.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            tmp.write_text(json.dumps({"t": self.env.clock(), "m": m, "beads": beads}), encoding="utf-8")
            os.replace(str(tmp), str(disk))
        except OSError:
            pass

    def show(self, repo: str, bead: str) -> dict[str, Any] | None:
        """One bead as a row, None when bd does not know it or cannot answer."""
        try:
            found = self.env.ports.store(repo).show(bead) if repo else None
        except (BdFailure, ValueError, OSError):
            return None
        return row_of(found) if found else None

    def comments(self, repo: str, bead: str) -> list[dict[str, Any]]:
        try:
            return [dataclasses.asdict(c) for c in self.env.ports.store(repo).comments(bead)] if repo else []
        except (BdFailure, ValueError, OSError):
            return []

    def resolve_repo(self, repo: str, bead: str = "") -> str:
        """A link may name a repo by path or by folder name, or not at all: find the registered repo it means."""
        known = self.records.repos()
        if repo in known:
            return repo
        named = [p for p in known if basename(p) == repo]
        if named:
            return named[0]
        return next((p for p in known if bead and any(x["id"] == bead for x in self.beads_of(p))), "")

    def blocker_of(self, bead: str, repo_hint: str = "") -> dict[str, str] | None:
        """The first open bead this one depends on with a `blocks` dependency, as {id, title}; None when there is none. Reads the
        repo's cached `bd list`: one bd call per repo per refresh, never one per task."""
        repo = repo_hint if repo_hint in self.records.repos() else ""
        if not repo:
            name = basename(repo_hint).removesuffix(".git")
            repo = self.resolve_repo(name, bead) if name else self.resolve_repo("", bead)
        if not repo:
            return None
        by_id = {b.get("id"): b for b in self.beads_of(repo)}
        me = by_id.get(bead) or {}
        if me.get("status") == "closed":
            return None
        for d in me.get("dependencies") or []:
            if d.get("type") != "blocks":
                continue
            dep = by_id.get(d.get("id")) or {}
            if dep and dep.get("status") != "closed":
                return {"id": dep["id"], "title": dep.get("title") or ""}
        return None
