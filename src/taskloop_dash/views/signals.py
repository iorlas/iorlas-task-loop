"""The Roadmap's top strip: what is wrong, what needs the owner, what is going well, computed from records the dashboard
already reads. Pure: server.py gathers the inputs and calls build(). Every rule has a threshold named below, picked from
lifesim's real distribution (2026-10-21..23: 131 beads, 77 parks of which 51 one cause) so that it fires on something real
and stays quiet otherwise. Python 3.8+, standard library only."""

import statistics
import time
from collections.abc import Iterable, Sequence
from typing import Any, Final

Row = dict[str, Any]

SEVERITY: Final = {"red": 0, "amber": 1, "info": 2, "green": 3}
CLUSTER_N, CLUSTER_WINDOW, CLUSTER_LOOKBACK = 4, 3 * 3600, 6 * 3600   # parks with one cause, within, looked at over
CHURN_CHECKS_RED, CHURN_BLOCKS, CHURN_LOOKBACK = 3, 12, 24 * 3600      # checks fails, steps in one bead
HOG_FRESH, HOG_TIMES_MEDIAN, HOG_LOOKBACK = 500_000, 3, 48 * 3600     # fresh tokens (input minus cached, plus output)
REPLANS = 3
BIG_TURN = 10_000_000                    # one write step (a block of many model calls; input incl. cache + output): p93 of lifesim's 93
SLOW_CHECK, SENDBACKS = 600, 2           # seconds per check round; review send-backs
ASK_AMBER, ASK_RED, ASK_PARK_SOON = 12 * 3600, 24 * 3600, 24 * 3600
USAGE_HIGH = 90.0
BUDGET_NEAR = 1.15  # an over-budget stop at most this far over its limit is a near miss


def fresh(row: Row) -> int:
    t = row.get("tokens_all") or {}
    return max(0, (t.get("in") or 0) - (t.get("cached") or 0)) + (t.get("out") or 0)


def total(row: Row) -> int:
    t = row.get("tokens_all") or {}
    return (t.get("in") or 0) + (t.get("out") or 0)


def short(i: object) -> str:
    return str(i).split("-", 1)[-1]


def human(n: float) -> str:
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{round(n / 1e3)}k" if n >= 1e3 else str(int(n))


def dur(s: float) -> str:
    s = int(s)
    return f"{int(s // 86400)}d" if s >= 2 * 86400 else f"{int(s // 3600)}h{int(s % 3600 // 60):02d}m" if s >= 3600 else f"{int(s // 60)}m"


def _id_like(run: str) -> bool:
    """A token such as `tl-bxk.8` or `abc-12`: letters and digits, one dash, then letters, digits and dots."""
    core = run.strip(".-")
    head, dash, tail = core.partition("-")
    return bool(dash and head and tail and head.isalnum() and all(c.isalnum() or c in ".-" for c in tail))


def cause(why: object) -> str:
    """A parked pass's reason with ids, numbers and quoted payloads cut, so the same cause groups."""
    w = str(why or "").lower()
    cut = min((i for i in (w.find(c) for c in "`'\"{") if i >= 0), default=len(w))
    w, run = w[:cut], ""
    words: list[str] = []
    for ch in w + " ":
        if ch.isalnum() or ch in ".-":
            run += ch
            continue
        if run and not _id_like(run):
            words.append(run)
        words.append(ch)
        run = ""
    w = "".join(words).translate({ord(c): None for c in "0123456789$"})
    return " ".join(w.split()).strip(" :;,.-")[:70]


def budget_pair(text: object) -> tuple[int, int] | None:
    """(used, limit) from the first 'N of M min' after 'over budget:' in a pass's reason; None when there is none."""
    _, found, rest = str(text).partition("over budget:")
    at = rest.find(" of ") if found else -1
    while at >= 0:
        left, right = rest[:at], rest[at + 4:]
        used = len(left) - len(left.rstrip("0123456789"))
        limit = len(right) - len(right.lstrip("0123456789"))
        if used and limit and right[limit:].startswith(" min"):
            return int(left[len(left) - used:]), int(right[:limit])
        at = rest.find(" of ", at + 1)
    return None


