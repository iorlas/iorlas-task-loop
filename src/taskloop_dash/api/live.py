"""The live feed of one run (87 §2, §6): the engine log and the worker's per-call live files, each a source with its own byte-offset
cursor, merged by time (a k-way merge of sorted files). `seq` = source tag + offset is the key the page dedupes by; the first load is
the newest events; a long-poll holds the request until a file grows."""

import base64
import heapq
import json
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from taskloop.contracts import log
from taskloop.contracts.locator import RunBundle
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

    def __init__(self, tag: str, path: str, worker: bool) -> None:
        self.tag, self.path, self.worker = tag, path, worker
        self.offset = 0
        self.items: list[tuple[int, Json]] = []

    def refresh(self) -> None:
        if jsonl.size_of(self.path) < self.offset:  # the file was replaced
            self.offset = 0
            self.items = []
        decode_one = ev.decode_worker if self.worker else log.decode
        rows, self.offset = jsonl.read_from(self.path, self.offset, decode_one)
        def build(r: Any, off: int) -> Json:
            return ev.worker_event(r, self.tag, off) if self.worker else ev.engine_event(r, off)

        self.items += [(off, build(r, off)) for off, r in rows if not isinstance(r, log.Beat)]  # a Beat is no event


class LiveRun:
    """A run's sources. Keep one per run between polls: each call reads only what the files gained."""

    def __init__(self, bundle: RunBundle) -> None:
        self.bundle = bundle
        log_path = str(bundle.log)
        self.log_path = log_path
        self.lock = threading.RLock()  # the server is threaded: one reader at a time advances the offsets and reads the items
        self.sources = {ev.ENGINE: Source(ev.ENGINE, log_path, False)}

    def live_dir(self) -> Path:
        return self.bundle.live

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
            self.sources.setdefault(tag, Source(tag, str(self.live_dir() / name), True))
        for s in self.sources.values():
            s.refresh()

    def offsets(self) -> dict[str, int]:
        return {t: s.offset for t, s in self.sources.items()}

    def select(self, keep: Callable[[str, int], bool]) -> list[tuple[str, int, Json]]:
        """(tag, offset, event) of the chosen events, merged by time (ties: the engine first, then file order)."""
        with self.lock:
            lists = [[(t, off, e) for off, e in s.items if keep(t, off)] for t, s in self.sources.items()]
        return list(heapq.merge(*lists, key=lambda x: (x[2]["t"], ev.rank(x[2]))))

    def events(self) -> list[Json]:
        return [e for _, _, e in self.select(lambda t, off: True)]


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


