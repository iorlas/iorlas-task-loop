"""Dashboard fixture logs and projection helpers: public testing surface."""
import dataclasses
import json
import os

from tlkernel import beadrows, factorydb, log
from tlkernel.bead import Bead
from tlkernel.ids import loop_key
from tlkernel.paths import ConfigDir
from tlkernel.run import RunManifest, RunState
from tlkernel.runlife import liveness
from tltestkit.logs import typed
from tltestkit.runs import manifest
from tltestkit.waits import settle

from tldash.index import Indexer
from tldash.views.runfacts import run_of

T = 1_800_000_000.0


def bead(id, title="", status="open", **kw):
    return Bead(id=id, title=title or id, status=status, **kw)


class RunScript:
    def __init__(self, bead_id, stamp="20261015-100000", slot="a", at=0.0, prev_run="", worktree="/w/a"):
        self.bead, self.name, self.t, self.n = bead_id, f"{bead_id}-{stamp}", T + at, 0
        self.t0 = self.t
        self.rows = [typed("run_start", self.t, run_id=self.name, bead=bead_id, worktree=worktree, slot=slot, parent_id=prev_run)]

    def add(self, kind, **fields):
        self.rows.append(typed(kind, self.t, **fields))
        return self

    def wait(self, secs):
        self.t += secs
        return self

    def step(self, step, secs, tokens=0, account="", text="", outcome="done", end=True, role="writer", cost=0.0, source=""):
        """One step of `secs` seconds with a worker call of `tokens` fresh tokens (all output); an open step when end=False."""
        self.n += 1
        sid = f"n{self.n}"
        self.add("step_start", id=sid, step=step, text=text)
        if tokens:
            self.add("call_start", id=f"c{self.n}", n=1, step=step, node=step, role=role)
        self.t += secs
        if tokens:
            self.add("call_end", id=f"c{self.n}", status="ok", account=account, secs=secs, tokens={"in": 0, "cached": 0, "out": tokens},
                     cost=cost, cost_source=source)
        if end:
            self.add("step_end", id=sid, step=step, outcome=outcome, exec_seconds=secs)
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

    def closed(self):
        return any(r["kind"] == "close" for r in self.rows)

    def state(self, lost=False):
        """The state the engine would have recorded: its terminal one after a close, running before, lost when `lost`."""
        return RunState.LOST if lost else RunState.DONE if self.closed() else RunState.RUNNING

    def run(self, now, lost=False):
        return dataclasses.replace(run_of(self.name, self.records(), now), life=liveness(self.manifest(lost)),
                                   records=tuple(r for r in self.records() if not isinstance(r, log.Beat)))

    def manifest(self, lost=False):
        return RunManifest(run=self.name, repo="/repo", bead=self.bead, started=self.t0, state=self.state(lost))

    def write(self, config, lost=False, repo="/repo"):
        manifest(config, self.name, self.bead, self.t0, repo=repo, state=self.state(lost))
        f = ConfigDir(config).engine_log(self.name)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("\n".join(json.dumps(r) for r in self.rows) + "\n", encoding="utf-8")
        os.utime(f, (self.t, self.t))  # the file is as old as its last record: the dashboard's retention reads the mtime
        return self


BEAD, STAMP = "tl-live.1", "20261026-100000"


LIVE_T = 1793000000.0


def put(path, rows, mode="a"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode, encoding="utf-8") as f:
        for r in rows:
            f.write((r if isinstance(r, str) else json.dumps(r)) + "\n")


def make_run(root):
    """An engine log with a command and a write step, and the live file of its write call."""
    b = manifest(os.path.join(root, "task-loop"), f"{BEAD}-{STAMP}", BEAD, LIVE_T)
    log = str(b.log)
    put(log, [typed("run_start", LIVE_T, run_id=f"{BEAD}-{STAMP}", bead=BEAD, worktree=""),
              typed("cmd_start", LIVE_T + 1, id="m1", text="git fetch -q origin"),
              typed("cmd_end", LIVE_T + 3, id="m1", exit=0),
              typed("step_start", LIVE_T + 4, id="n1", text="write: x", step="write"),
              typed("call_start", LIVE_T + 5, id="c1", n=1, step="write", node="n1", role="worker")])
    lf = os.path.join(b.live, "01-write.jsonl")
    put(
        lf,
        [
            {"t": LIVE_T + 6, "kind": "start", "harness": "codex", "account": "CODEX", "model": "gpt-x",
             "effort": "high", "role": "worker", "pid": 1},
            {"t": LIVE_T + 6.5, "kind": "msg", "text": "between the start and the command"},
            {"t": LIVE_T + 7, "kind": "cmd_start", "id": "1", "text": "pytest -q", "cwd": "/w"},
        ],
    )
    return b, lf


def ingest(cfg, now):
    cfg = cfg if isinstance(cfg, ConfigDir) else ConfigDir(cfg)
    with Indexer(cfg, clock=lambda: now) as index:
        settle(index)


def seed_beads(cfg, repo, beads, now):
    """Publish fixture beads through the projection contract, without asking the dashboard to list bd."""
    cfg = cfg if isinstance(cfg, ConfigDir) else ConfigDir(cfg)
    cfg.root.mkdir(parents=True, exist_ok=True)
    con = factorydb.open_rw(cfg.factory_db())
    assert con is not None
    try:
        with factorydb.begin_immediate(con):
            beadrows.replace_repo(con, loop_key(repo), [beadrows.row_of(bead) for bead in beads], None, now)
    finally:
        con.close()
