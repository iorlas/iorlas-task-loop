"""The engine log (EngineLog v2, one typed record per line) as the flat rows the dashboard panels read: node, end, session, cmd,
note, checks, wait ... The panels (dash/timeline.py, dash/server.py) keep this shape until the dashboard reads the typed records
itself (P1); a row that has no `v` is already a flat row and passes through. Standard library only."""
import json
import re

TRY = re.compile(r"\(try (\d+)\)")


def num(ident):
    """The number in a step id ('n4' -> 4); 0 for none."""
    digits = str(ident or "").lstrip("n")
    return int(digits) if digits.isdigit() else 0


class Rows:
    """Translates records one at a time; it remembers the open step, the calls and the waits that have started."""

    def __init__(self):
        self.step, self.calls, self.waits, self.node = 0, {}, {}, None

    def row(self, d):
        """The flat rows of one record (a list: none, one, or more)."""
        if d.get("v") != 2:
            return [d]
        fn = getattr(self, "k_" + str(d.get("kind")), None)
        out = fn(d) if fn else [dict(d, text=d.get("text") or "")]
        return [x for x in out if x]

    def k_run_start(self, d):
        return [dict(d, kind="run", text="run: %s" % d["started_because"])]

    def k_step_start(self, d):
        self.step = num(d["id"])
        meta = {k: d[k] for k in ("stage", "stages", "round", "write", "fix") if d.get(k) is not None}
        tries = TRY.search(d.get("text") or "")
        self.node = dict(t=d["t"], kind="node", id=self.step, step=d["step"], text=d.get("text") or "", **meta, **({"try": int(tries.group(1))} if tries else {}))
        return [self.node]

    def k_step_end(self, d):
        return [dict(t=d["t"], kind="end", id=num(d["id"]), step=d["step"], outcome=d["outcome"], detail=d.get("detail") or "", secs=d.get("secs"),
                     text="%s %d: %s" % (d["step"], num(d["id"]), d["outcome"]))]

    def k_close(self, d):  # the close step's row carries the outcome and why the panels read from it
        if self.node and self.node["step"] == "close":
            self.node.update(outcome=d["outcome"], why=d.get("why") or "", sha=d.get("sha") or "", why_code=d.get("why_code"))
        return []

    def k_call_start(self, d):
        self.calls[d["id"]] = d
        return []

    def k_call_end(self, d):
        start = self.calls.get(d["id"]) or {}
        tk = d.get("tokens") or {}
        row = dict(d, kind="session", node=start.get("step") or "", role=start.get("role") or "", resume=bool(start.get("resume")),
                   node_id=num(start.get("node")) or self.step, tokens={k: tk.get(k) or 0 for k in ("in", "cached", "out")})
        row["text"] = "%s: %s %s" % (row["node"], d.get("family") or "?", d.get("ref") or "(no session)")
        return [row]

    def k_cmd_start(self, d):
        return [dict(d, kind="cmd")]

    def k_cmd_end(self, d):
        return [dict(d, kind="note", text="exit %d%s" % (d["exit"], (": " + d["out"]) if d.get("out") else ""))]

    def k_gate_start(self, d):
        return [dict(d, kind="gate_start", text="gate: %s" % d["cmd"])]

    def k_gate_end(self, d):
        return [dict(d, kind="gate", cached=d.get("skipped"), text="gate: %s" % ("skipped" if d.get("skipped") else "exit %s" % d.get("exit")))]

    def k_wait_start(self, d):
        self.waits[d["id"]] = d
        return [dict(d, t0=d["t"], text=str(d["what"]).replace("_", " "))]

    def k_wait_end(self, d):
        start = self.waits.get(d["id"]) or {}
        what = start.get("what") or "other"
        return [dict(d, kind="wait", what=what, holder=start.get("holder") or "", t0=start.get("t", d["t"] - d["secs"]), text=str(what).replace("_", " "))]

    def k_transition(self, d):
        return [dict(d, **{"from": num(d.get("from"))}, text="%s -> %s: %s" % (d["cause"], d["to"], d.get("detail") or ""))]

    def k_checks(self, d):
        return [dict(d, node_id=num(d["node_id"]), text="checks round %d" % d["round"])]

    def k_vendor_error(self, d):
        return [dict(d, node_id=self.step, text="%s: %s" % (d.get("node") or "", d["reason"]))]

    def k_kill(self, d):
        return [dict(d, node_id=self.step, text="%s: %s" % (d["what"], d["why"]))]


def rows(recs):
    """The flat rows of a list of decoded records, in order."""
    state, out = Rows(), []
    for d in recs:
        if isinstance(d, dict):
            out.extend(state.row(d))
    return out


def read(lines):
    """The flat rows of a log's lines; a line that is not a JSON object is skipped."""
    def parse(ln):
        try:
            return json.loads(ln)
        except ValueError:
            return None
    return rows(parse(ln) for ln in lines)
