"""The storm record on disk: one small file per repo, written once, expiring by itself, and the closes it is judged on."""
import contextlib
import hashlib
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any


def recent_closes(traces: str | Path, repo: str, now: float, window: float | None = None) -> list[dict[str, Any]]:
    """The closes in a traces.jsonl (this repo only, since now - window; all of them when window is None) that carry a kind,
    as {bead, kind, fingerprint (the row's kfp: kind + stripped text), t}, oldest first. A damaged or kind-less line is skipped."""
    out: list[dict[str, Any]] = []
    try:
        lines = Path(traces).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for ln in lines:
        if '"kind"' not in ln:
            continue
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        t = float(r.get("ended") or 0)
        if r.get("kind") and r.get("repo_url") == repo and (window is None or t >= now - window):
            out.append({"bead": r.get("bead"), "kind": r.get("kind"), "fingerprint": r.get("kfp") or "", "t": t})
    return out


def storm_path(config_dir: str | Path, repo: str) -> Path:
    return Path(config_dir) / "storm" / (hashlib.sha1(repo.encode("utf-8")).hexdigest()[:12] + ".json")


def read_storm(path: str | Path, now: float, window_s: float) -> dict[str, Any] | None:
    """The live storm record, or None (absent, damaged, or older than the window: it expires by itself)."""
    try:
        rec = json.loads(Path(path).read_text(encoding="utf-8"))
        return rec if now - float(rec["t"]) < window_s else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def write_storm(path: str | Path, fingerprint: str, beads: Sequence[str], t: float, now: float, window_s: float, text: str = "") -> bool:
    """Write the record once: True when this call wrote it (the caller prints the banner), False when one is live."""
    if read_storm(path, now, window_s):
        return False
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"fingerprint": fingerprint, "beads": list(beads), "t": t, "text": text[:400]}), encoding="utf-8")
    os.replace(tmp, path)
    return True


def clear_storm(path: str | Path) -> None:
    with contextlib.suppress(OSError):
        Path(path).unlink()
