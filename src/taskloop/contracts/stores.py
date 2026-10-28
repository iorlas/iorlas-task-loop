"""One reader and one writer per file family. A missing, torn or stale (foreign `v`) file reads as absent."""
import dataclasses
import json
from pathlib import Path
from typing import Any, Protocol

from atomic_io import atomic_write_json
from jsonl_log import Entry, Jsonl

from taskloop.contracts import codec, events, log, paths
from taskloop.contracts.ask import Ask, AskAnswer
from taskloop.contracts.codec import CodecError
from taskloop.contracts.enums import AskStatus
from taskloop.contracts.ids import BeadId
from taskloop.contracts.loop import BadVersions, LoopCommand, LoopState, Rest
from taskloop.contracts.snapshots import DashState, Pin, ReleaseResult, ReposIndex, SessionIndex, SharedNotes, TasksSnapshot
from taskloop.contracts.trace import RunTrace

LIVE = (AskStatus.OPEN, AskStatus.PARKED)


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
        atomic_write_json(self.path, codec.to_json(rec), indent=1, fsync=False)

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
        self.file = Jsonl(path)
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

    def _page(self, entries: list[Entry[dict[str, Any]]], cursor: int) -> Page[T]:
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


class AskDocs(Protocol):
    """Where the ask documents live: one per bead (files for real, dicts for the fake)."""

    def of(self, key: str) -> Any: ...
    def keys(self) -> list[str]: ...


class AskFiles:
    def __init__(self, cfg: paths.ConfigDir) -> None:
        self.cfg = cfg

    def of(self, key: str) -> JsonStore[Ask]:
        return JsonStore(self.cfg.ask(key), Ask)

    def keys(self) -> list[str]:
        return self.cfg.ask_beads()


class AskStore:
    """The one reader and the one writer of asks/<bead>.json: the engine raises and consumes, `tl` sweeps and answers, the dashboard
    answers. One record per bead; a newer ask replaces the older. Every write re-reads first, so a stale copy never undoes a newer one."""

    def __init__(self, docs: AskDocs) -> None:
        self.docs = docs

    @classmethod
    def at(cls, cfg: paths.ConfigDir) -> "AskStore":
        return cls(AskFiles(cfg))

    def of(self, bead: BeadId | str) -> Any:
        return self.docs.of(str(bead))

    def get(self, bead: BeadId | str) -> Ask | None:
        return self.docs.of(str(bead)).read()

    def all(self) -> list[Ask]:
        names = self.docs.keys()
        return [a for a in (self.docs.of(k).read() for k in names) if a is not None]

    def live(self) -> list[Ask]:
        """Asks still waiting for an owner (open or parked), oldest first."""
        return sorted((a for a in self.all() if a.status in LIVE), key=lambda a: a.t)

    def pending(self) -> list[Ask]:
        """Asks no run has used yet: waiting for an answer, or answered and waiting for the next run. Oldest first."""
        return sorted((a for a in self.all() if a.consumed is None and a.status in (*LIVE, AskStatus.ANSWERED)), key=lambda a: a.t)

    def put(self, ask: Ask) -> None:
        self.docs.of(ask.bead).write(ask)

    def next_n(self, bead: BeadId | str) -> int:
        a = self.get(bead)
        return a.n + 1 if a else 1

    def state(self, bead: BeadId | str, ask_id: str) -> tuple[Ask | None, str]:
        """(the ask, why it cannot be answered): "" when it can; gone, superseded (a newer ask of the bead), withdrawn, closed,
        answered (first answer wins), consumed (a run already used the answer)."""
        a = self.get(bead)
        if a is None:
            return None, "gone"
        if a.id != ask_id:
            return a, "superseded"
        if a.status == AskStatus.WITHDRAWN:
            return a, "withdrawn"
        if a.status == AskStatus.CLOSED:
            return a, "closed"
        if a.consumed is not None:
            return a, "consumed"
        return a, "answered" if a.answer is not None else ""

    def answer(self, bead: BeadId | str, ask_id: str, answer: AskAnswer) -> tuple[Ask | None, str]:
        """File the owner's answer on a live, unanswered ask (the first one wins). -> (the ask, "" or why not)."""
        a, why = self.state(bead, ask_id)
        if a is None or why:
            return a, why
        done = dataclasses.replace(a, status=AskStatus.ANSWERED, answer=answer, answered=answer.t)
        self.put(done)
        return done, ""

    def amend(self, bead: BeadId | str, ask_id: str, answer: AskAnswer) -> tuple[Ask | None, str]:
        """Replace an answer no run has used yet."""
        a, why = self.state(bead, ask_id)
        if a is None or why not in ("", "answered"):
            return a, why
        done = dataclasses.replace(a, status=AskStatus.ANSWERED, answer=answer, answered=answer.t)
        self.put(done)
        return done, ""

    def consume(self, bead: BeadId | str, now: float) -> Ask | None:
        """A run starts from this ask (answered, or its bead changed): it will not be asked again. None when nothing is live."""
        a = self.get(bead)
        if a is None or a.status not in (*LIVE, AskStatus.ANSWERED) or a.consumed is not None:
            return None
        done = dataclasses.replace(a, status=AskStatus.ANSWERED, answered=a.answered or now, consumed=now)
        self.put(done)
        return done

    def withdraw(self, bead: BeadId | str, ask_id: str, why: str, now: float) -> tuple[Ask | None, str]:
        """The owner dismisses an ask no run has used. An answer given and not used goes with it."""
        a, problem = self.state(bead, ask_id)
        if a is None or problem in ("gone", "superseded", "closed", "consumed"):
            return a, problem
        if problem == "withdrawn":
            return a, ""
        done = dataclasses.replace(a, status=AskStatus.WITHDRAWN, closed_why=why, answered=now if a.answer else None)
        self.put(done)
        return done, ""

    def close(self, bead: BeadId | str, ask_id: str, why: str) -> bool:
        """The bead is closed or gone, or the run landed: close only the ask that is still the one read (a newer one stays)."""
        a = self.get(bead)
        if a is None or a.id != ask_id or a.status not in (*LIVE, AskStatus.ANSWERED) or a.consumed is not None:
            return False
        self.put(dataclasses.replace(a, status=AskStatus.CLOSED, closed_why=why))
        return True

    def park(self, bead: BeadId | str, ask_id: str) -> bool:
        a = self.get(bead)
        if a is None or a.id != ask_id or a.status != AskStatus.OPEN or a.answer is not None:
            return False
        self.put(dataclasses.replace(a, status=AskStatus.PARKED))
        return True


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
