"""`tl report`: the M2 scorecard over a time window. Reads only: traces.jsonl, the loop's log, engine/*.jsonl, the repo's git refs, bd."""

import contextlib
import json
import statistics
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, NotRequired, TypedDict

from tlkernel import lifecyclematchers as matchers
from tlkernel import paths, runlife, wire
from tlkernel.bead import Comment
from tlkernel.dashhealth import Score
from tlkernel.enums import Outcome, Result
from tlkernel.gitport import Git
from tlkernel.holds import engine_written
from tlkernel.identity import Identity
from tlkernel.ids import BeadId, is_bead_id, loop_key
from tlkernel.kinds import ASKS, PAUSES, Kind, kind_named
from tlkernel.locator import RunLocator
from tlkernel.log import EngineLog, decode
from tlkernel.rowstores import ReleaseResultStore
from tlkernel.runlife import Liveness
from tlkernel.stores import LoopLog
from tlkernel.trace import RunTrace

from taskloop.adapters import beadtools, gitrepo
from taskloop.app.reconcile.lost import lost_work
from taskloop.app.report.inputs import bead_status, landed_of, prefix, read_jsonl, repo_traces
from taskloop.app.report.landphases import land_stats, tries_of
from taskloop.app.report.mainstate import main_state
from taskloop.app.report.planner import input_tokens, planner_line, planner_stats

M2: Final = {"beads": 10, "landed_no_ask": 7}  # at least; lost and crashes must be 0 (docs/roadmap.md)


def typed_log(path: Path) -> list[EngineLog]:
    """The engine log's records; a line that is not one is skipped."""
    out: list[EngineLog] = []
    for d in read_jsonl(path):
        with contextlib.suppress(ValueError):
            out.append(decode(d))
    return out


def crashes(
    repo: str, since: float, until: float, traces: Sequence[RunTrace], cfg: paths.ConfigDir, now: float | None = None
) -> list[dict[str, Any]]:
    """Engine crashes: the loop saw run-task exit with no outcome; a run in the window with no trace whose manifest says `lost`
    (the reconciler: its heartbeat went stale and its process is gone); or a trace closed as an engine fault (an exception the engine
    caught). A run's .stderr is delegate's, where a worker's test tracebacks land too: never read."""
    now = time.time() if now is None else now
    out: dict[Any, dict[str, Any]] = {}
    loop_lines = [i.rec for i in LoopLog(cfg, loop_key(repo)).read_from(0).items]
    for r in loop_lines:
        t = r.t
        if since <= t < until and r.outcome is Result.FAILED and not r.run_id and r.why.startswith("failed: no outcome from run-task"):
            out[f"loop:{r.bead}:{r.t}"] = {"bead": r.bead, "t": t, "run": None, "why": r.why[:200]}
    traced = {str(r.run) for r in traces}
    for b in RunLocator(cfg).of_repo(repo):
        if b.run in traced or not since <= b.started < until or not b.log.exists():
            continue
        bead, t = b.bead, b.started
        if runlife.shown(b.manifest, now) is not Liveness.LOST:
            continue
        reason = b.manifest.reason or runlife.lost_reason(b.manifest, now)
        out[b.run] = {"bead": bead, "t": t, "run": b.run, "why": f"the run is lost: {reason[:120]}"}
    for r in traces:  # the engine caught it and closed (run_once): an engine bug all the same
        if overlaps(r, since, until) and kind_named(r.kind) is Kind.FAULT_ENGINE:
            out[str(r.run)] = {"bead": r.bead, "t": r.started, "run": str(r.run), "why": r.why[:200]}
    return sorted(out.values(), key=lambda c: c["t"])


def overlaps(r: RunTrace, since: float, until: float) -> bool:
    return r.started < until and (r.ended or r.started) >= since


@dataclass(frozen=True)
class Last:
    """How a bead's newest run (or crash) ended: the Kind it recorded, None when it recorded none, and its words."""

    kind: Kind | None
    why: str


def is_ask(run: RunTrace) -> bool:
    """A run that ended on an owner ask: its trace carries one of the ask Kinds."""
    return kind_named(run.kind) in ASKS


