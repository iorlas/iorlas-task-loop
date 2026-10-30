"""The verbs of tl report, tl lost and tl reflect digest (the data and its rules are in app/report): parse the window, print the card,
the planner table or the JSON."""

import json
import time
from pathlib import Path
from typing import Any

from taskloop.app.launch import repos
from taskloop.app.reconcile import lost as lostwork
from taskloop.app.report import card as cards
from taskloop.app.report import planner, reflect
from taskloop.app.report.inputs import bead_status, prefix, repo_traces
from taskloop.app.report.window import digest_time, since_of, window
from taskloop.contracts.env import Env
from taskloop.contracts.identity import Identity
from taskloop.contracts.ports import Git


def stamp(t: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t))


def mtok(d: dict[str, Any]) -> str:
    return "{:.1f}M in ({:.1f}M cached), {:d}k out".format(d["in"] / 1e6, d["cached"] / 1e6, int(d["out"] // 1000))


def print_card(c: dict[str, Any]) -> None:
    a = c["asks"]
    print(
        "tl report {}  {} -> {}  (runs overlapping the window: {:d})".format(
            Path(c["repo"]).name, stamp(c["since"]), stamp(c["until"]), int(c["runs"])
        )
    )
    print(
        "  beads {:d}   landed {:d}   landed with no ask {:d}   parked {:d}   paused {:d}   failed {:d}".format(
            int(c["beads"]), int(c["landed"]), int(c["landed_no_ask"]), int(c["parked"]), int(c["paused"]), int(c["failed"])
        )
    )
    print(
        "  asks {:d} on {:d} beads: owner {:d}, supervisor {:d}, open {:d}{}".format(
            int(a["count"]),
            int(a["beads"]),
            int(a["owner"]),
            int(a["supervisor"]),
            int(a["open"]),
            ", unknown {:d}".format(int(a["unknown"])) if a["unknown"] else "",
        )
    )
    print("  crashes {:d}   lost {:d}   pending branches {:d}".format(int(c["crashes"]), int(c["lost"]), len(c["pending_list"])))
    print(
        "  minutes per bead: median {}, p90 {}   fix rounds {:d}   replans {:d}".format(
            c["minutes"]["median"], c["minutes"]["p90"], int(c["rounds"]), int(c["replans"])
        )
    )
    for key in ("lane", "role"):
        for name, d in sorted(c["tokens"][key].items()):
            print(f"  tokens {key!s:<5} {name!s:<9} {mtok(d)}")
    if c.get("planner") and c["planner"]["calls"]:
        print("  " + planner_line(c["planner"]))
    for x in c["crash_list"]:
        print("  crash   {} {}  {}".format(stamp(x["t"])[11:], x["bead"], x["why"]))
    for x in c["lost_list"]:
        print("  lost    {} {} {}  {}".format(x["branch"], x["sha"][:8], x["subject"][:50], x["why"]))
    for x in c["per_bead"]:
        if x["state"] != "landed" or x["asks"]:
            print(
                "  {!s:<7} {}{}{}".format(
                    x["state"],
                    x["bead"],
                    "  asks: " + ",".join(x["answers"]) if x["asks"] else "",
                    "  " + x["why"][:100] if x["why"] else "",
                )
            )
    bad = ["{} {} (want {})".format(k, v["value"], v["want"]) for k, v in c["m2"]["checks"].items() if not v["ok"]]
    print("M2 {}{}".format("PASS" if c["m2"]["pass"] else "FAIL", ": " + "; ".join(bad) if bad else ""))


def cmd_report(a: Any, env: Env, git: Git, who: Identity) -> int:
    since, until = window(getattr(a, "since", None), getattr(a, "until", None), time.time())
    if getattr(a, "planner", False):
        pre = {x.strip() for x in (getattr(a, "prefix", "") or "").split(",") if x.strip()}
        p = planner.planner_stats(since, until, pre)
        if a.json:
            print(json.dumps(p, indent=1, ensure_ascii=False))
        else:
            print_planner(p)
        return 0
    repo = repos.repo_root(a.repo)
    c = cards.scorecard(repo, since, until, base=repos.default_base(repo, git), git=git, who=who)
    c["planner"] = planner.planner_stats(since, until, {prefix(x["bead"]) for x in c["per_bead"]})
    if a.json:
        print(json.dumps(c, indent=1, ensure_ascii=False))
    else:
        print_card(c)
    return 0 if c["m2"]["pass"] else 1


def cmd_lost(a: Any, env: Env, git: Git, who: Identity) -> int:
    repo = repos.repo_root(a.repo)
    since = since_of(a.since, time.time())
    rows = lostwork.lost_work(repo, repos.default_base(repo, git), lambda b: bead_status(b, repo, who), repo_traces(repo, git).runs, git,
        since=since)
    if a.json:
        print(json.dumps(rows, indent=1, ensure_ascii=False))
    else:
        for x in rows:
            if x["class"] != "landed":
                print("{!s:<9} {!s:<28} {} {}  {}".format(x["class"], x["branch"], x["sha"][:8], stamp(x["time"]), x["why"]))
        n = {k: sum(x["class"] == k for x in rows) for k in ("landed", "reclaimed", "superseded", "pending", "unknown", "lost")}
        print(
            ("{:d} lost, {:d} pending, {:d} unknown, {:d} reclaimed, {:d} superseded, {:d} landed"
             " (commits on task/* and wip/* not on the base)").format(
                int(n["lost"]), int(n["pending"]), int(n["unknown"]), int(n["reclaimed"]), int(n["superseded"]), int(n["landed"])
            )
        )
    return 1 if any(x["class"] == "lost" for x in rows) else 0


def planner_line(p: dict[str, Any]) -> str:
    return (
        "planner: {:d} calls on {:d} beads: {:d} first plans, {:d} full plans again, {:d} amends, {:d} check send-backs, {:d} other; "
        "input {:.1f}M, median {:d}k per call"
    ).format(
        int(p["calls"]),
        int(p["beads"]),
        int(p["first"]),
        int(p["again"]),
        int(p["amend"]),
        int(p["back"]),
        int(p["other"]),
        p["input"] / 1e6,
        int(p["median_input"] // 1000),
    )


def print_planner(p: dict[str, Any]) -> None:
    print(planner_line(p))
    print(
        "  {!s:<26} {!s:>5} {!s:>5} {!s:>5} {!s:>5} {!s:>5} {!s:>5} {!s:>9}".format(
            "bead", "calls", "first", "again", "amend", "back", "other", "input M"
        )
    )
    for x in sorted(p["per_bead"], key=lambda x: -x["input"]):
        print(
            "  {!s:<26} {:5d} {:5d} {:5d} {:5d} {:5d} {:5d} {:9.2f}".format(
                x["bead"],
                int(x["calls"]),
                int(x["first"]),
                int(x["again"]),
                int(x["amend"]),
                int(x["back"]),
                int(x["other"]),
                x["input"] / 1e6,
            )
        )



def cmd_reflect(a: Any, env: Env, git: Git, who: Identity) -> int:
    now = time.time()

    def at(text: str | None, default: float) -> float:
        return digest_time(text, now) if text else default

    st = reflect.read_state()
    last = float(st.get("until") or 0) or now - reflect.DAY  # the last digest's end, 3 days back at most
    since = at(a.since, max(now - 3 * reflect.DAY, last))
    d = reflect.digest(who, since, at(a.until, now), dry=a.dry_run)
    if not a.dry_run and not a.since and not d.get("busy"):
        st = reflect.read_state()
        st["until"] = now
        reflect.write_state(st)
    if a.json:
        print(json.dumps(d, indent=1, default=str))
        return 0
    print(
        "{:d} bad items in {:d} causes, {:d} recurring{}".format(
            int(d["items"]), len(d["clusters"]), len(d["actions"]), " (dry run)" if a.dry_run else ""
        )
    )
    for x in d["actions"]:
        print(
            "  {!s:<9} [{}] {} -> {} {} ({:d} runs)".format(
                x["action"], x["cause"], x["title"][:60], Path(x["repo"]).name or "?", x["bead"] or "-", len(x["runs"])
            )
        )
    return 0

