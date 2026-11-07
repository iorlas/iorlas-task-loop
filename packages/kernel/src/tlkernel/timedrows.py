"""The timed things of a run as `timed` rows in factory.db: one row per step, call, check, gate, wait or command that ended, written as
the engine log's end record is appended (`RunLog.append` feeds a `Tracker`). `tl runs show` and `tl runs slow` read these rows only. A
row's seconds are the end record's own (`exec_seconds`, a call's `secs`, `wait_seconds`); a command has none of its own, so its span is
the gap between its start and end records."""
from dataclasses import dataclass

from tlkernel import factorydb, log
from tlkernel.looprows import LoopRows
from tlkernel.paths import ConfigDir


@dataclass(frozen=True)
class Item:
    run: str
    bead: str
    kind: str  # step | call | check | gate | wait | cmd
    name: str
    exec_s: float
    wait_s: float
    t: float


class Tracker:
    """Pairs a run's start and end records, in the order they are logged; `feed` answers the item an end record completes."""

    def __init__(self, run: str) -> None:
        self.run, self.bead = run, ""
        self.names: dict[str, tuple[str, str]] = {}
        self.began: dict[str, float] = {}  # a command's start: its record carries no seconds, the gap to its end is the span

    def feed(self, r: log.EngineLog) -> Item | None:
        self.bead = self.bead or r.bead
        bead = r.bead or self.bead
        if isinstance(r, log.StepStart):
            self.names[r.id] = ("step", r.step)
        elif isinstance(r, log.CmdStart):
            self.names[r.id], self.began[r.id] = ("cmd", r.text), r.t
        elif isinstance(r, log.CmdEnd) and r.id in self.began:
            return Item(self.run, bead, "cmd", self.names[r.id][1], max(0.0, r.t - self.began.pop(r.id)), 0.0, r.t)
        elif isinstance(r, log.CallStart):
            self.names[r.id] = ("call", f"{r.node} {r.role}".strip())
        elif isinstance(r, log.CheckStart):
            self.names[r.id] = ("check", r.check)
        elif isinstance(r, log.WaitStart):
            self.names[r.id] = ("wait", str(r.what) + (f" {r.holder}" if r.holder else ""))
        elif isinstance(r, log.StepEnd | log.CheckEnd | log.WaitEnd):
            kind, name = self.names.get(r.id, ("step" if isinstance(r, log.StepEnd) else "?", r.id))
            return Item(self.run, bead, kind, name, r.exec_seconds or 0.0, r.wait_seconds or 0.0, r.t)
        elif isinstance(r, log.CallEnd):
            kind, name = self.names.get(r.id, ("call", r.id))
            return Item(self.run, bead, kind, name, r.secs, r.wait_seconds or 0.0, r.t)
        elif isinstance(r, log.GateEnd):
            return Item(self.run, bead, "gate", "gate", r.exec_seconds or 0.0, r.wait_seconds or 0.0, r.t)
        return None


def add(cfg: ConfigDir, item: Item) -> None:
    with LoopRows(cfg, "").transaction() as con:
        con.execute("INSERT INTO timed (run, bead, kind, name, exec_s, wait_s, t) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (item.run, item.bead, item.kind, item.name, item.exec_s, item.wait_s, item.t))


def _items(found: list[tuple[str, ...]]) -> list[Item]:
    return [Item(r[0], r[1] or "", r[2], r[3], float(r[4]), float(r[5]), float(r[6])) for r in found]


def of_run(cfg: ConfigDir, run: str) -> list[Item]:
    """The run's timed items in the order they ended; none when the database cannot be read."""
    try:
        return _items(LoopRows(cfg, "", quiet=True).select(
            "SELECT run, bead, kind, name, exec_s, wait_s, t FROM timed WHERE run=? ORDER BY id", (run,)))
    except factorydb.DatabaseError:
        return []


def newest(cfg: ConfigDir, runs: int) -> tuple[int, list[Item]]:
    """(how many runs, their items) of the `runs` runs that ended a timed item most recently."""
    rows = LoopRows(cfg, "", quiet=True)
    try:
        ids = [r[0] for r in rows.select("SELECT run FROM timed GROUP BY run ORDER BY MAX(id) DESC LIMIT ?", (runs,))]
        if not ids:
            return 0, []
        marks = ",".join("?" for _ in ids)
        return len(ids), _items(rows.select(
            f"SELECT run, bead, kind, name, exec_s, wait_s, t FROM timed WHERE run IN ({marks}) ORDER BY id", tuple(ids)))
    except factorydb.DatabaseError:
        return 0, []