def medians(rows: Sequence[Row]) -> Row:
    """Median and p90 of fresh tokens per bead over the beads that spent any."""
    v = sorted(fresh(r) for r in rows if fresh(r))
    if not v:
        return {"median_fresh": 0, "p90_fresh": 0, "n": 0, "median_blocks": 0}
    return {"median_fresh": int(statistics.median(v)), "p90_fresh": v[min(len(v) - 1, int(len(v) * .9))], "n": len(v),
            "median_blocks": int(statistics.median([r.get("blocks") or 0 for r in rows if r.get("blocks")] or [0]))}


def sig(kind: str, sev: str, title: str, line: str, look: Iterable[str] = (), href: str | None = None) -> Row:
    return {"kind": kind, "sev": sev, "title": title, "line": line, "look": list(look)[:4], "href": href}


def _reason(why: object) -> str:
    """The reason up to its first ':', '.' or '('."""
    text = str(why or "no reason given")
    cut = min((i for i in (text.find(c) for c in ":.(") if i >= 0), default=len(text))
    return text[:cut][:60]


def lane_out(lanes: Sequence[Row] | None, now: float) -> list[Row]:
    out: list[Row] = []
    for ln in lanes or []:
        name = str(ln.get("name") or "")
        if "CREDIT" in name.upper():  # a credit lane is never used by an unattended run (the subscription lanes are): out is no alarm
            continue
        label = "Codex" if "OPENAI" in name.upper() or "CODEX" in name.upper() else "Claude" if "CLAUDE" in name.upper() else name
        until = ln.get("out_until")
        if until and float(until) > now:
            out.append(
                sig(
                    "lane_out",
                    "red",
                    f"{label} lane out",
                    "out for {} ({}): a slot that needs it pauses or parks".format(dur(float(until) - now), _reason(ln.get("why"))),
                )
            )
            continue
        for u in ln.get("usage") or []:
            if (u.get("used_pct") or 0) >= USAGE_HIGH:
                back = float(u.get("resets_at") or 0) - now
                out.append(sig("lane_high", "amber", "{} {} window at {:d}%".format(label, u.get("window"), int(u["used_pct"])),
                               f"resets in {dur(back)}; until then new work may pause" if back > 0 else "reset time unknown"))
    return out


def park_cluster(passes: Sequence[Row], now: float) -> list[Row]:
    recent = [p for p in passes if p["outcome"] in ("parked", "failed") and now - p["t"] <= CLUSTER_LOOKBACK]
    groups: dict[str, list[Row]] = {}
    for p in recent:
        groups.setdefault(cause(p.get("why")) or "(no reason recorded)", []).append(p)
    out: list[Row] = []
    for c, ps in groups.items():
        ps.sort(key=lambda p: p["t"])
        best = max((sum(1 for q in ps if 0 <= q["t"] - p["t"] <= CLUSTER_WINDOW) for p in ps), default=0)
        if best >= CLUSTER_N:
            out.append(
                sig(
                    "park_cluster",
                    "red",
                    f"{len(ps)} parks, one cause",
                    "{}: {:d} in {}. Is the loop burning slots on it?".format(c, len(ps), dur(ps[-1]["t"] - ps[0]["t"] + 60)),
                    [p["id"] for p in ps][-3:],
                )
            )
    return out


