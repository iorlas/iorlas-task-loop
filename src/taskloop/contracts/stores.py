"""One reader and one writer per file family. A missing, torn or stale (foreign `v`) file reads as absent."""
import dataclasses
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from taskloop.contracts import codec, events, jsonl, log, paths
from taskloop.contracts.ask import Ask
from taskloop.contracts.codec import CodecError
from taskloop.contracts.ids import BeadId
from taskloop.contracts.loop import BadVersions, LoopCommand, LoopState, Rest
from taskloop.contracts.snapshots import DashState, Pin, ReleaseResult, ReposIndex, SessionIndex, SharedNotes, TasksSnapshot
from taskloop.contracts.trace import RunTrace


class JsonStore[T]:
    """One JSON document (indent 1), replaced atomically: a reader sees the old file or the new one, never half."""

    def __init__(self, path: Path, cls: type[T]) -> None:
        self.path = Path(path)
        self.cls = cls

    def read(self) -> T | None:
        try:
            return codec.from_json(self.cls, json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError):  # CodecError and StaleRecord are ValueErrors
            return None

    def write(self, rec: T) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=self.path.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(codec.to_json(rec), f, indent=1, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)


@dataclasses.dataclass(frozen=True)
class Item[T]:
    start: int
    end: int
    rec: T


@dataclasses.dataclass(frozen=True)
class Page[T]:
    items: list[Item[T]]
    cursor: int
    skipped: int = 0  # complete lines that were not a record of this family (stale v, unknown kind, bad JSON shape)


class JsonlStore[T]:
    """An append-only family: one record per line, read back by byte cursor."""

    def __init__(self, path: Path, decode: Any, cls: type[Any] | None = None) -> None:
        self.file = jsonl.Jsonl(path)
        self._decode = decode
        self._cls = cls

    def append(self, rec: T) -> int:
        return self.file.append(codec.to_json(rec))

    def read_from(self, offset: int = 0, limit: int | None = None) -> Page[T]:
        entries, cursor = self.file.read_from(offset, limit)
        return self._page(entries, cursor)

    def tail(self, n: int, before: int | None = None) -> Page[T]:
        entries = self.file.tail(n, before)
        return self._page(entries, entries[-1].end if entries else (before or 0))

    def _page(self, entries: list[jsonl.Entry], cursor: int) -> Page[T]:
        items: list[Item[T]] = []
        for e in entries:
            try:
                items.append(Item(e.start, e.end, self._decode(e.data)))
            except CodecError:
                pass
        return Page(items, cursor, len(entries) - len(items))


def _one(cls: type) -> Any:
    def decode(data: Any) -> Any:
        return codec.from_json(cls, data)
    return decode


class RunLog(JsonlStore[log.EngineLog]):
    def __init__(self, cfg: paths.ConfigDir, run: str) -> None:
        super().__init__(cfg.engine_log(run), log.decode)


class EventLog(JsonlStore[events.Event]):
    def __init__(self, cfg: paths.ConfigDir) -> None:
        super().__init__(cfg.events(), events.decode)


class TraceStore(JsonlStore[RunTrace]):
    def __init__(self, cfg: paths.ConfigDir) -> None:
        super().__init__(cfg.traces(), _one(RunTrace))


class AskStore:
    def __init__(self, cfg: paths.ConfigDir) -> None:
        self.cfg = cfg

    def of(self, bead: BeadId | str) -> JsonStore[Ask]:
        return JsonStore(self.cfg.ask(bead), Ask)


class LoopStateStore(JsonStore[LoopState]):
    def __init__(self, cfg: paths.ConfigDir, repo_key: str) -> None:
        super().__init__(cfg.loop_state(repo_key), LoopState)


class LoopCommandStore(JsonStore[LoopCommand]):
    def __init__(self, cfg: paths.ConfigDir, repo_key: str) -> None:
        super().__init__(cfg.loop_command(repo_key), LoopCommand)


class RestStore(JsonStore[Rest]):
    def __init__(self, cfg: paths.ConfigDir, repo_key: str) -> None:
        super().__init__(cfg.loop_rest(repo_key), Rest)


class SnapshotStore(JsonStore[TasksSnapshot]):
    def __init__(self, cfg: paths.ConfigDir, repo_key: str) -> None:
        super().__init__(cfg.snapshot(repo_key, "tasks"), TasksSnapshot)


class SharedNotesStore(JsonStore[SharedNotes]):
    def __init__(self, cfg: paths.ConfigDir, repo_key: str) -> None:
        super().__init__(cfg.shared(repo_key), SharedNotes)


class SessionStore(JsonStore[SessionIndex]):
    def __init__(self, cfg: paths.ConfigDir, session: str) -> None:
        super().__init__(cfg.session(session), SessionIndex)


class ReposStore(JsonStore[ReposIndex]):
    def __init__(self, cfg: paths.ConfigDir) -> None:
        super().__init__(cfg.repos(), ReposIndex)


class PinStore(JsonStore[Pin]):
    def __init__(self, cfg: paths.ConfigDir) -> None:
        super().__init__(cfg.pin(), Pin)


class ReleaseResultStore(JsonStore[ReleaseResult]):
    def __init__(self, cfg: paths.ConfigDir) -> None:
        super().__init__(cfg.release_result(), ReleaseResult)


class DashStateStore(JsonStore[DashState]):
    def __init__(self, cfg: paths.ConfigDir) -> None:
        super().__init__(cfg.dash_state(), DashState)


class BadVersionStore(JsonStore[BadVersions]):
    def __init__(self, cfg: paths.ConfigDir) -> None:
        super().__init__(cfg.bad_versions(), BadVersions)