def parked_state(last: Last) -> str:
    """The scorecard's state of a bead whose newest run did not land: parked (an ask, the owner's park), paused (a pause, an open
    ask), else failed. A run stopped by a signal is a failure, not a pause."""
    kind = last.kind
    if kind is None or kind is Kind.PAUSE_KILLED:
        return "failed"
    if kind in ASKS or kind is Kind.OWNER_PARK:
        return "parked"
    return "paused" if kind in PAUSES or kind is Kind.WAIT_ASK else "failed"


def answered_asks(run: RunTrace) -> set[str]:
    """Asks a run went on from (its log's 'ask X is answered' notes): the ask came before, maybe before the window."""
    ids: set[str] = set()
    for x in read_jsonl(run.log):
        found = matchers.answered_ask(x.get("text") or "") if x.get("kind") == "note" else ""
        if found:
            ids.add(found)
    return ids


def who_answered(comments: Sequence[Comment], n: int) -> list[str]:
    """For the bead's last n asks: 'supervisor', 'owner' or 'open', from the first person's comment after each."""
    out = []
    asks = [i for i, c in enumerate(comments) if engine_written(c) and c.text.startswith("Ask (engine) ")]
    for i in asks[-n:] if n else []:
        reply = next((c for c in comments[i + 1 :] if not engine_written(c)), None)
        out.append("open" if reply is None else "supervisor" if matchers.supervised(reply.text) else "owner")
    return out + ["unknown"] * (n - len(out))