def churn(rows: Sequence[Row], now: float) -> list[Row]:
    hits: list[tuple[int, Row]] = []
    for r in rows:
        if r.get("state") in ("landed", "done") or now - (r.get("updated") or 0) > CHURN_LOOKBACK:
            continue
        why: list[str] = []
        if (r.get("red_checks") or 0) >= CHURN_CHECKS_RED:
            why.append("checks failed {:d}\N{MULTIPLICATION SIGN}".format(int(r["red_checks"])))
        if (r.get("replans") or 0) >= REPLANS:
            why.append("planned {:d}\N{MULTIPLICATION SIGN}: the plan, not the code, is wrong".format(int(r["replans"])))
        if (r.get("sendbacks") or 0) >= SENDBACKS:
            why.append("review sent it back {:d}\N{MULTIPLICATION SIGN}".format(int(r["sendbacks"])))
        if (r.get("longest_check") or 0) >= SLOW_CHECK and (r.get("red_checks") or 0) >= 2:
            why.append("each check round takes up to {}".format(dur(r["longest_check"])))
        if (r.get("blocks") or 0) >= CHURN_BLOCKS and not why:
            why.append("{:d} steps".format(int(r["blocks"])))
        if why:
            share = round(100 * (r.get("checks_secs") or 0) / r["secs"]) if r.get("secs") else 0
            hits.append(
                (
                    r.get("blocks") or 0,
                    sig(
                        "churn",
                        "amber",
                        "{} churning".format(short(r["id"])),
                        "{}, {:d} steps{}".format(
                            ", ".join(why), int(r.get("blocks") or 0), (f", {int(share)}% of its time in checks") if share >= 40 else ""
                        ),
                        [r["id"]],
                    ),
                )
            )
    return [s for _, s in sorted(hits, key=lambda h: -h[0])[:3]]


def token_hogs(rows: Sequence[Row], now: float, med: Row) -> list[Row]:
    floor = max(HOG_FRESH, HOG_TIMES_MEDIAN * med["median_fresh"])
    hogs = sorted((r for r in rows if fresh(r) > floor and now - (r.get("updated") or 0) <= HOG_LOOKBACK), key=lambda r: -fresh(r))
    if not hogs:
        return []
    r = hogs[0]
    x = fresh(r) / med["median_fresh"] if med["median_fresh"] else 0
    more = f" (+{len(hogs) - 1} more)" if len(hogs) > 1 else ""
    return [
        sig(
            "token_hog",
            "amber",
            "{}: {} fresh tokens".format(short(r["id"]), human(fresh(r))),
            "{}\N{MULTIPLICATION SIGN} the median bead ({}); {} with cache, {:d} run{}{}".format(
                (f"{x:.0f}") if x else "?",
                human(med["median_fresh"]),
                human(total(r)),
                int(r.get("runs") or 0),
                "" if r.get("runs") == 1 else "s",
                more,
            ),
            [h["id"] for h in hogs],
        )
    ]


def big_turns(rows: Sequence[Row], now: float) -> list[Row]:
    hit = sorted((r for r in rows if (r.get("big_turn") or 0) >= BIG_TURN and now - (r.get("updated") or 0) <= HOG_LOOKBACK),
                 key=lambda r: -r["big_turn"])
    if not hit:
        return []
    r = hit[0]
    return [
        sig(
            "big_turn",
            "amber",
            "{}: one write step used {} tokens".format(short(r["id"]), human(r["big_turn"])),
            "almost all cache reads: the writer's context is huge and every model call re-reads it{}".format(
                f" (+{len(hit) - 1} more beads)" if len(hit) > 1 else ""
            ),
            [h["id"] for h in hit],
        )
    ]


def ask_aging(asks: Sequence[Row] | None, now: float) -> list[Row]:
    open_ = [a for a in asks or [] if a.get("status", "open") == "open" and not a.get("answered_here")]
    if not open_:
        return []
    def age(a: Row) -> float:
        return now - float(a.get("t") or now)
    old = sorted(open_, key=lambda a: -age(a))
    kinds: dict[str, int] = {}
    for a in open_:
        kinds[a.get("kind") or "ask"] = kinds.get(a.get("kind") or "ask", 0) + 1
    soon = [a for a in open_ if a.get("parks_at") and 0 < float(a["parks_at"]) - now < ASK_PARK_SOON]
    sev = "red" if age(old[0]) > ASK_RED or soon else "amber" if age(old[0]) > ASK_AMBER else "info"
    line = "oldest {}: {}".format(dur(age(old[0])), ", ".join(f"{n} {k}" for k, n in sorted(kinds.items(), key=lambda kv: -kv[1])))
    if soon:
        line += f"; {len(soon)} auto-park within {dur(ASK_PARK_SOON)}"
    return [sig("asks", sev, "{:d} ask{} wait on you".format(len(open_), "" if len(open_) == 1 else "s"), line,
                [a["bead"] for a in old[:3]], href="#asks")]


