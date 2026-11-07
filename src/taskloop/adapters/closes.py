"""Retry history from run closes."""
import json
from pathlib import Path
from typing import Any


def recent_closes(traces: str | Path, repo: str, now: float, window: float | None = None) -> list[dict[str, Any]]:
    """The closes in a traces.jsonl (this repo only, since now - window; all of them when window is None) that carry a kind,
    as {bead, kind, fingerprint (the row's kfp: kind + stripped text), t}, oldest first. A damaged or kind-less line is skipped."""
    out: list[dict[str, Any]] = []
    try:
        lines = Path(traces).read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
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
