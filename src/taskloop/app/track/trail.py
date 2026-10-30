"""What `tl` records about a bead's life: one line per event in events.jsonl (the dashboard's fast local index), the repos it has seen
(repos.json), and the provenance record in bd."""
import json
import socket
import sys
import time
from pathlib import Path
from typing import Any, Final

from atomic_io import atomic_write_text

from taskloop.adapters import applog
from taskloop.adapters.gitrepo import repo_root
from taskloop.contracts import events, wire
from taskloop.contracts.events import Event, EventRec
from taskloop.contracts.guard import guard
from taskloop.contracts.identity import Identity
from taskloop.contracts.ids import BeadId
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import BdFailure, Beads
from taskloop.contracts.stores import ReposStore

SOURCE: Final = "task-loop"
RETAIN_DAYS: Final = 7


def now() -> float:
    return time.time()


def event(by: Identity, kind: str, bead: str = "", **fields: Any) -> Event:
    """The one writer of events.jsonl (the dashboard's fast local index): a line is the typed Event record of `kind` (a name of
    contracts/events.py) with its fields, `v` first. A kind or field the contract does not name is refused here, never written."""
    head = {"t": now(), "kind": kind, "bead": bead, "session": by.session, "actor": by.actor,
            "repo": fields.pop("repo", None) or repo_root(), "host": socket.gethostname()}
    rec = events.decode({"v": EventRec.V, **head, **{k: v for k, v in fields.items() if v is not None}})
    cfg = by.config
    with guard(events_lock(cfg)):  # prune_events rewrites the file under this lock
        applog.append(cfg.events(), json.dumps(wire.dump(rec), ensure_ascii=False) + "\n")  # tl-64i: one held handle per process
    register_repo(rec.repo, cfg)
    return rec


def provenance(store: Beads, bead: BeadId, kind: str, ref: str, ref_kind: str, payload: dict[str, Any] | None = None) -> None:
    """The shared record in bd (append-only, idempotent); a bd without provenance is not fatal."""
    try:
        store.provenance(bead, kind, SOURCE, ref, ref_kind, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                            json.dumps(payload) if payload else "")
    except BdFailure as e:
        sys.stderr.write("tl: provenance not recorded: " + (e.error.text.strip().splitlines() or ["?"])[-1] + "\n")


def register_repo(path: str | None, cfg: ConfigDir) -> None:
    """Add a repo to repos.json. Every process registers (each event does); the store reads and writes under its lock, so two at once
    neither crash nor drop a repo. A repos.json of another version is said once per call and left alone."""
    if not path:
        return
    try:
        ReposStore(cfg).add(path, now())
    except ValueError as e:
        sys.stderr.write(f"tl: repo not registered: {e}\n")


def events_lock(cfg: ConfigDir) -> Path:
    return cfg.lock_record("log", "events")


def prune_events(cfg: ConfigDir, days: float = RETAIN_DAYS) -> None:
    f = cfg.events()
    if not f.exists() or f.stat().st_size < 2_000_000:
        return
    cut = now() - days * 86400
    with guard(events_lock(cfg)):  # read, filter, replace as one step: a line appended meanwhile waits
        keep: list[str] = []
        for ln in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                if json.loads(ln).get("t", 0) >= cut:
                    keep.append(ln)
            except ValueError:
                pass
        atomic_write_text(f, "\n".join(keep) + ("\n" if keep else ""), fsync=False)