def looks_waiting(looks: Sequence[Row], now: float) -> list[Row]:
    """Taste items the owner has not answered: they never block the loop, so only age makes them worth a colour."""
    if not looks:
        return []
    old = min((float(ln.get("filed") or now) for ln in looks), default=now)
    sev = "amber" if now - old > ASK_AMBER else "info"
    n = len(looks)
    return [sig("looks", sev, "{:d} look{} wait for you".format(int(n), "" if n == 1 else "s"),
                "good or redo, one click each: the pictures are in the gallery", [ln["bead"] for ln in looks][:3], href="#looks")]


def budget_near_miss(passes: Sequence[Row], now: float) -> list[Row]:
    out: list[tuple[Row, str]] = []
    for p in reversed(passes):
        m = budget_pair(p.get("why") or "")
        if p["outcome"] == "parked" and m and now - p["t"] <= 24 * 3600 and m[0] <= BUDGET_NEAR * m[1]:
            out.append((p, "{}/{} min".format(*m)))
    if not out:
        return []
    return [sig("near_miss", "info", f"{len(out)} over budget by a hair",
                "stopped at {} of the limit: running again is cheap and probably safe".format(", ".join(x for _, x in out[:2])),
                [p["id"] for p, _ in out])]


def stuck(graph_summary: Row | None) -> list[Row]:
    n = (graph_summary or {}).get("stuck") or 0
    return [sig("stuck", "red", "{:d} bead{} held by nothing".format(int(n), "" if n == 1 else "s"),
                "in progress in bd, but no slot runs it: nobody will pick it up")] if n else []


def good(passes: Sequence[Row], rows: Sequence[Row], now: float) -> list[Row]:
    day = [p for p in passes if p["outcome"] == "landed" and now - p["t"] <= 24 * 3600]
    if not day:
        return []
    mins = sorted(p["minutes"] for p in day)
    first = [r for r in rows if r.get("state") in ("landed", "done") and (r.get("runs") or 0) == 1]
    line = f"median {dur(statistics.median(mins) * 60)} per landing"
    if rows and first:
        line += "; {:d} of {:d} finished beads landed on the first run".format(
            len(first), sum(1 for r in rows if r.get("state") in ("landed", "done"))
        )
    return [sig("good", "green", f"{len(day)} landed in 24 h", line, [p["id"] for p in day[-3:]])]


def build(rows: Sequence[Row], passes: Sequence[Row], lanes: Sequence[Row], asks: Sequence[Row], graph_summary: Row | None,
          now: float | None = None, looks: Sequence[Row] = ()) -> Row:
    """rows: task rows (server.api_tasks) of this repo; passes: roadmap passes ({id, outcome, t, minutes, why}); lanes:
    agent-runs lane records; asks: open asks; graph_summary: graph.build()'s summary. -> {signals: [...], stats: {...}}"""
    now = now or time.time()
    med = medians(rows)
    sigs = (
        lane_out(lanes, now)
        + stuck(graph_summary)
        + park_cluster(passes, now)
        + ask_aging(asks, now)
        + looks_waiting(looks, now)
        + churn(rows, now)
        + token_hogs(rows, now, med)
        + big_turns(rows, now)
        + budget_near_miss(passes, now)
        + good(passes, rows, now)
    )
    sigs.sort(key=lambda s: SEVERITY[s["sev"]])
    return {"signals": sigs, "stats": med}
