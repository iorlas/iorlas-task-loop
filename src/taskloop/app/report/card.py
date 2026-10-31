"""`tl report`: the M2 scorecard over a time window. Reads only: traces.jsonl, the loop's log, engine/*.jsonl, the repo's git refs, bd."""
import contextlib
import statistics
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from taskloop.adapters import beadtools, gitrepo
from taskloop.app.asks import intake
from taskloop.app.reconcile.lost import lost_work
from taskloop.app.report.inputs import bead_status, read_jsonl, repo_traces
from taskloop.app.report.planner import input_tokens
from taskloop.contracts import paths
from taskloop.contracts.bead import Comment
from taskloop.contracts.enums import Outcome, Result
from taskloop.contracts.identity import Identity
from taskloop.contracts.ids import BeadId, is_bead_id, loop_key
from taskloop.contracts.kinds import ASKS, PAUSES, Kind, kind_named
from taskloop.contracts.locator import RunLocator
from taskloop.contracts.log import Beat, EngineLog, decode
from taskloop.contracts.ports import Git
from taskloop.contracts.runlife import Liveness, liveness
from taskloop.contracts.stores import LoopLog
from taskloop.contracts.trace import RunTrace
from taskloop.domain.report import matchers

M2: Final = {"beads": 10, "landed_no_ask": 7}  # at least; lost and crashes must be 0 (docs/roadmap.md)

def typed_log(path: Path) -> list[EngineLog]:
    """The engine log's records; a line that is not one is skipped."""
    out: list[EngineLog] = []
    for d in read_jsonl(path):
        with contextlib.suppress(ValueError):
            out.append(decode(d))
    return out


def crashes(repo: str, since: float, until: float, traces: Sequence[RunTrace], cfg: paths.ConfigDir,
            now: float | None = None) -> list[dict[str, Any]]:
    """Engine crashes: the loop saw run-task exit with no outcome; an engine log in the window with no trace that reads `crashed`
    (runlife.liveness: no close, and no record for CRASHED_AFTER); or a trace closed as an engine fault (an exception the engine
    caught). A run's .stderr is route.py's, where a worker's test tracebacks land too: never read."""
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
        bead, t, f = b.bead, b.started, b.log
        recs = typed_log(f)
        if liveness(recs, now) is not Liveness.CRASHED:
            continue
        last = getattr(next((r for r in reversed(recs) if not isinstance(r, Beat)), None), "text", "")
        out[b.run] = {"bead": bead, "t": t, "run": b.run, "why": f"the engine log ends with no close: {last[:120]}"}
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
    return xs[k]


def _bead_rows(beads: dict[str, dict[str, list[Any]]],
               comments_of: Callable[[BeadId], Sequence[Comment]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """(per-bead rows sorted by bead, the ask counts) of {bead: {runs, crashes}}."""
    rows: list[dict[str, Any]] = []
    asks = {"count": 0, "beads": 0, "supervisor": 0, "owner": 0, "open": 0, "unknown": 0}
    for bead, b in beads.items():
        rs: list[RunTrace] = b["runs"]
        n_ask = sum(1 for r in rs if is_ask(r))
        if not n_ask and any(answered_asks(r) for r in rs):
            n_ask = 1  # it went on from an ask raised before the window
        events = [(r.ended or 0, Last(kind_named(r.kind), r.why)) for r in rs] + [
            (c["t"], Last(Kind.FAULT_CRASHED, c["why"])) for c in b["crashes"]]
        last = max(events, key=lambda e: e[0])[1]
        why = last.why
        state = "landed" if any(r.outcome in (Outcome.LANDED, Outcome.DONE) for r in rs) else parked_state(last)
        answers = who_answered(comments_of(bead), n_ask) if n_ask and is_bead_id(bead) else []
        if n_ask:
            asks["count"] += n_ask
            asks["beads"] += 1
            for a in answers:
                asks[a] += 1
        rows.append({"bead": bead, "state": state, "asks": n_ask, "answers": answers, "runs": len(rs),
                     "crashes": len(b["crashes"]),
                     "minutes": round(sum((r.ended - r.started) / 60 for r in rs), 1),
                     "rounds": sum(r.stats.rounds for r in rs),
                     "replans": sum(r.stats.replans for r in rs),
                     "why": why[:160] if state != "landed" else ""})
    rows.sort(key=lambda x: x["bead"])
    return rows, asks


def _tokens(runs: Sequence[RunTrace]) -> dict[str, dict[str, dict[str, int]]]:
    """{lane|role: {name: {in, cached, out}}} over the sessions of the runs."""
    tokens = {"lane": {}, "role": {}}
    for r in runs:
        for s in r.sessions:
            tk = {"in": s.tokens.in_, "cached": s.tokens.cached, "out": s.tokens.out}
            if not any(tk.values()):
                continue
            fam = s.family or (s.lane or "?").split("_")[0].lower()
            for key, name in (("lane", "codex" if fam == "openai" else fam), ("role", s.role or "?")):
                d = tokens[key].setdefault(name, {"in": 0, "cached": 0, "out": 0})
                d["in"] += input_tokens(tk)
                d["cached"] += tk["cached"]
                d["out"] += tk["out"]
    return tokens


def scorecard(repo: str, since: float, until: float, base: str, comments_of: Callable[[BeadId], Sequence[Comment]] | None = None,
              status_of: Callable[[BeadId],
                  str | None] | None = None, now: float | None = None, *, git: Git, who: Identity) -> dict[str, Any]:
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
    lost = [x for x in lost_work(repo, base, status_of or (lambda b: bead_status(b, repo, who)), traces, git, who.config, since=since)
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
         "tokens": tokens, "runs": len(runs), "per_bead": rows, "skipped_traces": book.skipped}
    checks = {"beads": {"value": c["beads"], "want": ">={:d}".format(M2["beads"]), "ok": c["beads"] >= M2["beads"]},
              "landed_no_ask": {"value": c["landed_no_ask"], "want": ">={:d}".format(M2["landed_no_ask"]),
                                "ok": c["landed_no_ask"] >= M2["landed_no_ask"]},
              "lost": {"value": c["lost"], "want": "0", "ok": c["lost"] == 0},
              "crashes": {"value": c["crashes"], "want": "0", "ok": c["crashes"] == 0}}
    c["m2"] = {"pass": all(v["ok"] for v in checks.values()), "checks": checks}
    return c

