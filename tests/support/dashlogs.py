"""Typed engine logs for the dashboard v2 tests: `RunScript` writes the records an engine run would (EngineLog v2, as dicts through
`typed`), `.records()` decodes them strictly, `.run(now)` makes the dashboard's Run of them, `.write(config)` puts them where the
dashboard reads them. Times are seconds after T; every method moves the script's clock."""

import json
import os
from pathlib import Path

import support.paths  # noqa: F401
from support.logs import typed
from taskloop.contracts import log
from taskloop.contracts.bead import Bead
from taskloop_dash.views.runfacts import run_of

T = 1_800_000_000.0


def bead(id, title="", status="open", **kw):
    return Bead(id=id, title=title or id, status=status, **kw)


class RunScript:
    def __init__(self, bead_id, stamp="20261015-100000", slot="a", at=0.0, prev_run="", worktree="/w/a"):
        self.bead, self.name, self.t, self.n = bead_id, f"{bead_id}-{stamp}", T + at, 0
        self.rows = [typed("run_start", self.t, run=self.name, bead=bead_id, worktree=worktree, slot=slot, prev_run=prev_run)]

    def add(self, kind, **fields):
        self.rows.append(typed(kind, self.t, **fields))
        return self

    def wait(self, secs):
        self.t += secs
        return self

    def step(self, step, secs, tokens=0, lane="", text="", outcome="done", end=True):
        """One step of `secs` seconds with a worker call of `tokens` fresh tokens (all output); an open step when end=False."""
        self.n += 1
        sid = f"n{self.n}"
        self.add("step_start", id=sid, step=step, text=text)
        if tokens:
            self.add("call_start", id=f"c{self.n}", n=1, step=step, node=step, role="writer")
        self.t += secs
        if tokens:
            self.add("call_end", id=f"c{self.n}", status="ok", lane=lane, secs=secs, tokens={"in": 0, "cached": 0, "out": tokens})
        if end:
            self.add("step_end", id=sid, step=step, outcome=outcome, secs=secs)
        return self

    def move(self, to, cause):
        return self.add("transition", **{"from": f"n{self.n}", "to": to, "cause": cause})

    def artifacts(self, step_n, step, *names):
        return self.add("artifacts", id=f"n{step_n}", step=step, bead=self.bead, names=list(names))

    def close(self, outcome, why_code=None, why=""):
        self.add("close", outcome=outcome, why_code=why_code, why=why)
        return self

    def beat(self):
        return self.add("beat")

    def records(self):
        return [log.decode(r) for r in self.rows]

    def run(self, now):
        return run_of(self.name, self.records(), now)

    def write(self, config):
        d = Path(config) / "engine"
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"{self.name}.jsonl"
        f.write_text("\n".join(json.dumps(r) for r in self.rows) + "\n", encoding="utf-8")
        os.utime(f, (self.t, self.t))  # the file is as old as its last record: the dashboard's retention reads the mtime
        return self
