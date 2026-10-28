"""Engine logs -> the task timeline the dashboard draws: a run is a chain of blocks (one step + one worker call), each block
entered by an arrow that says why the run moved there. It reads the typed EngineLog records (taskloop.contracts.log) as they
are: no row format of its own, no regex."""

import json
import time
from pathlib import Path
from typing import Final

from taskloop.contracts import log as rec
from taskloop.contracts.paths import ConfigDir
from taskloop_dash import jsonl
from taskloop_dash.cache import FileCache
from taskloop_dash.views import arrows
from taskloop_dash.views.names import FAMILY, bead_of, lane_name, nice_model, run_name, when
from taskloop_dash.views.nodes import nodes_of

STAGED = ("write", "checks", "review")
RESULT: Final = {  # a step's outcome -> status colour
    "green": "ok",
    "clean": "ok",
    "landed": "ok",
    "done": "ok",
    "settled": "ok",
    "accepted": "ok",
    "red": "fail",
    "gate red": "fail",
    "conflict": "fail",
    "wrong": "fail",
    "failed": "fail",
    "stopped": "fail",
    "sent back": "warn",
    "reviewed": "warn",
    "rejected": "warn",
    "open": "ask",
    "asks": "ask",
    "paused": "wait",
    "lane_out": "wait",
    "waiting": "wait",
}


def read(path: str, cache: FileCache | None = None) -> list:
    """The log's records, re-read only when the file changed."""
    return cache.get(path, jsonl.records, []) if cache else jsonl.records(path)


def label_of(n: dict, k: int = 0) -> str:
    step, m = n["step"], n["meta"]
    if step == "write":
        return f"Fix {m['fix']} · write {m.get('write') or 1}" if m.get("fix") else f"Write {m.get('write') or 1}"
    if step == "land":
        return "Land" if (m.get("try") or 1) == 1 else f"Land (try {m['try']})"
    return {"plan": "Plan", "replan": "Re-plan", "checks": "Checks", "review": "Review", "verify": "Verify"}.get(step, step.capitalize())


def who_of(n: dict, s: dict | None) -> dict:
    if n["step"] in ("checks", "land", "reset", "close"):
        return {"family": "engine", "name": "Engine", "model": "", "effort": "", "lane": "", "resumed": False, "fallback": "", "flag": ""}
    s = s or {}
    fam = s.get("family") or ""
    name = lane_name(s.get("lane") or "", fam)
    fam = fam or {"Codex": "openai", "Claude": "claude"}.get(name, "")
    flag = s.get("flag") or ""
    return {
        "family": fam,
        "name": name or ("" if n["step"] == "write" else "?"),
        "model": s.get("model") or "",
        "effort": s.get("effort") or "",
        "lane": s.get("lane") or "",
        "resumed": bool(s.get("resume")),
        "flag": flag,
        "fallback": {"same_family": "same family as the writer", "degraded": "not the usual lane"}.get(flag, ""),
    }


def session_result(s: dict | None) -> dict | None:
    st = (s or {}).get("status") or ""
    if not s or st == "done":
        return None
    if (s.get("reason") or st) == "lane_out":
        return {"status": "wait", "text": "%s out" % (lane_name(s.get("lane"), s.get("family")) or "lane")}
    return {"status": "fail", "text": s.get("reason") or st}


def plan_titles(path: str, cache: FileCache | None = None) -> list[str]:
    """Stage titles from the plan the run keeps beside its log: the first json file there with a `stages` list; [] when none."""
    run_dir = ConfigDir(Path(path).parent.parent).run_dir(run_name(path))

    def load(p: str):
        try:
            with open(p, encoding="utf-8") as f:
                stages = (json.load(f) or {}).get("stages")
        except (OSError, ValueError, AttributeError):
            return None
        return [arrows.stage_title(x.get("goal") if isinstance(x, dict) else x) for x in stages] if isinstance(stages, list) else None

    try:
        files = sorted(run_dir.glob("*.json"))
    except OSError:
        return []
    for p in files:
        titles = cache.get(str(p), load) if cache else load(str(p))
        if titles is not None:
            return titles
    return []


