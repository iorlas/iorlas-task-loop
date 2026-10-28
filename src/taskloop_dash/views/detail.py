"""One block of a run in full: its worker call, the checks of its round with their outputs, the engine lines of its step."""

from taskloop_dash.cache import FileCache
from taskloop_dash.views import timeline
from taskloop_dash.views.nodes import nodes_of

CALL_KEYS = (
    "lane",
    "model",
    "effort",
    "family",
    "role",
    "secs",
    "tokens",
    "cost",
    "status",
    "reason",
    "ref",
    "transcript",
    "exit",
    "resume",
    "attempt",
    "flag",
    "t",
)
SESSION_KEYS = ("ref", "family", "model", "effort", "lane", "status", "reason", "transcript", "tokens", "secs", "resume", "flag", "attempt")


def check_pairs(lines: list[dict]) -> list[list]:
    """[[cmd, exit, tail, secs]] from a step's command lines and the exit note after each."""
    out: list[list] = []
    last: list | None = None
    for ln in lines:
        if ln["kind"] == "cmd":
            last = [ln["text"], None, "", None]
            out.append(last)
        elif ln["kind"] == "note" and last is not None and ln.get("exit") is not None:
            last[1], last[2], last[3] = ln["exit"], (ln.get("out") or "").strip(), ln.get("secs")
            last = None
    return out


def checks_of(n: dict) -> list[dict]:
    pairs = check_pairs(n["lines"])
    rec = n.get("checks")
    if not rec:
        return [
            {
                "id": cmd,
                "cmd": cmd,
                "exit": ex,
                "status": "passed" if ex == 0 else "failed" if ex else "?",
                "secs": round(secs) if isinstance(secs, (int, float)) else None,
                "tries": 1,
                "tail": tail,
                "log": "",
            }
            for cmd, ex, tail, secs in pairs
        ]
    out: list[dict] = []
    used: set[int] = set()
    for it in rec.run.results:
        tail = ""
        for j, p in enumerate(pairs):
            if j not in used and it.exit is not None and p[1] == it.exit and (p[0] == it.cmd or p[0].endswith(it.cmd[-40:])):
                used.add(j)
                tail = p[2]
                break
        out.append(
            {
                "id": it.id,
                "cmd": it.cmd,
                "group": it.group,
                "exit": it.exit,
                "status": it.status,
                "secs": it.secs,
                "tries": it.tries,
                "cached": it.cached,
                "reused": it.reused,
                "why": it.why,
                "log": it.log,
                "tail": tail,
            }
        )
    return out


def judging_checks(nodes: list[dict], idx: int) -> dict | None:
    """The checks node that judges node idx: itself, or for a write the checks that follow it."""
    n = nodes[idx]
    if n["step"] == "checks":
        return n
    if n["step"] != "write":
        return None
    for m in nodes[idx + 1 :]:
        if m["step"] == "checks":
            return m
        if m["step"] in ("write", "plan", "replan", "close"):
            break
    return None


def block_detail(path: str, node_id: str | int, k: str | int = 0, cache: FileCache | None = None) -> dict:
    recs = timeline.read(path, cache)
    nodes, _ = nodes_of(recs)
    blocks, _ = timeline.blocks_of(nodes, timeline.plan_titles(path, cache))
    try:
        node, kk = int(node_id), int(k or 0)
    except (TypeError, ValueError):
        return {"error": "no such block"}
    blk = next((b for b in blocks if b["node"] == node and b["k"] == kk), None)
    idx = next((i for i, n in enumerate(nodes) if n["id"] == node), None)
    if blk is None or idx is None:
        return {"error": "no such block"}
    n = nodes[idx]
    judge = judging_checks(nodes, idx)
    last_checks = max([m["id"] for m in nodes if m["step"] == "checks"] or [0])
    lines = [{"t": ln["t"], "kind": ln["kind"], "text": str(ln["text"])[:2000], "exit": ln.get("exit")} for ln in n["lines"]][:400]
    sess = n["sessions"][kk] if kk < len(n["sessions"]) else {}
    calls = [dict({key: c.get(key) for key in CALL_KEYS}, k=i) for i, c in enumerate(n["sessions"])]  # every worker call of the step
    return {
        "block": blk,
        "calls": calls,
        "session": {key: sess.get(key) for key in SESSION_KEYS} if sess else None,
        "checks": checks_of(judge) if judge else [],
        "checks_node": judge["id"] if judge else None,
        "checks_last": bool(judge and judge["id"] == last_checks),
        "lines": lines,
        "answer": None,
        "node_text": n["text"],
    }
