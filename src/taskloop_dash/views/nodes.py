"""The records of one engine run folded into nodes: a node is one step with its worker calls, lines and moves."""

from taskloop.contracts import log as rec
from taskloop_dash.views.names import num

META = ("stage", "stages", "write", "round", "fix")


def try_of(text: str) -> int | None:
    """N from a step text that ends '(try N)'."""
    head, sep, tail = text.rpartition("(try ")
    n = tail[:-1] if tail.endswith(")") else ""
    return int(n) if sep and head is not None and n.isdigit() else None


def session_of(end: rec.CallEnd, start: rec.CallStart | None, index: int) -> dict:
    tk = end.tokens
    return {
        "t": end.t,
        "node": start.step if start else "",
        "role": start.role if start else "",
        "resume": bool(start and start.resume),
        "node_id": num(start.node) if start else 0,
        "attempt": start.n if start else 1,
        "status": end.status,
        "reason": end.reason,
        "ref": end.ref,
        "lane": end.lane,
        "model": end.model,
        "effort": end.effort,
        "secs": end.secs or None,
        "cost": end.cost,
        "family": end.family,
        "flag": end.flag,
        "transcript": end.transcript,
        "exit": end.exit,
        "tokens": {"in": tk.in_, "cached": tk.cached, "out": tk.out},
        "_i": index,
    }


def line_of(r, index: int) -> dict | None:
    """A command, note or warning as the one line the block's detail shows."""
    if isinstance(r, rec.CmdStart):
        return {"t": r.t, "kind": "cmd", "text": r.text, "_i": index}
    if isinstance(r, rec.CmdEnd):
        return {
            "t": r.t,
            "kind": "note",
            "text": f"exit {r.exit}{(': ' + r.out) if r.out else ''}",
            "exit": r.exit,
            "out": r.out,
            "secs": r.secs,
            "_i": index,
        }
    if isinstance(r, (rec.Note, rec.Warn)):
        return {"t": r.t, "kind": r.KIND, "text": r.text, "_i": index}
    return None


def new_node(r: rec.StepStart) -> dict:
    meta = {x: getattr(r, x) for x in META if getattr(r, x) is not None}
    if try_of(r.text):
        meta["try"] = try_of(r.text)
    return {
        "id": num(r.id),
        "step": r.step,
        "text": r.text,
        "t0": r.t,
        "t1": None,
        "meta": meta,
        "sessions": [],
        "lines": [],
        "moves": [],
        "checks": None,
        "outcome": "",
        "detail": "",
        "close": {},
        "open": True,
    }


class NodeBuilder:
    """Folds the records of a run, in order, into its nodes."""

    def __init__(self) -> None:
        self.nodes: list[dict] = []
        self.by_id: dict[int, dict] = {}
        self.cur: dict | None = None
        self.run: dict | None = None
        self.ends: dict[int, rec.StepEnd] = {}
        self.calls: dict[str, rec.CallStart] = {}

    def node_for(self, ident: object) -> dict | None:
        return self.by_id.get(num(ident)) or self.cur

    def feed(self, i: int, r) -> None:
        if isinstance(r, rec.StepStart):
            if self.nodes and self.nodes[-1]["t1"] is None:
                self.nodes[-1]["t1"] = r.t
            self.cur = new_node(r)
            self.nodes.append(self.cur)
            self.by_id[self.cur["id"]] = self.cur
        elif isinstance(r, rec.RunStart):
            self.run = {
                "started_because": r.started_because,
                "prev_run": r.prev_run,
                "ask": r.ask,
                "slot": r.slot or "",
                "worktree": r.worktree,
            }
        elif isinstance(r, rec.StepEnd):
            self.ends[num(r.id)] = r
        elif self.cur is not None:
            self.within(i, r)

    def within(self, i: int, r) -> None:
        """A record that belongs to a step."""
        if isinstance(r, rec.Transition):
            self.node_for(r.from_id)["moves"].append({"from": r.from_id, "to": r.to, "cause": r.cause, "detail": r.detail, "_i": i})
        elif isinstance(r, rec.CallStart):
            self.calls[r.id] = r
        elif isinstance(r, rec.CallEnd):
            start = self.calls.get(r.id)
            self.node_for(start.node if start else 0)["sessions"].append(session_of(r, start, i))
        elif isinstance(r, rec.Checks):
            self.node_for(r.node_id)["checks"] = r
        elif isinstance(r, rec.Close):
            self.cur["close"] = {"outcome": str(r.outcome), "why": r.why, "sha": r.sha, "why_code": r.why_code}
        elif (ln := line_of(r, i)) is not None:
            self.cur["lines"].append(ln)

    def done(self, recs: list) -> list[dict]:
        if self.nodes and self.nodes[-1]["t1"] is None:
            self.nodes[-1]["t1"] = recs[-1].t if recs else None
        for n in self.nodes:
            e = self.ends.get(n["id"])
            if e:
                n["t1"], n["outcome"], n["detail"], n["open"] = e.t or n["t1"], e.outcome, e.detail, False
        return self.nodes


def nodes_of(recs: list) -> tuple[list[dict], dict | None]:
    """(nodes, the run's start). A node: one engine step with its worker calls, lines and moves."""
    b = NodeBuilder()
    for i, r in enumerate(recs):
        b.feed(i, r)
    return b.done(recs), b.run