def arrow_inside(n: dict, sessions: list, k: int, s: dict | None) -> dict:
    """The arrow into the k-th call of a step (k > 0): the move logged between the two calls, else a plain retry."""
    prev_i = sessions[k - 1].get("_i", -1) if sessions[k - 1] else -1
    inside = [
        m
        for m in n["moves"]
        if prev_i < m["_i"] < (s or {}).get("_i", 1 << 60) and m.get("to") in (n["step"], "") and m.get("cause") != "paused"
    ]
    mv = inside[-1] if inside else {"cause": "retry", "detail": "another try"}
    prev = sessions[k - 1] or {}
    ctx = {"from_name": lane_name(prev.get("lane"), prev.get("family")), "to_model": nice_model((s or {}).get("model"))}
    return {"cause": mv["cause"], "detail": mv.get("detail") or "", "text": arrows.arrow_text(mv["cause"], mv.get("detail"), ctx)}


def block_result(n: dict, s: dict | None, last: bool) -> dict:
    res = session_result(s) if not last else None
    if res is not None:
        return res
    out = n["outcome"]
    if last and s and s.get("status") not in (None, "done") and n["step"] != "checks":
        return session_result(s) or {"status": "info", "text": out}
    text = n["detail"] if n["step"] in ("review", "checks") and n["detail"] else out
    return {"status": RESULT.get(out, "ok" if out else "info"), "text": out if n["step"] in ("plan", "replan") else text}


def blocks_of(nodes: list[dict], titles_in: list | tuple = ()) -> tuple[list[dict], dict | None]:
    """Blocks in order, each with the arrow into it, and the move out of the last one. A write, checks or review block names
    its stage (index, count, title); a review or verify block by the family that wrote the last write is marked same_family."""
    blocks: list[dict] = []
    pending: dict | None = None
    titles = list(titles_in or [])
    writer = ""
    for idx, n in enumerate(nodes):
        if n["step"] in ("reset", "close"):
            continue
        m = n["meta"]
        si = m.get("stage") if n["step"] in STAGED and m.get("stages") else None
        st = (titles[si - 1] if len(titles) >= si else "") if si else None
        sessions = n["sessions"] or [None]
        for k, s in enumerate(sessions):
            arrow = pending if k == 0 else arrow_inside(n, sessions, k, s)
            last = k == len(sessions) - 1
            res = block_result(n, s, last)
            t1 = (s or {}).get("t") if s and not last else n["t1"]
            t0 = n["t0"] if k == 0 else (sessions[k - 1] or {}).get("t") or n["t0"]
            secs = (s or {}).get("secs")
            who = who_of(n, s)
            if arrow and arrow.get("cause") == "lane_out" and k > 0:
                who["fallback"] = "new thread: {} was out".format(arrow["text"].split(" out")[0])
            fam = (s or {}).get("family") or who.get("family") or ""
            same = n["step"] in ("review", "verify") and bool((s or {}).get("flag") == "same_family" or (fam and writer and fam == writer))
            if n["step"] == "write" and fam in FAMILY:
                writer = fam
            blocks.append(
                {
                    "node": n["id"],
                    "k": k,
                    "kind": n["step"],
                    "label": label_of(n, k),
                    "stage": f"{m['stage']}/{m['stages']}" if m.get("stages") else None,
                    "stage_index": si,
                    "stage_count": m.get("stages") if si else None,
                    "stage_title": st,
                    "same_family": same,
                    "fix": m.get("fix"),
                    "fixes": None,
                    "write": m.get("write"),
                    "round": m.get("round"),
                    "files": n.get("files", []) if last else [],
                    "t0": t0,
                    "t1": t1,
                    "secs": secs if secs is not None else (round(t1 - t0) if t0 and t1 else None),
                    "who": who,
                    "tokens": (s or {}).get("tokens"),
                    "result": res,
                    "arrow": arrow,
                    "session": {
                        "ref": (s or {}).get("ref") or None,
                        "family": (s or {}).get("family") or "",
                        "status": (s or {}).get("status") or "",
                        "reason": (s or {}).get("reason") or "",
                        "transcript": (s or {}).get("transcript") or "",
                    }
                    if n["step"] not in ("checks", "land")
                    else None,
                }
            )
        pending = exit_move(n, nodes[idx + 1] if idx + 1 < len(nodes) else None)
    return blocks, pending


