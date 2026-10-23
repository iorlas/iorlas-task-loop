"""The Roadmap tab's data: one lane per slot (the bead running now, its stage rail, what its landing unlocks, the last
passes that left the slot) and the queue in the order the loop takes it, each entry with the beads it unblocks as a
tree. Pure: server.py gathers the inputs and calls build(). Python 3.8+, standard library only."""

import time

STEPS = ("plan", "write", "checks", "review", "verify", "land")
OUTCOMES = ("landed", "parked", "failed", "paused")   # "taken" (lost a claim race) is not an outcome of a pass
DEPTH, WIDE, PAST = 3, 5, 5


def epoch(s):
    try:
        return time.mktime(time.strptime(str(s)[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, TypeError):
        return 0


def rail(blocks, run_no):
    """[{step, state}] for the six steps: done, now (the live block) or todo. A step seen in the run is done; the live
    block's step is now; the plan of a resumed run (run 2 and later) counts as done."""
    seen, now_step = set(), None
    for i, b in enumerate(blocks):
        k = "plan" if b.get("kind") == "replan" else b.get("kind")
        seen.add(k)
        if i == len(blocks) - 1 and b.get("status") in ("run", "running"):
            now_step = k
    if run_no > 1:
        seen.add("plan")
    return [{"step": s, "state": "now" if s == now_step else "done" if s in seen else "todo"} for s in STEPS]


def tree(i, out, by_id, seen=(), depth=DEPTH):
    """The beads that wait on `i`: [{id, title, state, needs, kids, more}]. `needs` = other open blockers it still has
    (it unlocks only when they land too). Cycles stop at a seen id."""
    kids = [t for t in out.get(i, ()) if t not in seen and by_id.get(t) and by_id[t]["state"] != "done"
            and not by_id[t]["is_epic"]]
    res = []
    for t in sorted(kids, key=lambda t: (-by_id[t]["unblocks"], t))[:WIDE]:
        n = by_id[t]
        res.append({"id": t, "title": n["title"], "state": n["state"], "needs": max(0, len(n.get("blocked_by") or ()) - 1),
                    "kids": tree(t, out, by_id, tuple(seen) + (i,), depth - 1) if depth > 1 else [], "more": 0})
    if len(kids) > WIDE and res:
        res[-1]["more"] = len(kids) - WIDE
    return res


def released(i, out, by_id):
    """Beads whose last open blocker was `i`: what a landing of `i` let go."""
    return [{"id": t, "title": by_id[t]["title"], "state": by_id[t]["state"]} for t in out.get(i, ())
            if by_id.get(t) and by_id[t]["state"] not in ("done", "epic", "blocked") and not by_id[t]["is_epic"]]


def build(graph_data, lanes, ranked, skipped, history, trails, now=None):
    """graph_data: graph.build() output. lanes: [{slot, bead, since}] (bead None = an idle loop). ranked: [(id, reason)] in
    the order `tl next` takes them. skipped: [(id, why)]. history: loop-log rows, oldest first. trails: {bead: {run,
    stage, blocks: [{kind, label, status, text}]}}."""
    now = now or time.time()
    by_id = {n["id"]: n for n in graph_data["nodes"]}
    out = {}
    for e in graph_data["edges"]:
        out.setdefault(e["source"], []).append(e["target"])
    blockers = {}
    for e in graph_data["edges"]:
        if by_id.get(e["source"]) and by_id[e["source"]]["state"] != "done":
            blockers.setdefault(e["target"], []).append(e["source"])
    for i, n in by_id.items():
        n["blocked_by"] = blockers.get(i, [])
    passes = []
    for r in history:
        if r.get("outcome") in OUTCOMES:
            t = epoch(r.get("ts"))
            title = (by_id.get(r["bead"]) or {}).get("title", "")
            passes.append({"id": r["bead"], "title": title, "slot": r.get("slot"), "outcome": r["outcome"], "t": t,
                           "minutes": r.get("minutes") or 0, "asked": bool(r.get("asked")), "why": (r.get("why") or "")[:160],
                           "released": released(r["bead"], out, by_id) if r["outcome"] == "landed" else []})
    lane_out = []
    for ln in sorted(lanes, key=lambda x: x["slot"]):
        b, tr = ln.get("bead"), trails.get(ln.get("bead")) or {}
        node = by_id.get(b) or {}
        lane_out.append({
            "slot": ln["slot"], "bead": b, "title": node.get("title") or tr.get("title") or "", "since": ln.get("since"),
            "run": tr.get("run") or 0, "stage": tr.get("stage") or "",
            "rail": rail(tr.get("blocks") or [], tr.get("run") or 0) if b else [],
            "trail": tr.get("blocks") or [], "unlocks": tree(b, out, by_id) if b else [],
            "unblocks": node.get("unblocks", 0),
            "past": [p for p in passes if p["slot"] == ln["slot"]][-PAST:]})
    queue = []
    for i, why in ranked:
        n = by_id.get(i) or {}
        queue.append({"id": i, "title": n.get("title", ""), "priority": n.get("priority"), "reason": why,
                      "unblocks": n.get("unblocks", 0), "tree": tree(i, out, by_id)})
    held = []
    for i, why in skipped:
        n = by_id.get(i)
        if n:
            held.append({"id": i, "title": n["title"], "why": why, "priority": n.get("priority"), "unblocks": n["unblocks"],
                         "tree": tree(i, out, by_id)})
    held.sort(key=lambda h: (-h["unblocks"], h["id"]))
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    today = [p for p in passes if time.strftime("%Y-%m-%d", time.localtime(p["t"])) == day]
    summary = {o: sum(1 for p in today if p["outcome"] == o) for o in OUTCOMES}
    summary["ready"] = len(queue)
    return {"now": now, "repo": graph_data.get("repo", ""), "lanes": lane_out, "queue": queue, "held": held[:12],
            "held_total": len(held), "summary": summary, "recent": passes[-12:][::-1]}
