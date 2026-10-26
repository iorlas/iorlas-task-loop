"""The Roadmap tab's data: one lane per slot (the bead running now, its stage rail, what its landing unlocks, the last
passes that left the slot) and the queue in the order the loop takes it, each entry with the beads it unblocks as a
tree. Pure: server.py gathers the inputs and calls build(). Python 3.8+, standard library only."""

import re
import time
from datetime import datetime

import signals

STEPS = ("plan", "write", "checks", "review", "verify", "land")
OUTCOMES = ("landed", "parked", "failed", "paused")   # "taken" (lost a claim race) is not an outcome of a pass
DEPTH, WIDE, PAST = 3, 5, 8
DONE_DAYS = 7   # the Done feed reaches this far back; the page narrows it to today or shows all of it


def epoch(s):
    try:
        return time.mktime(time.strptime(str(s)[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, TypeError):
        return 0


def when(s):
    """Epoch of a bd timestamp (ISO, with an offset or Z; a bare one is local time, like the loop log's); 0 when unreadable."""
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return 0
    return d.timestamp()


def family(slot):
    """The slot's family: loop slots are named per run (loop-<session>, loop-<session>-<suffix>), so a restart is a new
    slot name in the same family. Any other name is its own family."""
    slot = slot or ""
    return "loop" if slot == "loop" or slot.startswith("loop-") else slot


def done_feed(passes, closed, now):
    """The repo-wide Done feed, newest first: every bd-closed bead of the last DONE_DAYS days, whoever closed it, merged with
    the loop's passes. A bead the loop landed is one row (by "loop", with the pass's minutes and run); a closed bead with no
    landed pass is by "hand" (an agent worktree, release.py, a person); a parked/failed/paused pass is a loop row.
    -> [{id, title, t, by, outcome, minutes, run, why, today}]; typed data only, the page words it."""
    since = now - DONE_DAYS * 86400
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    landed = {p["id"]: p for p in passes if p["outcome"] == "landed"}
    rows, seen = [], set()
    for b in closed:
        if b.get("status") != "closed" or "slot" in (b.get("labels") or []):
            continue
        t = when(b.get("closed_at"))
        if t < since:
            continue
        p = landed.get(b["id"])
        seen.add(b["id"])
        why = (p or {}).get("why") or b.get("close_reason") or ""
        rows.append({"id": b["id"], "title": b.get("title") or "", "t": t, "by": "loop" if p else "hand",
                     "outcome": "landed" if p else "closed", "minutes": p["minutes"] if p else 0,
                     "run": p["run"] if p else "", "why": why[:160]})
    for p in passes:
        if p["t"] < since or (p["outcome"] == "landed" and p["id"] in seen):
            continue
        rows.append({"id": p["id"], "title": p["title"], "t": p["t"], "by": "loop", "outcome": p["outcome"],
                     "minutes": p["minutes"], "run": p["run"], "why": p["why"]})
    rows.sort(key=lambda r: (-r["t"], r["id"]))
    for r in rows:
        r["today"] = time.strftime("%Y-%m-%d", time.localtime(r["t"])) == day
    return rows


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


def build(graph_data, lanes, ranked, skipped, history, trails, now=None, rows=None, lane_records=(), asks=(), waiting=0, looks=(), closed=(), installed=()):
    """graph_data: graph.build() output. lanes: [{slot, bead, since}] (bead None = an idle loop). ranked: [(id, reason)] in
    the order `tl next` takes them. skipped: [(id, why)]. history: loop-log rows, oldest first. trails: {bead: {run,
    stage, blocks: [{kind, label, status, text}]}}. closed: the repo's bd beads (the closed ones feed Done)."""
    now = now or time.time()
    by_id = {n["id"]: dict(n) for n in graph_data["nodes"]}  # copies: build() adds keys, and the graph is cached and shared
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
        if isinstance(r, dict) and r.get("bead") and r.get("outcome") in OUTCOMES:
            t = epoch(r.get("ts"))
            title = (by_id.get(r["bead"]) or {}).get("title", "")
            passes.append({"id": r["bead"], "title": title, "slot": r.get("slot") or "", "outcome": r["outcome"], "t": t,
                           "minutes": r.get("minutes") or 0, "asked": bool(r.get("asked")), "run": r.get("trace") or "", "why": (r.get("why") or "")[:160],
                           "released": released(r["bead"], out, by_id) if r["outcome"] == "landed" else []})
    lane_out = []
    for ln in sorted(lanes, key=lambda x: x["slot"]):
        b, tr = ln.get("bead"), trails.get(ln.get("bead")) or {}
        node = by_id.get(b) or {}
        lane_out.append({
            "slot": ln["slot"], "bead": b, "version": ln.get("version") or "", "engine": ln.get("engine") or "",
            "lags": lag(ln.get("engine") or ln.get("version") or "", installed), "stopping": ln.get("stopping") or "", "title": node.get("title") or tr.get("title") or "", "since": ln.get("since"),
            "run": tr.get("run") or 0, "stage": tr.get("stage") or "",
            "rail": rail(tr.get("blocks") or [], tr.get("run") or 0) if b else [],
            "trail": tr.get("blocks") or [], "unlocks": tree(b, out, by_id) if b else [],
            "unblocks": node.get("unblocks", 0),
            "past": [p for p in passes if family(p["slot"]) == family(ln["slot"])][-PAST:]})
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
    out = {"now": now, "repo": graph_data.get("repo", ""), "lanes": lane_out, "queue": queue, "held": held[:12],
           "held_total": len(held), "summary": summary, "done": done_feed(passes, closed, now)}
    out["loops_waiting"] = waiting
    out["briefs"] = briefs(out, by_id, rows or {})
    mine = [r for r in (rows or {}).values() if not graph_data.get("repo") or r.get("repo") == graph_data["repo"]]
    out.update(signals.build(mine, passes, list(lane_records), list(asks), graph_data.get("summary"), now, list(looks)))
    for ln in out["lanes"]:
        ln["verdict"] = verdict((rows or {}).get(ln["bead"]) or {}, out["stats"])
    return out


def ids_shown(out):
    """Every bead id the page draws a link for."""
    seen = set()

    def walk(ks):
        for k in ks:
            seen.add(k["id"])
            walk(k.get("kids") or [])
    for ln in out["lanes"]:
        if ln["bead"]:
            seen.add(ln["bead"])
        seen.update(p["id"] for p in ln["past"])
        walk(ln["unlocks"])
    for q in out["queue"] + out["held"]:
        seen.add(q["id"])
        walk(q["tree"])
    seen.update(p["id"] for p in out["done"])
    return seen


def briefs(out, by_id, rows):
    """id -> what a hover says: title, one line of state and why, and what it has cost. `rows` are the engine's task rows
    (server.api_tasks): its label is the truest 'why' (waiting for your answer, paused: lane out, checks red...)."""
    res = {}
    for i in ids_shown(out):
        n, r = by_id.get(i) or {}, rows.get(i) or {}
        spent = r.get("tokens_all") or {}
        res[i] = {"title": n.get("title") or r.get("title") or "", "state": r.get("state") or n.get("state") or "",
                  "why": r.get("label") or n.get("why") or "", "priority": n.get("priority"),
                  "runs": r.get("runs") or 0, "blocks": r.get("blocks") or 0, "secs": r.get("secs") or 0,
                  "tok": (spent.get("in") or 0) + (spent.get("out") or 0),
                  "fresh": max(0, (spent.get("in") or 0) - (spent.get("cached") or 0)) + (spent.get("out") or 0),
                  "new_in": max(0, (spent.get("in") or 0) - (spent.get("cached") or 0)), "cache": spent.get("cached") or 0,
                  "out": spent.get("out") or 0}
    return res


def verdict(r, stats):
    """One line on a running bead: its churn and what it has cost against the median bead; '' when it is unremarkable."""
    bits = []
    if r.get("writes", 0) > 1:
        bits.append("write round %d" % r["writes"])
    if r.get("red_checks"):
        bits.append("checks failed %d×" % r["red_checks"])
    if r.get("replans"):
        bits.append("planned %d×" % (r["replans"] + 1))
    if r.get("secs") and (r.get("checks_secs") or 0) / r["secs"] >= .4:
        bits.append("%d%% of its time in checks" % round(100 * r["checks_secs"] / r["secs"]))
    f = signals.fresh(r)
    if f and stats.get("median_fresh"):
        bits.append("%s fresh tokens, %.1f× the median bead" % (signals.human(f), f / stats["median_fresh"]))
    return " · ".join(bits)


def vkey(v):
    return tuple(int(x) for x in v.split(".")) if re.fullmatch(r"\d+(\.\d+)*", v or "") else None


def lag(version, installed):
    """How many installed releases are newer than `version` (0: current, or either side unknown)."""
    mine = vkey(version)
    return sum(1 for v in installed if mine and vkey(v) and vkey(v) > mine)


def lanes_of(slots, running, loops, stop=(0, "")):
    """One lane per slot, never per loop. slots: this machine's slot names; running: {bead: slot} (a slot bead's held_bead, or
    a live engine lock); loops: live loop states [{pid, slot, bead, since, started, version}]; stop: {pid: applicable mode},
    or a legacy (mtime, mode) pair. -> (lanes, waiting): a lane {slot, bead, since, version, stopping, loop}, and loops without a slot
    (they wait in line; they are a note on the queue, not a lane). A slot with no bead is free; a loop with a bead but no
    slot name (run in a worktree) gets a lane named after its bead's slot or '-'."""
    def mode(lp):
        if isinstance(stop, dict):
            return stop.get(lp.get("pid"), "")
        return stop[1] if stop[0] > (lp.get("started") or 0) + 1 else ""
    names = set(slots) | set(running.values()) | {lp["slot"] for lp in loops if lp.get("slot")}
    lanes = []
    for name in sorted(names):
        bead = next((b for b, s in running.items() if s == name), None)
        owner = next((lp for lp in loops if lp.get("slot") == name or (bead and lp.get("bead") == bead)), None)
        bead = bead or (owner or {}).get("bead")
        lanes.append({"slot": name, "bead": bead, "since": (owner or {}).get("since") if bead else None,
                      "version": (owner or {}).get("version") or "", "engine": (owner or {}).get("engine") or "",
                      "stopping": mode(owner) if owner else "",
                      "loop": (owner or {}).get("pid")})
    placed = {l["loop"] for l in lanes if l["loop"]}
    for lp in loops:  # a loop on a bead whose slot nobody named
        if lp.get("bead") and lp.get("pid") not in placed and lp["bead"] not in {l["bead"] for l in lanes}:
            lanes.append({"slot": lp.get("slot") or "-", "bead": lp["bead"], "since": lp.get("since"), "version": lp.get("version") or "",
                          "stopping": mode(lp), "loop": lp.get("pid")})
            placed.add(lp.get("pid"))
    waiting = [lp for lp in loops if not lp.get("bead") and lp.get("pid") not in placed]
    return lanes, waiting
