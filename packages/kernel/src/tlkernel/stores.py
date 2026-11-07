"""The append-only log stores: one writer per file family, a missing or torn line reads as absent."""
import contextlib
import json
from pathlib import Path
from typing import Any, override

from jsonl_log import KEEP, ROTATE_BYTES, Entry

from tlkernel import events, factorydb, log, paths, timedrows, wire
from tlkernel.docstore import Item, Page
from tlkernel.guard import guard
from tlkernel.rotating import RotatingJsonl
from tlkernel.run import LoopLogLine
from tlkernel.snapshots import (
    StatusSnapshot,
)
from tlkernel.trace import RunTrace
from tlkernel.usage import USAGE_KEEP_S, UsageRow, rows_of


class JsonlStore[T]:
    """An append-only family: one record per line, read back by byte cursor."""

    def __init__(self, path: Path, decode: Any, cls: type[Any] | None = None, rotate_bytes: int = ROTATE_BYTES, keep: int = KEEP,
                 rotate_lock: Path | bool = False) -> None:
        self.file = RotatingJsonl(path, rotate_bytes, keep, rotate_lock)
        self._decode = decode
        self._cls = cls

    def append(self, rec: T) -> int:
        return self.file.append(wire.dump(rec))

    def read_from(self, offset: int = 0, limit: int | None = None) -> Page[T]:
        entries, cursor = self.file.read_from(offset, limit)
        return self._page(entries, cursor)

    def tail(self, n: int, before: int | None = None) -> Page[T]:
        entries = self.file.tail(n, before)
        return self._page(entries, entries[-1].end if entries else (before or 0))

    def _page(self, entries: list[Entry[dict[str, Any]]], cursor: int) -> Page[T]:
        items: list[Item[T]] = []
        for e in entries:
            with contextlib.suppress(ValueError):
                items.append(Item(e.start, e.end, self._decode(e.data)))
        return Page(items, cursor, len(entries) - len(items))


def _beside(path: Path, suffix: str) -> Path:
    return path.with_name(path.name + suffix)


def _one(cls: type) -> Any:
    def decode(data: Any) -> Any:
        return wire.load(cls, data)
    return decode


class RunLog(JsonlStore[log.EngineLog]):
    """The engine log of one run. Each end record that completes a timed thing also adds its `timed` row (contracts/timedrows.py); the
    row is best effort, the log is the record."""

    def __init__(self, cfg: paths.ConfigDir, run: str) -> None:
        super().__init__(cfg.engine_log(run), log.decode)
        self.cfg, self.run = cfg, run
        self.tracker: timedrows.Tracker | None = None

    def warm(self) -> timedrows.Tracker:
        """The pairing state of this run: a run that exec'd or took up again has the starts of its earlier process in the file."""
        if self.tracker is None:
            self.tracker = timedrows.Tracker(self.run)
            for earlier in self.read_from(0).items:
                self.tracker.feed(earlier.rec)
        return self.tracker

    @override
    def append(self, rec: log.EngineLog) -> int:
        tracker = None
        with contextlib.suppress(OSError, factorydb.DatabaseError):
            tracker = self.warm()  # read before the append: the file does not hold `rec` yet
        at = super().append(rec)
        if tracker is not None:
            item = tracker.feed(rec)
            if item is not None:
                with contextlib.suppress(OSError, factorydb.DatabaseError, factorydb.sqlite3.Error):
                    timedrows.add(self.cfg, item)
        return at


class EventLog(JsonlStore[events.Event]):
    def __init__(self, cfg: paths.ConfigDir) -> None:
        super().__init__(cfg.events(), events.decode)


class TraceStore(JsonlStore[RunTrace]):
    """Run traces; append and age retention share one outer lock."""

    def __init__(self, cfg: paths.ConfigDir) -> None:
        super().__init__(cfg.traces(), _one(RunTrace), rotate_lock=_beside(cfg.traces(), ".prune.lock"))

    def lock_path(self) -> Path:
        return self.file.path.with_name(self.file.path.name + ".prune.lock")

    @override
    def append(self, rec: RunTrace) -> int:
        with guard(self.lock_path()):
            return super().append(rec)


class LoopLog(JsonlStore[LoopLogLine]):
    """loop/<key>.jsonl: a line per bead the loop ran."""

    def __init__(self, cfg: paths.ConfigDir, key: str) -> None:
        super().__init__(cfg.loop_log(key), _one(LoopLogLine))


class UsageHistory(JsonlStore[UsageRow]):
    """The lane usage history: `tl lanes` is its one writer (`record`), age its only prune."""

    def __init__(self, cfg: paths.ConfigDir) -> None:
        super().__init__(cfg.usage_history(), _one(UsageRow), rotate_lock=_beside(cfg.usage_history(), ".lock"))

    def lock_path(self) -> Path:
        return self.file.path.with_name(self.file.path.name + ".lock")

    @override
    def append(self, rec: UsageRow) -> int:
        with guard(self.lock_path()):  # prune rewrites the file under this lock: a line appended meanwhile is not lost
            return super().append(rec)

    def record(self, snap: StatusSnapshot) -> None:
        for row in rows_of(snap):
            self.append(row)

    def rows(self) -> list[UsageRow]:
        return [i.rec for i in self.read_from(0).items]

    def prune(self, now: float) -> int:
        """Drop rows older than USAGE_KEEP_S (and lines that are no row); -> how many lines went. Rewrites only when one goes."""
        cut = now - USAGE_KEEP_S
        return self.file.rewrite(lambda line: self._at(line) >= cut)

    def _at(self, line: bytes) -> float:
        try:
            return self._decode(json.loads(line)).at
        except ValueError:
            return float("-inf")
