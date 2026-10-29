"""`tl report`: the M2 scorecard over a time window. Reads only: traces.jsonl, the loop's log, engine/*.jsonl, the repo's git refs, bd."""
import statistics
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Final

from taskloop.adapters import beadtools, gitrepo, ident
from taskloop.app.asks import intake
from taskloop.app.report.inputs import prefix, read_jsonl, repo_traces, run_alive
from taskloop.app.report.lost import lost_work
from taskloop.app.report.planner import input_tokens
from taskloop.contracts import paths
from taskloop.contracts.bead import Comment
from taskloop.contracts.ids import loop_key
from taskloop.domain.report import matchers

M2: Final = {"beads": 10, "landed_no_ask": 7}  # at least; lost and crashes must be 0 (docs/roadmap.md)
QUIET_MIN = 30  # an engine log with no close and no trace, untouched this long and with no live run-task: a crash


def crashes(repo: str, since: float, until: float, traces: list[dict[str, Any]], alive: Callable[[str], bool | None] | None = None,
            now: float | None = None) -> list[dict[str, Any]]:
    """Engine crashes: the loop saw run-task exit with no outcome; an engine log in the window with no close record and
    no trace, quiet for QUIET_MIN and with no live run-task; or a trace closed as 'failed: engine error' (an exception
    the engine caught). A run's .stderr is route.py's, where a worker's test tracebacks land too: never read."""
    alive = alive or run_alive
    now = time.time() if now is None else now
    out: dict[Any, dict[str, Any]] = {}
    log = paths.ConfigDir(ident.config_dir()).loop_log(loop_key(repo))
    for r in read_jsonl(log):
        try:
            t = time.mktime(time.strptime(r.get("ts") or "", "%Y-%m-%dT%H:%M:%S"))
        except ValueError:
            continue
        if since <= t < until and r.get("outcome") == "failed" and not r.get("trace") and \
                (r.get("why") or "").startswith("failed: no outcome from run-task"):
            key = "loop:{}:{}".format(r.get("bead"), r.get("ts"))
            out[key] = {"bead": r.get("bead"), "t": t, "run": None, "why": (r.get("why") or "")[:200]}
    traced = {r.get("run") for r in traces} | {Path(r["log"]).stem for r in traces if r.get("log")}
    prefixes = {prefix(r.get("bead")) for r in traces} | {prefix(r.get("bead")) for r in read_jsonl(log)}
    for f in sorted((ident.config_dir() / "engine").glob("*.jsonl")):
        parts = matchers.split_stem(f.stem)
        if not parts or f.stem in traced or prefix(parts[0]) not in prefixes:
            continue
        bead = parts[0]
        t = matchers.stem_time(parts[1])
        if not since <= t < until:
            continue
        recs = read_jsonl(f)
        if any(x.get("kind") == "close" for x in recs):
            continue
        try:
            quiet = (now - f.stat().st_mtime) / 60
        except OSError:
            continue
        live = alive(bead)
        if live or (live is None and quiet < QUIET_MIN):
            continue
        last = (recs[-1].get("text") or "") if recs else ""
        out[f.stem] = {"bead": bead, "t": t, "run": f.stem, "why": f"the engine log ends with no close: {last[:120]}"}
    for r in traces:  # the engine caught it and closed (engine.py: Engine.run): an engine bug all the same
        if overlaps(r, since, until) and (r.get("why") or "").startswith("failed: engine error"):
            out[r.get("run")] = {"bead": r.get("bead"), "t": r.get("started") or 0, "run": r.get("run"),
                                 "why": (r.get("why") or "")[:200]}
    return sorted(out.values(), key=lambda c: c["t"])


def overlaps(r: dict[str, Any], since: float, until: float) -> bool:
    return (r.get("started") or 0) < until and (r.get("ended") or r.get("started") or 0) >= since


def is_ask(run: dict[str, Any]) -> bool:
    """A run that ended on an owner ask: its trace carries the outcome Kind (ask_decision, ask_stuck, ask_budget, ask_ticket)."""
    return str(run.get("kind") or "").startswith("ask_")


def answered_asks(run: dict[str, Any]) -> set[str]:
    """Asks a run went on from (its log's 'ask X is answered' notes): the ask came before, maybe before the window."""
    ids: set[str] = set()
    for x in read_jsonl(run.get("log") or ""):
        found = matchers.answered_ask(x.get("text") or "") if x.get("kind") == "note" else ""
        if found:
            ids.add(found)
    return ids


def who_answered(comments: Sequence[Comment], n: int) -> list[str]:
    """For the bead's last n asks: 'supervisor', 'owner' or 'open', from the first person's comment after each."""
    out = []
    asks = [i for i, c in enumerate(comments) if c.text.startswith("Ask (engine) ")]
    for i in asks[-n:] if n else []:
        reply = next((c for c in comments[i + 1:] if not intake.engine_written(c.text)), None)
        out.append("open" if reply is None else "supervisor" if matchers.supervised(reply.text) else "owner")
    return out + ["unknown"] * (n - len(out))