def exit_move(n: dict, nxt: dict | None) -> dict | None:
    """The arrow out of node n: the last transition logged after its last call, else what the next node shows."""
    last_s = max([s.get("_i", -1) for s in n["sessions"]] or [-1])
    out = [m for m in n["moves"] if m["_i"] > last_s]
    mv = out[-1] if out else (arrows.infer_move(n, nxt) if nxt else None)
    if not mv:
        return None
    return {
        "cause": mv["cause"],
        "detail": mv.get("detail") or "",
        "to": mv.get("to") or "",
        "text": arrows.arrow_text(mv["cause"], mv.get("detail"), arrows.exit_ctx(mv)),
    }


def because_text(run: dict, prev: dict | None = None) -> str:
    """Why a run started, in words."""
    b = run.get("started_because")
    pe = (prev or {}).get("end") or {}
    if b == "first":
        return "first run"
    if b == "answer":
        return "you answered" + (" ask {}".format(run["ask"].rsplit("-", 1)[-1]) if run.get("ask") else "")
    if b == "fresh":
        return "fresh start"
    after = {
        "paused": "after pause" + ((": {} was out".format(pe["lane"])) if pe.get("lane") else ""),
        "stopped": "after a stop",
        "failed": "after a failure",
        "asks": "after the bead changed",
    }.get(pe.get("outcome") or "", "")
    return "resumed " + (after or "from the checkpoint") if b == "resume" else "retry" + ((" " + after) if after else "")


def run_end(nodes: list[dict], pending: dict | None, alive: bool) -> dict:
    close = next((n for n in reversed(nodes) if n["step"] == "close"), None)
    if not close:
        t = nodes[-1]["t1"] if nodes else None
        if alive:
            return {"outcome": "running", "status": "run", "cause": "running", "text": "running", "t": t}
        return {"outcome": "stopped", "status": "fail", "cause": "stopped", "t": t, "text": "stopped: the run ended without a close record"}
    outcome, why = close["close"].get("outcome") or "", close["close"].get("why") or ""
    mv = pending or {}
    cause = arrows.close_move(outcome, why)[1]
    cause = mv.get("cause") if mv.get("to") in ("ask", "pause", "close") else cause
    end = {"t": close["t0"], "why": why[:600], "cause": cause}
    if outcome in ("landed", "done"):
        end.update(outcome=outcome, status="ok", text="{} {}".format(outcome, when(close["t0"])))
    elif why.startswith("paused:"):
        end.update(
            outcome="paused",
            status="wait",
            lane=arrows.lane_of(why),
            until=arrows.until_of(why),
            reason=arrows.pause_reason(why),
            text=arrows.arrow_text("paused", why),
        )
    elif why.startswith("waiting:"):
        end.update(outcome="waiting", status="ask", text=arrows.arrow_text("waiting"))
    elif outcome == "blocked" and arrows.ask_kind(why):
        end.update(outcome="asks", status="ask", text=arrows.arrow_text(cause if cause in arrows.ASKS else arrows.ask_kind(why) or ""))
    elif why.startswith("failed: stopped"):
        end.update(outcome="stopped", status="fail", text="stopped")
    else:
        end.update(
            outcome="failed" if outcome == "failed" else "blocked", status="fail", text=arrows.arrow_text("failed", why.split("\n")[0])
        )
    return end


