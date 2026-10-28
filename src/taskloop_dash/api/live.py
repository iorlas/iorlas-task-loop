"""The live feed of one run (87 §2, §6): the engine log and the worker's per-call live files, each a source with its own byte-offset
cursor, merged by time (a k-way merge of sorted files). `seq` = source tag + offset is the key the page dedupes by; the first load is
the newest events with a `before` cursor for earlier ones; a long-poll holds the request until a file grows."""

import base64
import heapq
import json
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

from taskloop.contracts import log
from taskloop.contracts.paths import ConfigDir
from taskloop_dash import jsonl
from taskloop_dash.views import live_events as ev
from taskloop_dash.views import live_state

PAGE = 300  # events on a first load
MAX_PAGE = 2000  # the most one answer carries
POLL_EVERY = 0.25  # seconds between stats of the files while a long-poll holds


def encode(cursor: dict[str, int]) -> str:
    return base64.urlsafe_b64encode(json.dumps(cursor, separators=(",", ":")).encode()).decode()


def decode(text: str | None) -> dict[str, int] | None:
    """The offsets a cursor holds; None for none or a cursor that is not one."""
    if not text:
        return None
    try:
        cur = json.loads(base64.urlsafe_b64decode(text.encode() + b"=" * (-len(text) % 4)))
    except (ValueError, TypeError):
        return None
    return {k: v for k, v in cur.items() if isinstance(v, int)} if isinstance(cur, dict) else None


class Source:
    """One file: its events so far, and the offset after the last complete line read."""

    def __init__(self, tag: str, path: str, worker: bool) -> None:
        self.tag, self.path, self.worker = tag, path, worker
        self.offset = 0
        self.items: list[tuple[int, dict]] = []

    def refresh(self) -> None:
        if jsonl.size_of(self.path) < self.offset:  # the file was replaced
            self.offset, self.items = 0, []
        decode_one = ev.decode_worker if self.worker else log.decode
        rows, self.offset = jsonl.read_from(self.path, self.offset, decode_one)
        build = (lambda r, off: ev.worker_event(r, self.tag, off)) if self.worker else ev.engine_event
        self.items += [(off, build(r, off)) for off, r in rows]


class LiveRun:
    """A run's sources. Keep one per run between polls: each call reads only what the files gained."""

    def __init__(self, log_path: str) -> None:
        self.log_path = log_path
        self.lock = threading.RLock()  # the server is threaded: one reader at a time advances the offsets and reads the items
        self.sources = {ev.ENGINE: Source(ev.ENGINE, log_path, False)}

    def live_dir(self) -> Path:
        run = Path(self.log_path).stem
        return ConfigDir(Path(self.log_path).parent.parent).live_dir(run)

    def refresh(self) -> None:
        with self.lock:
            self._refresh()

    def _refresh(self) -> None:
        try:
            names = sorted(n for n in os.listdir(self.live_dir()) if n.endswith(".jsonl"))
        except OSError:
            names = []
        for name in names:
            tag = name[: -len(".jsonl")]
            self.sources.setdefault(tag, Source(tag, str(self.live_dir() / name), True))
        for s in self.sources.values():
            s.refresh()

    def offsets(self) -> dict[str, int]:
        return {t: s.offset for t, s in self.sources.items()}

    def sizes(self) -> dict[str, int]:
        return {t: jsonl.size_of(s.path) for t, s in self.sources.items()}

    def select(self, keep: Callable[[str, int], bool]) -> list[tuple[str, int, dict]]:
        """(tag, offset, event) of the chosen events, merged by time (ties: the engine first, then file order)."""
        with self.lock:
            lists = [[(t, off, e) for off, e in s.items if keep(t, off)] for t, s in self.sources.items()]
        return list(heapq.merge(*lists, key=lambda x: (x[2]["t"], ev.rank(x[2]))))

    def events(self) -> list[dict]:
        return [e for _, _, e in self.select(lambda t, off: True)]

    def is_alive(self, now: float, stale: float) -> bool:
        """Running until the end record is written; stale only when no file of the run (engine log, worker live files) was
        written for `stale` seconds, the engine's heartbeat having lapsed. No process is probed: a scripted lane has none."""
        if any(e["k"] == "close" for e in self.events()):
            return False
        newest = 0.0
        for s in self.sources.values():
            try:
                newest = max(newest, os.stat(s.path).st_mtime)
            except OSError:
                continue
        return now - newest < stale


def before_cursor(run: LiveRun, shown: list[tuple[str, int, dict]], older: bool) -> str | None:
    """Where the events before `shown` end, per source; None when nothing is left before them."""
    if not older:
        return None
    first: dict[str, int] = {}
    for tag, off, _ in shown:
        first.setdefault(tag, off)
    return encode({t: first.get(t, s.offset) for t, s in run.sources.items()})


def page(run: LiveRun, since: dict[str, int] | None = None, before: dict[str, int] | None = None, limit: int = PAGE) -> dict:
    """{events, cursor, before}: what is new after `since`; else the newest `limit` events (or those before `before`)."""
    limit = max(1, min(int(limit), MAX_PAGE))
    if since is not None:
        got = run.select(lambda t, off: off >= since.get(t, 0))
        return {"events": [e for _, _, e in got[-MAX_PAGE:]], "cursor": encode(run.offsets()), "before": None}
    limit_of = (lambda t, off: off < before.get(t, 0)) if before is not None else (lambda t, off: True)
    got = run.select(limit_of)
    tail = got[-limit:]
    left = len(got) > len(tail)
    return {"events": [e for _, _, e in tail], "cursor": encode(run.offsets()), "before": before_cursor(run, tail, left)}


def poll(
    run: LiveRun,
    since: dict[str, int] | None,
    wait: float = 0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    """The page after `since`, held up to `wait` seconds until a file grows (long-poll); a first load never waits."""
    run.refresh()
    deadline = clock() + max(0.0, min(float(wait), 20.0))
    while since is not None and not page(run, since)["events"] and clock() < deadline:
        sleep(POLL_EVERY)
        run.refresh()
    return page(run, since)


def log_mtime(root: Path, run: str, event: dict) -> float | None:
    """When the log file of an open check or gate last grew (what 'last output Ns ago' counts from)."""
    rel = event.get("log") or ""
    if not rel:
        return None
    path = Path(rel) if os.path.isabs(rel) else ConfigDir(root).run_dir(run) / rel
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def answer(
    run: LiveRun,
    bead: str,
    newest: str,
    alive: bool,
    since: str | None = None,
    before: str | None = None,
    wait: float = 0,
    limit: int = PAGE,
    now: float | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """The /api/live object for one run: its page of events, the state line, the worker, and what the page needs to follow a retry."""
    now = now or time.time()
    name = Path(run.log_path).stem
    root = Path(run.log_path).parent.parent
    pg = poll(run, decode(since), wait, sleep) if before is None else page(run, None, decode(before), limit)
    if since is None and before is None:
        pg = page(run, None, None, limit)
    every = run.events()
    state = live_state.state_of(every, now, alive, lambda e: log_mtime(root, name, e))
    steps = [e for e in every if e["k"] == "step_start"]
    started = next((e["t"] for e in every if e["k"] == "run_start"), None)
    return {
        "found": True,
        "bead": bead,
        "run": name,
        "newest": newest,
        "now": now,
        "running": state["what"] != "ended",
        "state": state,
        "worker": live_state.worker_of(every),
        "step": steps[-1]["step"] if steps else None,
        "started": started,
        **pg,
    }
