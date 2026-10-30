"""What `tl` records about a bead's life: one line per event in events.jsonl (the dashboard's fast local index), the repos it has seen
(repos.json), and the provenance record in bd."""
import json
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any, Final

from taskloop.adapters import applog
from taskloop.adapters.beadtools import bd_store
from taskloop.adapters.gitrepo import repo_root
from taskloop.adapters.ident import actor, config_dir, session_id
from taskloop.adapters.landlock import os_lock
from taskloop.contracts.guard import guard
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import BdFailure, Beads

SOURCE: Final = "task-loop"
RETAIN_DAYS: Final = 7


def now() -> float:
    return time.time()


def event(kind: str, bead: str = "", **fields: Any) -> dict[str, Any]:
    """One line per event in events.jsonl: the dashboard's fast local index (transcripts are local too)."""
    rec: dict[str, Any] = {"t": now(), "kind": kind, "bead": bead, "session": session_id(), "actor": actor(),
                           "repo": fields.pop("repo", None) or repo_root(), "host": socket.gethostname()}
    rec.update({k: v for k, v in fields.items() if v is not None})
    with guard(events_lock(ConfigDir(config_dir()))):  # prune_events rewrites the file under this lock
        applog.append(ConfigDir(config_dir()).events(), json.dumps(rec, ensure_ascii=False) + "\n")  # tl-64i: one held handle per process
    register_repo(rec["repo"])
    return rec


def provenance(bead: str, kind: str, ref: str, ref_kind: str, payload: dict[str, Any] | None = None, cwd: str | None = None,
               store: Beads | None = None) -> None:
    """The shared record in bd (append-only, idempotent); a bd without provenance is not fatal."""
    try:
        (store or bd_store(cwd)).provenance(bead, kind, SOURCE, ref, ref_kind, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                            json.dumps(payload) if payload else "")
    except BdFailure as e:
        sys.stderr.write("tl: provenance not recorded: " + (e.error.text.strip().splitlines() or ["?"])[-1] + "\n")


def register_repo(path: str | None) -> None:
    """Add a repo to repos.json. Every process registers (each event does): the read and write go under a lock, each through its own tmp
    file, so two at once neither crash nor drop a repo."""
    f = ConfigDir(config_dir()).repos()

    def read() -> dict[str, Any]:
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    if not path or path in read():
        return
    with os_lock(config_dir() / "locks" / "repos.lock", f"pid {os.getpid()}"):
        repos = read()
        if path not in repos:
            repos[path] = {"added": now()}
            tmp = f.with_name(f"repos.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(repos, indent=1), encoding="utf-8")
            os.replace(tmp, f)


def events_lock(cfg: ConfigDir) -> Path:
    return cfg.lock_record("log", "events")


def prune_events(days: float = RETAIN_DAYS) -> None:
    f = ConfigDir(config_dir()).events()
    if not f.exists() or f.stat().st_size < 2_000_000:
        return
    cut = now() - days * 86400
    with guard(events_lock(ConfigDir(config_dir()))):  # read, filter, replace as one step: a line appended meanwhile waits
        keep: list[str] = []
        for ln in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                if json.loads(ln).get("t", 0) >= cut:
                    keep.append(ln)
            except ValueError:
                pass
        tmp = f.with_name(f"events.{os.getpid()}.tmp")
        tmp.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")
        os.replace(tmp, f)