def waits_of(recs: list, until: float = 0) -> list[dict]:
    """The engine's waits: [{what, label, t0, secs, holder, in_budget}], oldest first. A wait_start with no wait_end after it is a
    wait still going (or cut off when the process died): it lasts until `until`."""
    out: list[dict] = []
    starts = {r.id: r for r in recs if isinstance(r, rec.WaitStart)}
    ended: set[str] = set()
    for r in recs:
        if isinstance(r, rec.WaitEnd):
            s = starts.get(r.id)
            ended.add(r.id)
            what = str(s.what) if s else "other"
            out.append(
                {
                    "what": what,
                    "label": what.replace("_", " "),
                    "t0": s.t if s else r.t - r.secs,
                    "secs": r.secs,
                    "holder": s.holder if s else "",
                    "in_budget": r.in_budget,
                }
            )
    for ident, s in starts.items():
        if ident not in ended and until > s.t:
            out.append(
                {
                    "what": str(s.what),
                    "label": str(s.what).replace("_", " "),
                    "t0": s.t,
                    "secs": until - s.t,
                    "holder": s.holder,
                    "in_budget": True,
                    "open": True,
                }
            )
    return sorted(out, key=lambda w: w["t0"])


def run_timeline(path: str, alive: bool = False, now: float | None = None, cache: FileCache | None = None) -> dict:
    """One run of a bead: why it started, its blocks with the arrows between them, how it ended. A run that is alive has its open
    step and its end at `now` (the last record only says when something last happened, not how long it has been going)."""
    recs = read(path, cache)
    nodes, run = nodes_of(recs)
    now = now or time.time()
    if alive and nodes and nodes[-1].get("open"):
        nodes[-1]["t1"] = now
    blocks, pending = blocks_of(nodes, plan_titles(path, cache))
    t0 = recs[0].t if recs else None
    t1 = now if alive and recs else recs[-1].t if recs else None
    tokens = {"in": 0, "cached": 0, "out": 0}
    for b in blocks:
        for k in tokens:
            tokens[k] += int((b.get("tokens") or {}).get(k) or 0)
    end = run_end(nodes, pending, alive)
    if blocks and end["outcome"] in ("running", "stopped"):  # the step it was in when it stopped, or is in now
        b = blocks[-1]
        if not (b["session"] or {}).get("ref") or b["kind"] in ("checks", "land"):
            b["result"] = {"status": end["status"], "text": end["outcome"]}
    name = run_name(path)
    origin = {k: (run or {}).get(k) or "" for k in ("started_because", "prev_run", "ask")}
    return dict(
        origin,
        run=name,
        bead=bead_of(name),
        started=t0,
        ended=t1,
        secs=round(t1 - t0) if t0 and t1 else None,
        blocks=blocks,
        end=end,
        tokens=tokens,
        slot=(run or {}).get("slot") or "",
        worktree=(run or {}).get("worktree") or "",
        waits=waits_of(recs, now if alive else (t1 or 0)),
        alive=bool(alive),
    )


def last_node(path: str, cache: FileCache | None = None) -> dict | None:
    nodes, _ = nodes_of(read(path, cache))
    return nodes[-1] if nodes else None


def live_label(n: dict | None) -> str:
    """What a running task is doing, from its last node."""
    if not n:
        return "starting"
    step, m = n["step"], n["meta"]
    stage = f" stage {m['stage']}/{m['stages']}" if m.get("stages") and m["stages"] > 1 else ""
    fix = f"fix round {m['fix']} · " if m.get("fix") else ""
    if step == "write":
        return fix + "writing" + stage + (f" (write {m['write']})" if (m.get("write") or 1) > 1 else "")
    if step in ("checks", "review"):
        return fix + step + stage
    return {
        "reset": "starting",
        "plan": "planning",
        "replan": "re-planning",
        "verify": "checking before land",
        "land": "landing",
        "close": "closing",
    }.get(step, step)
