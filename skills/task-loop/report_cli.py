"""The verbs of tl report and tl lost (the data and its rules are in report.py): parse the window, print the card or the JSON."""

import json
import time
from pathlib import Path

import report

from taskloop.adapters import gitrepo


def mtok(d):
    return "{:.1f}M in ({:.1f}M cached), {:d}k out".format(d["in"] / 1e6, d["cached"] / 1e6, int(d["out"] // 1000))


def print_card(c):
    a = c["asks"]
    print(
        "tl report {}  {} -> {}  (runs overlapping the window: {:d})".format(
            Path(c["repo"]).name, report.stamp(c["since"]), report.stamp(c["until"]), int(c["runs"])
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
        print("  " + report.planner_line(c["planner"]))
    for x in c["crash_list"]:
        print("  crash   {} {}  {}".format(report.stamp(x["t"])[11:], x["bead"], x["why"]))
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


def window(a):
    now = time.time()
    since = report.parse_time(a.since, now) if getattr(a, "since", None) else now - 86400
    until = report.parse_time(a.until, now, forward=True) if getattr(a, "until", None) else now
    return since, until


def cmd_report(a):
    since, until = window(a)
    if getattr(a, "planner", False):
        pre = {x.strip() for x in (getattr(a, "prefix", "") or "").split(",") if x.strip()}
        p = report.planner_stats(since, until, pre)
        if a.json:
            print(json.dumps(p, indent=1, ensure_ascii=False))
        else:
            report.print_planner(p)
        return 0
    repo = gitrepo.repo_root(a.repo)
    c = report.scorecard(repo, since, until, base=report.default_base(repo), alive=report.run_alive)
    c["planner"] = report.planner_stats(since, until, {report.prefix(x["bead"]) for x in c["per_bead"]})
    if a.json:
        print(json.dumps(c, indent=1, ensure_ascii=False))
    else:
        print_card(c)
    return 0 if c["m2"]["pass"] else 1


def cmd_lost(a):
    repo = gitrepo.repo_root(a.repo)
    since = report.parse_time(a.since) if a.since else None
    rows = report.lost_work(repo, since=since, base=report.default_base(repo))
    if a.json:
        print(json.dumps(rows, indent=1, ensure_ascii=False))
    else:
        for x in rows:
            if x["class"] != "landed":
                print("{!s:<9} {!s:<28} {} {}  {}".format(x["class"], x["branch"], x["sha"][:8], report.stamp(x["time"]), x["why"]))
        n = {k: sum(x["class"] == k for x in rows) for k in ("landed", "reclaimed", "pending", "unknown", "lost")}
        print(
            "{:d} lost, {:d} pending, {:d} unknown, {:d} reclaimed, {:d} landed (commits on task/* and wip/* not on the base)".format(
                int(n["lost"]), int(n["pending"]), int(n["unknown"]), int(n["reclaimed"]), int(n["landed"])
            )
        )
    return 1 if any(x["class"] == "lost" for x in rows) else 0