def pctl(xs: Sequence[float], p: int) -> float:
    xs = sorted(xs)
    if not xs:
        return 0
    k = max(0, -(-len(xs) * p // 100) - 1)
    return xs[k]


def _bead_rows(
    beads: dict[str, dict[str, list[Any]]], comments_of: Callable[[BeadId], Sequence[Comment]]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """(per-bead rows sorted by bead, the ask counts) of {bead: {runs, crashes}}."""
    rows: list[dict[str, Any]] = []
    asks = {"count": 0, "beads": 0, "supervisor": 0, "owner": 0, "open": 0, "unknown": 0}
    for bead, b in beads.items():
        rs: list[RunTrace] = b["runs"]
        n_ask = sum(1 for r in rs if is_ask(r))
        if not n_ask and any(answered_asks(r) for r in rs):
            n_ask = 1  # it went on from an ask raised before the window
        events = [(r.ended or 0, Last(kind_named(r.kind), r.why)) for r in rs] + [
            (c["t"], Last(Kind.FAULT_CRASHED, c["why"])) for c in b["crashes"]
        ]
        last = max(events, key=lambda e: e[0])[1]
        why = last.why
        state = "landed" if any(r.outcome in (Outcome.LANDED, Outcome.DONE) for r in rs) else parked_state(last)
        answers = who_answered(comments_of(bead), n_ask) if n_ask and is_bead_id(bead) else []
        if n_ask:
            asks["count"] += n_ask
            asks["beads"] += 1
            for a in answers:
                asks[a] += 1
        rows.append(
            {
                "bead": bead,
                "state": state,
                "asks": n_ask,
                "answers": answers,
                "runs": len(rs),
                "crashes": len(b["crashes"]),
                "minutes": round(sum((r.ended - r.started) / 60 for r in rs), 1),
                "rounds": sum(r.stats.rounds for r in rs),
                "replans": sum(r.stats.replans for r in rs),
                "why": why[:160] if state != "landed" else "",
            }
        )
    rows.sort(key=lambda x: x["bead"])
    return rows, asks


def _tokens(runs: Sequence[RunTrace]) -> dict[str, dict[str, dict[str, int]]]:
    """{account|role: {name: {in, cached, out}}} over the sessions of the runs."""
    tokens = {"account": {}, "role": {}}
    for r in runs:
        for s in r.sessions:
            tk = {"in": s.tokens.in_, "cached": s.tokens.cached, "out": s.tokens.out}
            if not any(tk.values()):
                continue
            fam = s.family or (s.account or "?").split("_")[0].lower()
            for key, name in (("account", fam), ("role", s.role or "?")):
                d = tokens[key].setdefault(name, {"in": 0, "cached": 0, "out": 0})
                d["in"] += input_tokens(tk)
                d["cached"] += tk["cached"]
                d["out"] += tk["out"]
    return tokens


class _Count(TypedDict):
    count: int


_M2 = TypedDict("_M2", {"pass": bool})  # `pass` is a keyword


class _Main(TypedDict):
    red: bool


class _Card(TypedDict):
    since: float
    until: float
    beads: int
    landed: int
    landed_no_ask: int
    asks: _Count
    lost: int
    crashes: int
    m2: _M2
    main: NotRequired[_Main]
    runs: NotRequired[int]
    kinds: NotRequired[dict[str, int]]


def score_of(card: Mapping[str, object]) -> Score:
    """The dashboard strip's numbers of a scorecard: nothing is recounted, so the strip and `tl report` cannot disagree."""
    c: _Card = wire.load(_Card, card)
    return Score(
        since=c["since"],
        until=c["until"],
        beads=c["beads"],
        landed=c["landed"],
        landed_no_ask=c["landed_no_ask"],
        asks=c["asks"]["count"],
        lost=c["lost"],
        crashes=c["crashes"],
        m2_pass=c["m2"]["pass"],
        main_red=c.get("main", {"red": False})["red"],
        retries=max(0, c.get("runs", c["beads"]) - c["beads"]),
        kinds=c.get("kinds", {}),
    )


def scorecard(
    repo: str,
    since: float,
    until: float,
    base: str,
    comments_of: Callable[[BeadId], Sequence[Comment]] | None = None,
    status_of: Callable[[BeadId], str | None] | None = None,
    now: float | None = None,
    *,
    git: Git,
    who: Identity,
) -> dict[str, Any]:
    repo = gitrepo.repo_root(repo)  # the loop keys its log by this path
    comments_of = comments_of or beadtools.bd_store(who.actor, repo).comments
    book = repo_traces(repo, git, who.config)
    traces = book.runs
    runs = sorted([r for r in traces if overlaps(r, since, until)], key=lambda r: r.started)
    crash = crashes(repo, since, until, traces, who.config, now=now)
    beads: dict[str, dict[str, list[Any]]] = {}
    for r in runs:
        beads.setdefault(r.bead, {"runs": [], "crashes": []})["runs"].append(r)
    for c in crash:
        beads.setdefault(c["bead"], {"runs": [], "crashes": []})["crashes"].append(c)
    rows, asks = _bead_rows(beads, comments_of)
    tokens = _tokens(runs)
    lost = [
        x
        for x in lost_work(
            repo, base, status_of or (lambda b: bead_status(b, repo, who)), traces, git, lambda b: landed_of(b, repo, who), since=since
        )
        if x["class"] in ("lost", "pending", "unknown")
    ]
    mins = [x["minutes"] for x in rows if x["runs"]]
    c: dict[str, Any] = {
        "repo": repo,
        "since": since,
        "until": until,
        "beads": len(rows),
        "landed": sum(x["state"] == "landed" for x in rows),
        "landed_no_ask": sum(x["state"] == "landed" and not x["asks"] for x in rows),
        "parked": sum(x["state"] == "parked" for x in rows),
        "paused": sum(x["state"] == "paused" for x in rows),
        "failed": sum(x["state"] == "failed" for x in rows),
        "asks": asks,
        "crashes": len(crash),
        "crash_list": crash,
        "lost": sum(x["class"] == "lost" for x in lost),
        "lost_list": [x for x in lost if x["class"] == "lost"],
        "pending_list": [x for x in lost if x["class"] in ("pending", "unknown")],
        "minutes": {"median": round(statistics.median(mins), 1) if mins else 0, "p90": pctl(mins, 90)},
        "rounds": sum(x["rounds"] for x in rows),
        "replans": sum(x["replans"] for x in rows),
        "land": land_stats([t for r in runs if r.log for t in tries_of(typed_log(Path(r.log)))]),
        "main": main_state(git, repo, base, since, ReleaseResultStore(who.config).get()),
        "tokens": tokens,
        "runs": len(runs),
        "kinds": dict(Counter(r.kind for r in runs if r.kind)),
        "per_bead": rows,
        "skipped_traces": book.skipped,
    }
    checks = {
        "beads": {"value": c["beads"], "want": ">={:d}".format(M2["beads"]), "ok": c["beads"] >= M2["beads"]},
        "landed_no_ask": {
            "value": c["landed_no_ask"],
            "want": ">={:d}".format(M2["landed_no_ask"]),
            "ok": c["landed_no_ask"] >= M2["landed_no_ask"],
        },
        "lost": {"value": c["lost"], "want": "0", "ok": c["lost"] == 0},
        "crashes": {"value": c["crashes"], "want": "0", "ok": c["crashes"] == 0},
    }
    c["m2"] = {"pass": all(v["ok"] for v in checks.values()), "checks": checks}
    return c


def report(repo: str, base: str, since: float, until: float, *, as_json: bool, git: Git, who: Identity) -> int:
    c = scorecard(repo, since, until, base=base, git=git, who=who)
    c["planner"] = planner_stats(who.config, since, until, {prefix(x["bead"]) for x in c["per_bead"]})
    if as_json:
        print(json.dumps(c, indent=1, ensure_ascii=False))
    else:
        print_card(c)
    return 0 if c["m2"]["pass"] else 1


def stamp(t: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t))


def mtok(d: dict[str, float]) -> str:
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
    if c["land"]["tries"]:
        land = c["land"]
        med = "  ".join(f"{k} {v:.0f}s" for k, v in land["median_s"].items())
        why = ", ".join(f"{k} {n}" for k, n in land["causes"].items()) or "-"
        print(f"  land    {land['tries']} tries, {land['retried']} retried ({why})  median {med}")
    print(
        "  minutes per bead: median {}, p90 {}   fix rounds {:d}   replans {:d}".format(
            c["minutes"]["median"], c["minutes"]["p90"], int(c["rounds"]), int(c["replans"])
        )
    )
    for key in ("account", "role"):
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
    if c.get("kinds"):
        print("  outcomes " + ", ".join(f"{k} {n}" for k, n in sorted(c["kinds"].items(), key=lambda kv: -kv[1])))
    main = c.get("main", {"red": False, "reverts": []})
    reverted = ", ".join(f"{x['sha'][:8]} {x['subject'][:50]}" for x in main["reverts"])
    why = [x for x in (f"reverted {reverted}" if reverted else "", "the last release gate failed" if main.get("gate_red") else "") if x]
    print("  main    {}".format("RED: " + "; ".join(why) if main["red"] else "green"))
    bad = ["{} {} (want {})".format(k, v["value"], v["want"]) for k, v in c["m2"]["checks"].items() if not v["ok"]]
    print("M2 {}{}".format("PASS" if c["m2"]["pass"] else "FAIL", ": " + "; ".join(bad) if bad else ""))


def print_lost(rows: list[dict[str, Any]], *, as_json: bool) -> int:
    if as_json:
        print(json.dumps(rows, indent=1, ensure_ascii=False))
    else:
        for x in rows:
            if x["class"] != "landed":
                print("{!s:<9} {!s:<28} {} {}  {}".format(x["class"], x["branch"], x["sha"][:8], stamp(x["time"]), x["why"]))
        n = {k: sum(x["class"] == k for x in rows) for k in ("landed", "reclaimed", "superseded", "pending", "unknown", "lost")}
        print(
            (
                "{:d} lost, {:d} pending, {:d} unknown, {:d} reclaimed, {:d} superseded, {:d} landed"
                " (commits on task/* and wip/* not on the base)"
            ).format(int(n["lost"]), int(n["pending"]), int(n["unknown"]), int(n["reclaimed"]), int(n["superseded"]), int(n["landed"]))
        )
    return 1 if any(x["class"] == "lost" for x in rows) else 0
