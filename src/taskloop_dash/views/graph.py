"""The Plan tab's data: open beads as a dependency graph with one state each. Pure: server.py gathers the inputs
(bd list, the loop's queue, beads held by a slot, open asks) and calls build(). Python 3.8+, standard library only."""

import calendar
import time
from collections.abc import Collection, Iterable, Mapping
from typing import Any

Bead = dict[str, Any]

OWNER_LABELS = ("owner-taste", "needs-info", "owner-look")
STATES = ("running", "stuck", "queued", "blocked", "waits", "not_auto", "epic", "done", "deferred")
DAY = 86400


def parse(s: object) -> int:
    try:
        return calendar.timegm(time.strptime(str(s)[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, TypeError):
        return 0


def blockers(b: Bead) -> list[str]:
    return [d.get("id") for d in b.get("dependencies") or [] if d.get("type") == "blocks"]


def unblock_counts(edges: Mapping[str, Collection[str]], skip: Collection[str]) -> dict[str, int]:
    """id -> number of beads that wait on it, directly or through others, not counting ids in `skip` (epics, done).
    A cycle never loops: every walk keeps a seen set."""
    out: dict[str, int] = {}
    for s in edges:
        seen, stack = {s}, [s]
        while stack:
            for t in edges.get(stack.pop(), ()):
                if t not in seen:
                    seen.add(t)
                    stack.append(t)
        out[s] = len([x for x in seen if x != s and x not in skip])
    return out


def _day(t: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(t))


def build(beads: Iterable[Bead], cfg: Bead, queued: Iterable[str], running: Iterable[str] = (), asks: Iterable[str] = (), now: float | None = None,
          repo: str = "") -> Bead:
    now = now or time.time()
    running, asks, queued, pick = set(running), set(asks), set(queued), cfg.get("pick_label")
    beads = [b for b in beads if "slot" not in (b.get("labels") or [])]  # a slot record is a lock, never work: it is in_progress for as long as it exists
    by_id = {b["id"]: b for b in beads}
    recent = {b["id"] for b in beads if b.get("status") == "closed" and now - parse(b.get("closed_at")) < DAY}
    live = {b["id"] for b in beads if b.get("status") not in ("closed", "deferred")}
    # a deferred bead shows only where it holds something up or hangs under a shown epic
    keep = live | recent
    for b in beads:
        if b.get("status") == "deferred":
            if any(b["id"] in blockers(by_id[x]) for x in live if x in by_id):
                keep.add(b["id"])
    edges: dict[str, set[str]] = {}
    for t in keep:
        for s in blockers(by_id[t]):
            if s in keep and s != t:
                edges.setdefault(s, set()).add(t)
    open_edges = {s: {t for t in ts if by_id[t].get("status") != "closed"} for s, ts in edges.items()
                  if by_id[s].get("status") != "closed"}
    epics = {i for i in keep if by_id[i].get("issue_type") == "epic"}
    counts = unblock_counts(open_edges, epics | recent)

    def state(b: Bead) -> tuple[str, str]:
        i, labels = b["id"], set(b.get("labels") or [])
        if b.get("status") == "closed":
            return "done", "closed in the last 24 h"
        if b.get("status") == "deferred":
            return "deferred", "deferred"
        if b.get("issue_type") == "epic":
            return "epic", "epic"
        if i in running:
            return "running", "held by a slot now"
        if b.get("status") == "in_progress":
            return "stuck", "in_progress in bd, but no slot holds it: nothing runs it"
        if i in asks:
            return "waits", "an ask is open"
        if labels & set(OWNER_LABELS):
            return "waits", "label " + sorted(labels & set(OWNER_LABELS))[0]
        if b.get("status") == "review":
            return "waits", "in review"
        open_by = [x for x in blockers(b) if (by_id.get(x) or {}).get("status", "closed") != "closed"]
        if open_by or b.get("status") == "blocked":
            return "blocked", ("blocked by " + ", ".join(open_by[:3])) if open_by else "marked blocked"
        if i in queued:
            return "queued", "the loop would pick it"
        if pick and pick not in labels:
            return "not_auto", "no %s label: the loop never takes it" % pick
        return "not_auto", "the loop skips it"

    def parent_of(i: str) -> str | None:
        seen, p = {i}, by_id[i].get("parent")
        while p and p not in seen:
            if p in epics:
                return p
            seen.add(p)
            p = (by_id.get(p) or {}).get("parent")
        return None

    nodes: list[Bead] = []
    for i in sorted(keep):
        b = by_id[i]
        st, why = state(b)
        nodes.append({"id": i, "title": b.get("title") or "", "state": st, "why": why, "epic": parent_of(i),
                      "is_epic": i in epics, "unblocks": 0 if st == "done" else counts.get(i, 0),
                      "priority": b.get("priority"), "labels": b.get("labels") or [], "status": b.get("status"),
                      "closed_at": b.get("closed_at") if st == "done" else None})
    kids: dict[str, dict[str, int]] = {}
    for n in nodes:
        if n["epic"]:
            c = kids.setdefault(n["epic"], {})
            c[n["state"]] = c.get(n["state"], 0) + 1
    for n in nodes:
        n["kids"] = kids.get(n["id"], {}) if n["is_epic"] else None
    flat = [{"source": s, "target": t} for s in sorted(edges) for t in sorted(edges[s])]
    done_today = sum(1 for i in recent if _day(parse(by_id[i].get("closed_at"))) == _day(now))
    sc = dict.fromkeys(STATES, 0)
    for n in nodes:
        sc[n["state"]] += 1
    summary = {"ready": sc["queued"], "running": sc["running"], "stuck": sc["stuck"], "blocked": sc["blocked"], "waits": sc["waits"],
               "not_auto": sc["not_auto"], "epic": sc["epic"], "deferred": sc["deferred"], "done_today": done_today,
               "done": sc["done"]}
    return {"repo": repo, "now": now, "nodes": nodes, "edges": flat, "summary": summary, "pick_label": pick}
