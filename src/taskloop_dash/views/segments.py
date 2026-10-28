"""One bead's whole time: every step, check and wait as a bar."""

import time
from typing import Final

WAIT_NAMES: Final = {
    "land_lock": "land lock",
    "review_lock": "review lock",
    "lane": "lane",
    "unity_slot": "Unity slot",
    "editor_lock": "editor lock",
    "delegate_crash": "delegate crash",
    "network": "network",
    "owner_ask": "owner ask",
    "paused": "paused",
    "between_runs": "between runs",
    "between_steps": "between steps",
    "other": "other wait",
}
LOCKS = ("land_lock", "review_lock")  # waited for after the step before them ended: a bar of their own, never cut out of a step
MIN_GAP = 10  # seconds of unexplained time worth a bar of its own


def _seg(kind, what, label, t0, t1, run, **kw):
    return dict({"kind": kind, "what": what, "label": label, "t0": t0, "t1": t1, "secs": max(0, round(t1 - t0)), "run": run}, **kw)


def block_segments(b: dict, waits: list, used: set, name: str) -> list[dict]:
    """A step's bars: the work, cut by the waits that started inside it."""
    out = []
    kind = "checks" if b["kind"] == "checks" else "work"
    label = b.get("label") or b["kind"]
    cuts = []
    for i, w in enumerate(waits):
        if i not in used and w["what"] not in LOCKS and b["t0"] - 1 <= w["t0"] < b["t1"]:  # a wait that starts in a step belongs to it
            cuts.append((max(b["t0"], w["t0"]), min(b["t1"], w["t0"] + w["secs"]), w))
            used.add(i)
    at = b["t0"]
    for cut0, c1, w in sorted(cuts, key=lambda c: c[0]):
        c0 = max(cut0, at)
        if c1 <= c0:
            continue
        if c0 > at:
            out.append(_seg(kind, b["kind"], label, at, c0, name, node=b["node"]))
        out.append(_seg("wait", w["what"], WAIT_NAMES.get(w["what"], w["what"]), c0, c1, name, node=b["node"], holder=w["holder"]))
        at = max(at, c1)
    if b["t1"] > at:
        out.append(_seg(kind, b["kind"], label, at, b["t1"], name, node=b["node"]))
    return out


def run_segments(r: dict, end) -> list[dict]:
    """The segments of one run: its steps, the waits the engine recorded (cut out of the step they happened in, or a bar of their
    own between steps), and the unexplained gaps between them."""
    name, out, used = r["run"], [], set()
    waits = [w for w in r.get("waits") or [] if w["secs"] > 0]
    for b in r["blocks"]:
        if b.get("t0") and b.get("t1") and b["t1"] >= b["t0"]:
            out += block_segments(b, waits, used, name)
    for i, w in enumerate(waits):
        t0 = max(w["t0"], r.get("started") or 0)  # never before the run: the time before it is the gap between runs
        if i not in used and w["t0"] + w["secs"] > t0:
            out.append(_seg("wait", w["what"], WAIT_NAMES.get(w["what"], w["what"]), t0, w["t0"] + w["secs"], name, holder=w["holder"]))
    out.sort(key=lambda x: (x["t0"], x["t1"]))
    filled, at = [], r.get("started")
    for s in out:
        if at and s["t0"] - at >= MIN_GAP:
            filled.append(_seg("idle", "between_steps", WAIT_NAMES["between_steps"], at, s["t0"], name))
        filled.append(s)
        at = max(at or 0, s["t1"])
    if at and end and end - at >= MIN_GAP:
        filled.append(_seg("idle", "between_steps", WAIT_NAMES["between_steps"], at, end, name))
    return filled


def bead_segments(runs: list[dict], now: float | None = None) -> dict:
    """runs: run_timeline() results of one bead, oldest first, the last one `alive` when the bead is running. -> {t0, t1, segments,
    totals}. Time between two runs is an owner ask (the earlier one ended asking), a pause (it ended paused) or idle."""
    now = now or time.time()
    segs, prev = [], None
    for r in runs:
        start = r.get("started")
        if not start:
            continue
        end = now if r.get("alive") else r.get("ended") or start
        if prev and prev["end"] and start - prev["end"] >= MIN_GAP:
            out = (prev["r"].get("end") or {}).get("outcome") or ""
            what = "owner_ask" if out in ("asks", "waiting") else "paused" if out == "paused" else "between_runs"
            segs.append(_seg("idle" if what == "between_runs" else "wait", what, WAIT_NAMES[what], prev["end"], start, r["run"]))
        segs += run_segments(r, end)
        prev = {"r": r, "end": end}
    totals = {"work": 0, "checks": 0, "wait": 0, "idle": 0, "by_what": {}}
    for s in segs:
        totals[s["kind"]] += s["secs"]
        if s["kind"] in ("wait", "idle", "checks"):
            totals["by_what"][s["what"]] = totals["by_what"].get(s["what"], 0) + s["secs"]
    return {"t0": segs[0]["t0"] if segs else None, "t1": segs[-1]["t1"] if segs else None, "segments": segs, "totals": totals, "now": now}
