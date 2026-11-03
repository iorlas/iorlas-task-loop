"""Engine and worker logs behind storage-neutral readers and opaque cursors.

A later bead may swap the storage (another file layout, or a DB table) without
changing a view or the HTTP API. Rotation and age pruning belong to tl-zej9.18.
"""

import base64
import heapq
import json
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

from taskloop.contracts import log, wire
from taskloop.contracts.delegate import LiveEvent
from taskloop.contracts.paths import ConfigDir
from taskloop_dash import jsonl
from taskloop_dash.jsonrec import Json
from taskloop_dash.views import live_events as ev

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

    def __init__(self, tag: str, path: str) -> None:
        self.tag, self.path = tag, path
        self.offset = 0
        self.items: list[tuple[int, Json]] = []

    def refresh(self) -> None:
        if jsonl.size_of(self.path) < self.offset:  # the file was replaced
            self.offset = 0
            self.items = []
        rows, self.offset = jsonl.read_from(self.path, self.offset, ev.decode_worker)
        self.items += [(off, ev.worker_event(r, self.tag, off)) for off, r in rows]


class EngineSource:
    """Use the same narrow reader as drawer history; cursor contents stay here."""

    def __init__(self, cfg: ConfigDir, run: str) -> None:
        self.logs, self.run = Logs(cfg), run
        self.offset = 0
        self.cursor = ""
        self.items: list[tuple[int, Json]] = []

    def refresh(self) -> None:
        rows, cursor = self.logs.read(self.run, self.cursor)
        after = (decode(cursor) or {}).get("engine", 0)
        if after < (decode(self.cursor) or {}).get("engine", 0):
            self.items = []
            self.offset = 0
        self.items += [(self.offset + i, ev.engine_event(r, self.offset + i)) for i, r in enumerate(rows)]
        self.offset += len(rows)
        self.cursor = cursor


class LiveRun:
    """A run's sources. Keep one per run between polls: each call reads only what the files gained."""

    def __init__(self, cfg: ConfigDir, run: str) -> None:
        self.cfg, self.run = cfg, run
        self.lock = threading.RLock()  # the server is threaded: one reader at a time advances the offsets and reads the items
        self.sources: dict[str, Source | EngineSource] = {ev.ENGINE: EngineSource(cfg, run)}

    def live_dir(self) -> Path:
        return self.cfg.live_dir(self.run)

    def refresh(self) -> None:
        with self.lock:
            self._refresh()

    def _refresh(self) -> None:
        try:
            names: list[str] = sorted(n for n in os.listdir(self.live_dir()) if n.endswith(".jsonl"))
        except OSError:
            names = []
        for name in names:
            tag = name[: -len(".jsonl")]
            self.sources.setdefault(tag, Source(tag, str(self.live_dir() / name)))
        for s in self.sources.values():
            s.refresh()

    def offsets(self) -> dict[str, int]:
        out = {t: s.offset for t, s in self.sources.items()}
        engine = self.sources[ev.ENGINE]
        if isinstance(engine, EngineSource):
            out["_engine_bytes"] = (decode(engine.cursor) or {}).get("engine", 0)
        return out

    def select(self, keep: Callable[[str, int], bool]) -> list[tuple[str, int, Json]]:
        """(tag, offset, event) of the chosen events, merged by time (ties: the engine first, then file order)."""
        with self.lock:
            lists = [[(t, off, e) for off, e in s.items if keep(t, off)] for t, s in self.sources.items()]
        return list(heapq.merge(*lists, key=lambda x: (x[2]["t"], ev.rank(x[2]))))

    def events(self) -> list[Json]:
        return [e for _, _, e in self.select(lambda t, off: True)]

    def read(self, cursor: str = "", wait: float = 0) -> Json:
        """The HTTP-facing interface: callers never decode or inspect a cursor."""
        return poll(self, decode(cursor), wait)


def page(run: LiveRun, since: dict[str, int] | None = None, limit: int = PAGE) -> Json:
    """{events, cursor}: what is new after `since`, else the newest `limit` events."""
    got = run.select(lambda t, off: since is None or off >= since.get(t, 0))
    return {"events": [e for _, _, e in got[-(MAX_PAGE if since is not None else max(1, min(limit, MAX_PAGE))):]],
            "cursor": encode(run.offsets())}


def poll(
    run: LiveRun,
    since: dict[str, int] | None,
    wait: float = 0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Json:
    """The page after `since`, held up to `wait` seconds until a file grows (long-poll); a first load never waits."""
    run.refresh()
    deadline = clock() + max(0.0, min(float(wait), 20.0))
    while since is not None and not page(run, since)["events"] and clock() < deadline:
        sleep(POLL_EVERY)
        run.refresh()
    return page(run, since)
def live_event(data: object) -> LiveEvent:
    """Decode the delegate console format, separately owned from engine state."""
    if not isinstance(data, dict):
        raise ValueError("not a live event")
    return wire.load(LiveEvent, {**{k: v for k, v in data.items() if k != "k"}, "kind": data.get("k"), "v": 1})


class Logs:
    """Run ids in, records and opaque cursors out; only this module knows paths."""

    def __init__(self, cfg: ConfigDir) -> None:
        self.cfg = cfg

    def read(self, run: str, cursor: str = "") -> tuple[tuple[log.EngineLog, ...], str]:
        offset = (decode(cursor) or {}).get("engine", 0)
        rows, after = jsonl.read_from(str(self.cfg.engine_log(run)), offset)
        return tuple(r for _, r in rows if not isinstance(r, log.Beat)), encode({"engine": after})

    def records(self, run: str) -> tuple[log.EngineLog, ...]:
        cursor = ""
        out: list[log.EngineLog] = []
        while True:
            rows, after = self.read(run, cursor)
            out.extend(rows)
            if after == cursor:
                return tuple(out)
            cursor = after

    def calls(self, run: str) -> dict[int, tuple[LiveEvent, ...]]:
        out: dict[int, tuple[LiveEvent, ...]] = {}
        for path in sorted(self.cfg.live_dir(run).glob("*.jsonl")):
            number = path.stem.partition("-")[0]
            if number.isdigit():
                out[int(number)] = tuple(jsonl.records(str(path), decode=live_event))
        return out

    def console(self, run: str) -> list[LiveEvent]:
        try:
            files = sorted(self.cfg.live_dir(run).glob("*.jsonl"), key=lambda f: f.stat().st_mtime)
        except OSError:
            return []
        return jsonl.records(str(files[-1]), decode=live_event) if files else []
