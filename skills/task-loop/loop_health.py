"""Loop-level health: the run storm detector and the absent-loop verdict. Pure functions plus one small record file.

The storm detector stamps run fingerprints and never marks a lane (the delegate owns the lane breaker): the same FAULT
fingerprint on STORM_BEADS distinct beads inside the window trips it. One `storm` record is written (once) and one
banner is printed; the beads stay open and no per-bead ask is raised. Python 3.8+, stdlib only.
"""

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

import outcome as oc


@dataclass(frozen=True)
class StormTrip:
    fingerprint: str
    beads: tuple
    t: float


def storm_trip(history, bead, kind, fingerprint, now, knobs=oc.KNOBS):
    """The trip this close causes, or None. history: earlier closes {bead, kind, fingerprint, t}; (bead, kind, fingerprint)
    is the close being made. Only FAULT_* count: an ask repeats legitimately, a lane or network pause is gated by its wake."""
    if not oc.POLICY[kind].storm:
        return None
    cut = now - knobs["storm_window_s"]
    beads = {bead}
    for h in history:
        if h.get("fingerprint") != fingerprint or float(h.get("t") or 0) < cut:
            continue
        try:
            if oc.POLICY[oc.Kind(h.get("kind"))].storm:
                beads.add(h.get("bead"))
        except ValueError:
            continue
    if len(beads) < knobs["storm_beads"]:
        return None
    return StormTrip(fingerprint, tuple(sorted(beads)), now)


def banner(trip):
    return "STOPPED: storm %s on %s (the beads stay open; look at their logs, then `tl storm clear`)" % (
        trip.fingerprint, ",".join(trip.beads))


def recent_closes(traces, repo, now, window=None):
    """The closes in a traces.jsonl (this repo only, since now - window; all of them when window is None) that carry a kind,
    as {bead, kind, fingerprint (the row's kfp: kind + stripped text), t}, oldest first. A damaged or kind-less line is skipped."""
    out = []
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


def storm_path(config_dir, repo):
    return Path(config_dir) / "storm" / (hashlib.sha1(repo.encode("utf-8")).hexdigest()[:12] + ".json")


def read_storm(path, now, knobs=oc.KNOBS):
    """The live storm record, or None (absent, damaged, or older than the window: it expires by itself)."""
    try:
        rec = json.loads(Path(path).read_text(encoding="utf-8"))
        return rec if now - float(rec["t"]) < knobs["storm_window_s"] else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def write_storm(path, trip, now, text=""):
    """Write the record once: True when this call wrote it (the caller prints the banner), False when one is live."""
    if read_storm(path, now):
        return False
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".%d.tmp" % os.getpid())
    tmp.write_text(json.dumps({"fingerprint": trip.fingerprint, "beads": list(trip.beads), "t": trip.t, "text": text[:400]}),
                   encoding="utf-8")
    os.replace(tmp, path)
    return True


def clear_storm(path):
    try:
        Path(path).unlink()
    except OSError:
        pass
