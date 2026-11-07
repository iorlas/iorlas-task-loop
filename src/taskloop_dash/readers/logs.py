"""Engine and worker logs behind storage-neutral readers and opaque cursors.

A later bead may swap the storage (another file layout, or a DB table) without
changing a view or the HTTP API. Rotation and age pruning belong to tl-zej9.18.
"""

import base64
import contextlib
import heapq
import json
import threading
import time
import zlib
from collections.abc import Callable
from pathlib import Path

from delegate import api
from taskloop_dash import jsonl
from taskloop_dash.jsonrec import Json
from taskloop_dash.views import live_events as ev
from tlkernel import factorydb, log, wire
from tlkernel.delegate import LiveEvent
from tlkernel.paths import ConfigDir

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

    def __init__(self, tag: str, live_dir: str) -> None:
        self.tag, self.live_dir = tag, live_dir
        self.offset = 0
        self.items: list[tuple[int, Json]] = []
        self.ident = 0

    def refresh(self) -> None:
        """Refresh through delegate's reader, clearing events when the stream resets."""
        result = api.live_read(self.live_dir, self.tag, self.offset, self.ident)
        if result.reset:
            self.items = []
        self.offset, self.ident = result.cursor, result.ident
        self.items += [(line.offset, ev.worker_event(line.event, self.tag, line.offset)) for line in result.lines]


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
        self.attempt = 0  # the run's newest attempt row (0: none yet); a cursor belongs to one attempt
        self.lock = threading.RLock()  # the server is threaded: one reader at a time advances the offsets and reads the items
        self.sources: dict[str, Source | EngineSource] = {ev.ENGINE: EngineSource(cfg, run)}

    def live_dir(self) -> Path:
        return self.cfg.live_dir(self.run)

    def refresh(self) -> None:
        with self.lock:
            self._refresh()

    def _attempt(self) -> int:
        found = factorydb.attempt_of(self.cfg.factory_db(), self.run)
        return self.attempt if found is None else found

    def _refresh(self) -> None:
        self.attempt = self._attempt()
        files = api.live_files(str(self.live_dir()))
        kept = {file.name for file in files}
        for tag in [t for t, s in self.sources.items() if isinstance(s, Source) and t not in kept]:
            del self.sources[tag]  # retention removed the stream
        for file in files:
            self.sources.setdefault(file.name, Source(file.name, str(self.live_dir())))
        for s in self.sources.values():
            s.refresh()

    def offsets(self) -> dict[str, int]:
        out = {t: s.offset for t, s in self.sources.items()}
        engine = self.sources[ev.ENGINE]
        if isinstance(engine, EngineSource):
            out["_engine_bytes"] = (decode(engine.cursor) or {}).get("engine", 0)
        out["_run"] = zlib.crc32(self.run.encode())  # a cursor belongs to one run
        out["_attempt"] = self.attempt  # and to one attempt of it
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
    """{events, cursor, reset}: the first MAX_PAGE events after `since`, else the newest `limit` events. A burst past one page is not
    cut: the cursor stops at the first event left over, so the next poll carries on from it. A cursor of another run, or of an
    earlier attempt of this one, is a `reset`: the newest events answer it. A `gap`: the cursor had read a worker file that
    retention has since removed, so events between it and now are gone."""
    reset = since is not None and (
        since.get("_run", zlib.crc32(run.run.encode())) != zlib.crc32(run.run.encode())
        or since.get("_attempt", run.attempt) != run.attempt)  # a cursor without the key is from before attempts: it continues
    if reset:
        since = None
    gap = since is not None and any(not t.startswith("_") and off > 0 and t not in run.sources for t, off in since.items())
    got = run.select(lambda t, off: since is None or off >= since.get(t, 0))
    cursor = run.offsets()
    if since is None:
        got = got[-max(1, min(limit, MAX_PAGE)):]
    else:
        for tag, off, _ in reversed(got[MAX_PAGE:]):
            cursor[tag] = off
        got = got[:MAX_PAGE]
    return {"events": [e for _, _, e in got], "cursor": encode(cursor), "reset": reset, "gap": gap}


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
    return wire.load(LiveEvent, dict(data, v=1))


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
        for file in api.live_files(str(self.cfg.live_dir(run))):
            number = file.name.partition("-")[0]
            if number.isdigit():
                out[int(number)] = tuple(self._live_records(run, file.name))
        return out

    def console(self, run: str) -> list[LiveEvent]:
        files = sorted(api.live_files(str(self.cfg.live_dir(run))), key=lambda f: f.mtime)
        return self._live_records(run, files[-1].name) if files else []

    def _live_records(self, run: str, name: str) -> list[LiveEvent]:
        cursor, ident = 0, 0
        out: list[LiveEvent] = []
        while True:
            result = api.live_read(str(self.cfg.live_dir(run)), name, cursor, ident)
            if result.reset:
                out = []
            for line in result.lines:
                with contextlib.suppress(ValueError):
                    out.append(live_event(line.event))
            if result.cursor == cursor:
                return out
            cursor, ident = result.cursor, result.ident
