"""What `tl` records about a bead's life: one line per event in events.jsonl (the dashboard's fast local index), the repos it has seen
(repos.json), and the provenance record in bd."""
import json
import socket
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from jsonl_log import JsonlLog, held
from tlkernel import events, wire
from tlkernel.beadsport import BdFailure, Beads
from tlkernel.events import Event, EventRec
from tlkernel.guard import guard
from tlkernel.identity import Identity
from tlkernel.ids import BeadId
from tlkernel.locator import RunLocator
from tlkernel.paths import ConfigDir
from tlkernel.rotating import NO_ROTATION
from tlkernel.rowstores import ReposStore

from taskloop.adapters.gitrepo import repo_root
from taskloop.stores.real import real_stores

SOURCE: Final = "task-loop"
RETAIN_DAYS: Final = 7


def now() -> float:
    return time.time()


def event(by: Identity, kind: str, bead: str = "", **fields: Any) -> Event:
    """The one writer of events.jsonl (the dashboard's fast local index): a line is the typed Event record of `kind` (a name of
    contracts/events.py) with its fields, `v` first. A kind or field the contract does not name is refused here, never written."""
    if kind == "stage" and fields.get("step") == "close":
        bundle = RunLocator(by.config).get(str(fields.get("run_id") or ""))
        finished = bundle.manifest.finish if bundle else None
        if finished is not None:
            fields.update(t=finished.ended, sha=finished.sha, text=f"close: {finished.outcome}")
    head = {"t": now(), "kind": kind, "bead": bead, "session": by.session, "actor": by.actor,
            "repo": fields.pop("repo", None) or repo_root(), "host": socket.gethostname()}
    rec = events.decode({"v": EventRec.V, **head, **{k: v for k, v in fields.items() if v is not None}})
    cfg = by.config
    with guard(events_lock(cfg)):  # prune_events rewrites the file under this lock
        if kind == "stage" and rec.step == "close" and rec.run_id:
            existing = next((i.rec for i in real_stores(cfg).events.read_from().items
                             if i.rec.run_id == rec.run_id and i.rec.step == "close"), None)
            if existing is not None:
                return existing
        events_log(cfg).append(json.dumps(wire.dump(rec), ensure_ascii=False).encode("utf-8", "surrogateescape"))  # tl-64i: one held handle
    register_repo(rec.repo, cfg)
    return rec


def provenance(store: Beads, bead: BeadId, kind: str, ref: str, ref_kind: str, payload: dict[str, Any] | None = None) -> None:
    """The shared record in bd (append-only, idempotent); a bd without provenance is not fatal."""
    try:
        store.provenance(bead, kind, SOURCE, ref, ref_kind, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                            json.dumps(payload) if payload else "")
    except BdFailure as e:
        sys.stderr.write("tl: provenance not recorded: " + (e.error.text.strip().splitlines() or ["?"])[-1] + "\n")


def register_repo(path: str | None, cfg: ConfigDir) -> bool:
    """Add a repo to repos.json. Every process registers (each event does); the store reads and writes under its lock, so two at once
    neither crash nor drop a repo. A repos.json of another version, or a name another folder holds, is said once per call and left
    alone. -> whether the repo is registered."""
    if not path:
        return False
    try:
        ReposStore(cfg).add(path, now())
    except ValueError as e:
        sys.stderr.write(f"tl: repo not registered: {e}\n")
        return False
    return True


def events_lock(cfg: ConfigDir) -> Path:
    return cfg.lock_record("log", "events")


def events_log(cfg: ConfigDir) -> JsonlLog:
    """The process's one open events.jsonl: never rotated (pruned by age), its prune lock is the one `event` holds."""
    return held(cfg.events(), rotate_bytes=NO_ROTATION, rotate_lock=events_lock(cfg))


def _newer(cut: float) -> Callable[[bytes], bool]:
    def keep(line: bytes) -> bool:
        try:
            return json.loads(line).get("t", 0) >= cut
        except ValueError:
            return False
    return keep


def prune_events(cfg: ConfigDir, days: float = RETAIN_DAYS) -> None:
    f = cfg.events()
    if f.exists() and f.stat().st_size >= 2_000_000:
        events_log(cfg).rewrite(_newer(now() - days * 86400))
