"""`tl layout migrate` (tl-9un.44): an old config dir becomes the target tree once. runs/<run>/ holds everything of a run, repos/<key>/ the
state of a repo.

Each move is one rename inside the config dir, so a reader sees the old place or the new one, never half. A hash manifest taken before
and after proves nothing changed on the way, and every step goes to the journal. A second run finds nothing old and changes nothing.
No reader looks at an old place afterwards: a tl that finds one stops and names this command (`old_layout`)."""
import hashlib
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from taskloop.adapters import key_migrate, locks
from taskloop.contracts import factorydb
from taskloop.contracts.paths import ConfigDir, RunFiles
from taskloop.contracts.ports import Git
from taskloop.contracts.stores import ReposStore

COMMAND = "tl layout migrate"
RUN_FILE = re.compile(r"(?P<run>.+?)(?P<tail>\.jsonl(?:\.\d+)?|\.stderr|\.live)")
LOOP_FILE = re.compile(r"(?P<key>.+-[0-9a-f]{8})(?P<tail>\.command\.json|-rest\.json|\.jsonl(?:\.\d+)?|\.json|\.\d+\.json)?")
LOOP_NAME = {".command.json": "command.json", "-rest.json": "rest.json", ".json": "state.json"}


@dataclass(frozen=True)
class Move:
    src: Path
    dst: Path | None  # None: retired (an older loop's per-pid state file; the rows are in factory.db)


def plan(cfg: ConfigDir, keys: dict[str, str] | None = None) -> list[Move]:
    """Every old place that still holds something, with where it goes (`keys`: old repo key -> the repo's one key, from key_migrate;
    without them a repo key is taken as it is). Pure listing: nothing is touched."""
    keys = keys or {}
    out: list[Move] = []
    root = cfg.root
    for f in sorted((root / "engine").glob("*")):
        m = RUN_FILE.fullmatch(f.name)
        if m:
            tail = m["tail"]
            to = {".stderr": "stderr.log", ".live": "live"}.get(tail, "engine" + tail)
            out.append(Move(f, cfg.run_dir(m["run"]) / to))
    for f in sorted((root / "loop").glob("*")):
        m = LOOP_FILE.fullmatch(f.name)
        if m is None:
            continue
        key, tail = m["key"], m["tail"] or ""
        home = cfg.loop_runs(key)
        if f.is_dir():
            out += [Move(c, home / c.name) for c in sorted(f.iterdir())]
        elif re.fullmatch(r"\.\d+\.json", tail):
            out.append(Move(f, None))
        elif tail.startswith(".jsonl"):
            out.append(Move(f, home / ("log" + tail)))
        else:
            out.append(Move(f, home / LOOP_NAME[tail]))
    for old in ("slots", "slot-state", "decisions"):
        out += [Move(d, key_migrate.home(cfg, d.name, keys) / old) for d in _dirs(root / old)]
    out += [Move(f, key_migrate.home(cfg, f.stem, keys) / "durations.json") for f in sorted((root / "check-durations").glob("*.json"))]
    # a run's old artifacts/ is one run attempt: its step tries are numbered apart
    out += [Move(a, RunFiles(a.parent).artifacts(1)) for a in sorted((root / "runs").glob("*/artifacts"))]
    out += [Move(a, b) for a, b in key_migrate.moves(cfg, keys)]
    return out


def _dirs(parent: Path) -> list[Path]:
    return sorted(p for p in parent.glob("*") if p.is_dir())


def old_layout(cfg: ConfigDir) -> list[str]:
    """One line per old place found, empty when the config dir is in the target layout."""
    srcs = [m.src for m in plan(cfg)] + key_migrate.left_over(cfg)  # an old spelling of a repo key: which repo it is takes git
    return [f"{p.relative_to(cfg.root)} is the old layout" for p in srcs]


def stop_text(cfg: ConfigDir) -> str:
    """What a tl verb says when it finds the old layout (empty: it did not)."""
    old = old_layout(cfg)
    return f"tl: the config dir is in the old layout ({old[0]}, {len(old)} places): stop the loops, then run `{COMMAND}`" if old else ""