def pctl(xs: Sequence[float], p: int) -> float:
    xs = sorted(xs)
    if not xs:
        return 0
    k = max(0, -(-len(xs) * p // 100) - 1)
    return xs[int(k)]


def _bead_rows(beads: dict[str, dict[str, list[dict[str, Any]]]],
               comments_of: Callable[[str], Sequence[Comment]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """(per-bead rows sorted by bead, the ask counts) of {bead: {runs, crashes}}."""
    rows: list[dict[str, Any]] = []
    asks = {"count": 0, "beads": 0, "supervisor": 0, "owner": 0, "open": 0, "unknown": 0}
    for bead, b in beads.items():
        rs = b["runs"]
        n_ask = sum(1 for r in rs if r.get("outcome") == "blocked" and is_ask(r))
        if not n_ask and any(answered_asks(r) for r in rs):
            n_ask = 1  # it went on from an ask raised before the window
        events = [(r.get("ended") or 0, r) for r in rs] + [(c["t"], {"outcome": "failed", "why": c["why"]})
                                                            for c in b["crashes"]]
        last = max(events, key=lambda e: e[0])[1]
        why = last.get("why") or ""
        if any(r.get("outcome") in ("landed", "done") for r in rs):
            state = "landed"
        elif last.get("outcome") == "blocked" and is_ask(last):
            state = "parked"
        elif last.get("outcome") == "blocked" and why.startswith(("paused:", "waiting:")):
            state = "paused"
        else:
            state = "failed"
        answers = who_answered(comments_of(bead), n_ask) if n_ask else []
        if n_ask:
            asks["count"] += n_ask
            asks["beads"] += 1
            for a in answers:
                asks[a] += 1
        rows.append({"bead": bead, "state": state, "asks": n_ask, "answers": answers, "runs": len(rs),
                     "crashes": len(b["crashes"]),
                     "minutes": round(sum(((r.get("ended") or 0) - (r.get("started") or 0)) / 60 for r in rs), 1),
                     "rounds": sum((r.get("stats") or {}).get("rounds") or 0 for r in rs),
                     "replans": sum((r.get("stats") or {}).get("replans") or 0 for r in rs),
                     "why": why[:160] if state != "landed" else ""})
    rows.sort(key=lambda x: x["bead"])
    return rows, asks


def _tokens(runs: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, int]]]:
    """{lane|role: {name: {in, cached, out}}} over the sessions of the runs."""
    tokens = {"lane": {}, "role": {}}
    for r in runs:
        for s in r.get("sessions") or []:
            tk = s.get("tokens") or {}
            if not any(tk.values()):
                continue
            fam = s.get("family") or (s.get("lane") or "?").split("_")[0].lower()
            for key, name in (("lane", "codex" if fam == "openai" else fam), ("role", s.get("role") or "?")):
                d = tokens[key].setdefault(name, {"in": 0, "cached": 0, "out": 0})
                d["in"] += input_tokens(tk)
                d["cached"] += int(tk.get("cached") or 0)
                d["out"] += int(tk.get("out") or 0)
    return tokens


def scorecard(repo: str, since: float, until: float, base: str, comments_of: Callable[[str], Sequence[Comment]] | None = None,
              status_of: Callable[[str], str | None] | None = None, alive: Callable[[str], bool | None] | None = None,
              now: float | None = None) -> dict[str, Any]:
    repo = gitrepo.repo_root(repo)  # the loop keys its log by this path
    comments_of = comments_of or beadtools.bd_store(repo).comments
    traces = repo_traces(repo)
    runs = sorted([r for r in traces if overlaps(r, since, until)], key=lambda r: r.get("started") or 0)
    crash = crashes(repo, since, until, traces, alive=alive, now=now)
    beads: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for r in runs:
        beads.setdefault(r["bead"], {"runs": [], "crashes": []})["runs"].append(r)
    for c in crash:
        beads.setdefault(c["bead"], {"runs": [], "crashes": []})["crashes"].append(c)
    rows, asks = _bead_rows(beads, comments_of)
    tokens = _tokens(runs)
    lost = [x for x in lost_work(repo, since=since, base=base, status_of=status_of, traces=traces)
            if x["class"] in ("lost", "pending", "unknown")]
    mins = [x["minutes"] for x in rows if x["runs"]]
    c: dict[str, Any] = {"repo": repo, "since": since, "until": until, "beads": len(rows),
         "landed": sum(x["state"] == "landed" for x in rows),
         "landed_no_ask": sum(x["state"] == "landed" and not x["asks"] for x in rows),
         "parked": sum(x["state"] == "parked" for x in rows), "paused": sum(x["state"] == "paused" for x in rows),
         "failed": sum(x["state"] == "failed" for x in rows), "asks": asks,
         "crashes": len(crash), "crash_list": crash,
         "lost": sum(x["class"] == "lost" for x in lost), "lost_list": [x for x in lost if x["class"] == "lost"],
         "pending_list": [x for x in lost if x["class"] in ("pending", "unknown")],
         "minutes": {"median": round(statistics.median(mins), 1) if mins else 0, "p90": pctl(mins, 90)},
         "rounds": sum(x["rounds"] for x in rows), "replans": sum(x["replans"] for x in rows),
         "tokens": tokens, "runs": len(runs), "per_bead": rows}
    checks = {"beads": {"value": c["beads"], "want": ">={:d}".format(int(M2["beads"])), "ok": c["beads"] >= M2["beads"]},
              "landed_no_ask": {"value": c["landed_no_ask"], "want": ">={:d}".format(int(M2["landed_no_ask"])),
                                "ok": c["landed_no_ask"] >= M2["landed_no_ask"]},
              "lost": {"value": c["lost"], "want": "0", "ok": c["lost"] == 0},
              "crashes": {"value": c["crashes"], "want": "0", "ok": c["crashes"] == 0}}
    c["m2"] = {"pass": all(v["ok"] for v in checks.values()), "checks": checks}
    return c