def live_writers(cfg: ConfigDir) -> list[str]:
    """The holders of the config dir's locks that are still alive (a loop or a run writes the old places)."""
    out: list[str] = []
    for lock in sorted((cfg.root / "locks").glob("*.lock")):
        rec = locks.read_holder(lock)
        if rec is not None and rec.alive():
            out.append(f"{lock.name}: {rec.holder} (pid {rec.pid})")
    return out


def manifest(path: Path) -> dict[str, str]:
    """{relative path: sha256} of a file or of every file under a folder (an empty folder: its name with no hash)."""
    if path.is_file():
        return {"": hashlib.sha256(path.read_bytes()).hexdigest()}
    out = {"": "dir"}
    for p in sorted(path.rglob("*")):
        out[p.relative_to(path).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "dir"
    return out


def migrate(cfg: ConfigDir, say: Callable[[str], None], now: float, git: Git) -> int:
    """Move every old place to the target tree and give every repo its one key. -> 0 done (or nothing to do), 2 a loop or run is live,
    3 a target already exists."""
    keys = key_migrate.keymap(git, ReposStore(cfg, quiet=True).known())
    moves = plan(cfg, keys)
    rows = _rows(cfg, keys, dry=True)
    if not moves and not rows:
        say("nothing to migrate: the config dir is in the target layout")
        return 0
    if live := live_writers(cfg):
        say("stop the loops and runs first; still holding a lock:\n  " + "\n  ".join(live))
        return 2
    dsts = [m.dst for m in moves if m.dst is not None]
    clash = [m for m in moves if m.dst is not None and (m.dst.exists() or dsts.count(m.dst) > 1)]
    if clash:
        say("the target already exists, nothing moved:\n  " + "\n  ".join(f"{m.src} -> {m.dst}" for m in clash))
        return 3
    journal = cfg.layout_journal()
    for m in moves:
        before = manifest(m.src)
        if m.dst is None:
            m.src.unlink()
        else:
            m.dst.parent.mkdir(parents=True, exist_ok=True)
            os.rename(m.src, m.dst)
            if manifest(m.dst) != before:
                raise RuntimeError(f"{m.src} changed on the way to {m.dst}")
        _journal(journal, {"t": now, "from": str(m.src), "to": str(m.dst) if m.dst else None, "files": len(before)})
    changed = _rows(cfg, keys, dry=False)
    if changed:
        _journal(journal, {"t": now, "factory.db": "repo keys", "rows": changed})
    olds = [cfg.root / n for n in ("engine", "loop", "slot-state", "decisions", "check-durations", "slots")]
    for old in olds + key_migrate.left_over(cfg):
        _drop_empty(old)
    say(f"migrated {len(moves)} places and {changed} factory.db rows; journal: {journal}")
    return 0


def _journal(path: Path, rec: dict[str, object]) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def _rows(cfg: ConfigDir, keys: dict[str, str], *, dry: bool) -> int:
    """The factory.db rows still under an old repo key (`dry`: counted, not changed); the rows changed otherwise."""
    con = factorydb.open_rw(cfg.factory_db()) if cfg.factory_db().is_file() else None
    if con is None:
        return 0
    try:
        if dry:
            return sum(con.execute(sql, args).fetchone()[0] for old in keys for sql, args in (
                ("SELECT count(*) FROM kv WHERE k=?", (f"durations:{old}",)),
                ("SELECT count(*) FROM check_pass WHERE repo_key=?", (old,))))
        with con:
            return key_migrate.rekey_rows(keys, lambda sql, args: con.execute(sql, args).rowcount)
    finally:
        con.close()


def _drop_empty(path: Path) -> None:
    """Remove the folder and the empty folders in it; any file left keeps its folder."""
    if not path.is_dir():
        return
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_dir() and not any(child.iterdir()):
            child.rmdir()
    if not any(path.iterdir()):
        path.rmdir()
