"""One reader and one writer per file family. A missing, torn or stale (foreign `v`) file reads as absent."""
import contextlib
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final, Protocol, override

from jsonl_log import KEEP, ROTATE_BYTES, Entry

from taskloop.contracts import docstore, events, factorydb, log, paths, timedrows, wire
from taskloop.contracts.ask import Ask, AskAnswer, ThreadEntry
from taskloop.contracts.askrows import AskRows, DbDocs, DbLedger
from taskloop.contracts.dash import OwnerCause, Stick
from taskloop.contracts.docrows import RowDoc, singleton
from taskloop.contracts.docstore import ForeignVersion, Item, JsonStore, Ledger, Page, Present, Torn, refusal
from taskloop.contracts.enums import AskStatus
from taskloop.contracts.guard import guard
from taskloop.contracts.ids import BeadId
from taskloop.contracts.ledger import LedgerEntry, LedgerEvent
from taskloop.contracts.loop import BadVersions, LoopCommand, LoopState, Rest
from taskloop.contracts.reponame import repo_name
from taskloop.contracts.rotating import RotatingJsonl
from taskloop.contracts.run import LoopLogLine
from taskloop.contracts.snapshots import (
    Pin,
    ReflectState,
    ReleaseResult,
    RepoEntry,
    ReposIndex,
    SharedNotes,
    StatusSnapshot,
    StatusTried,
)
from taskloop.contracts.trace import RunTrace
from taskloop.contracts.usage import USAGE_KEEP_S, UsageRow, rows_of
from taskloop.contracts.wire import Refused

LIVE = (AskStatus.OPEN, AskStatus.PARKED)
HAD_PICK: Final = "had_pick_label"  # bead metadata: the pick label the park took off, to give back
ORPHAN: Final = "parked; its ask was dropped at upgrade; `tl answer --rerun` or reopen to re-ask"
Absent = docstore.Absent
type Read[T] = docstore.Read[T]


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


class LedgerStore(DbLedger):
    """The authoritative ask ledger in factory.db."""
    def __init__(self, cfg: paths.ConfigDir) -> None:
        super().__init__(AskRows(cfg))


class AskDocs(Protocol):
    """Where the ask documents live: DB rows for real, dicts for the fake."""

    def of(self, key: str) -> Any: ...
    def keys(self) -> list[str]: ...


class AskStore:
    """One ask per bead. `held` makes read, decision, document and ledger writes atomic;
    the in-memory fake uses a null context."""

    def __init__(self, docs: AskDocs, ledger: Ledger[LedgerEntry] | None = None,
                 held: Callable[[str], contextlib.AbstractContextManager[None]] | None = None) -> None:
        self.docs = docs
        self.ledger = ledger
        self.held = held

    @classmethod
    def at(cls, cfg: paths.ConfigDir) -> AskStore:
        rows = AskRows(cfg)
        return cls(DbDocs(rows), DbLedger(rows), lambda bead: rows.transaction())

    def _lock(self, bead: BeadId) -> contextlib.AbstractContextManager[None]:
        return self.held(str(bead)) if self.held is not None else contextlib.nullcontext()

    def log(self, a: Ask, event: LedgerEvent, t: float, why: str = "") -> None:
        """One ledger row of this transition, carrying the ask's answer, cause and outcome as they are now."""
        if self.ledger is not None:
            answer = (a.answer.text or a.answer.action) if a.answer else ""
            self.ledger.append(LedgerEntry(
                t=t, event=event, ask=a.id, bead=a.bead, repo=a.repo, question=a.decision, key=a.key, blocking=a.blocking,
                cause=a.owner_cause, cause_by=a.cause_by, answer=answer, outcome=a.outcome, outcome_ref=a.outcome_ref,
                similar=list(a.similar) if event == "raise" else [], why=why))

    def rows(self) -> list[LedgerEntry]:
        """Every ledger row, oldest first ([] for a store with no ledger)."""
        return [i.rec for i in self.ledger.read_from(0).items] if self.ledger is not None else []

    def history(self, ask_id: str) -> list[LedgerEntry]:
        return [e for e in self.rows() if e.ask == ask_id]

    def file(self, ask: Ask) -> None:
        """A new ask: the document and the ledger's raise row. Refused when the stored body is torn."""
        with self._lock(ask.bead):
            self.get(ask.bead)
            self.put(ask)
            self.log(ask, "raise", ask.t)

    def of(self, bead: BeadId) -> Any:
        return self.docs.of(str(bead))

    def get(self, bead: BeadId) -> Ask | None:
        """The bead's ask; None when it has none or it is of another version (an orphan). A torn body is Refused, never read as no ask:
        the next write would overwrite what the owner may still need."""
        r = self.docs.of(str(bead)).read()
        if isinstance(r, Torn):
            raise Refused(refusal(r))
        return r.rec if isinstance(r, Present) else None

    def all(self) -> list[Ask]:
        """Every readable ask (`orphans` and `torn` name the unreadable rows)."""
        names = self.docs.keys()
        return [r.rec for r in (self.docs.of(k).read() for k in names) if isinstance(r, Present)]

    def orphans(self) -> list[str]:
        """Beads whose ask is of another version: the bead may still be parked on it."""
        names = self.docs.keys()
        return [k for k in names if isinstance(self.docs.of(k).read(), ForeignVersion)]

    def torn(self) -> list[str]:
        """Beads whose stored ask body is torn, listed by what is wrong; the owner fixes or deletes it."""
        names = self.docs.keys()
        return [f"{k}: {refusal(r)}" for k in names if isinstance(r := self.docs.of(k).read(), Torn)]

    def drop(self, bead: BeadId) -> None:
        """Delete the bead's ask row, whatever its body holds."""
        self.docs.of(str(bead)).delete()

    def live(self) -> list[Ask]:
        """Asks still waiting for an owner (open or parked), oldest first."""
        return sorted((a for a in self.all() if a.status in LIVE), key=lambda a: a.t)

    def pending(self) -> list[Ask]:
        """Asks no run has used yet: waiting for an answer, or answered and waiting for the next run. Oldest first."""
        return sorted((a for a in self.all() if a.consumed is None and a.status in (*LIVE, AskStatus.ANSWERED)), key=lambda a: a.t)

    def put(self, ask: Ask) -> None:
        self.docs.of(ask.bead).write(ask)

    def next_n(self, bead: BeadId) -> int:
        a = self.get(bead)
        return a.n + 1 if a else 1

    def state(self, bead: BeadId, ask_id: str) -> tuple[Ask | None, str]:
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

    def answer(self, bead: BeadId, ask_id: str, answer: AskAnswer) -> tuple[Ask | None, str]:
        """File the owner's answer on a live, unanswered ask (the first one wins). -> (the ask, "" or why not)."""
        with self._lock(bead):
            a, why = self.state(bead, ask_id)
            if a is None or why:
                if a is not None:
                    self.log(a.replace(id=ask_id, answer=answer), "answer_refused", answer.t, why=why)
                return a, why
            done = a.replace(status=AskStatus.ANSWERED, answer=answer, answered=answer.t)
            self.put(done)
            self.log(done, "answer", answer.t)
        return done, ""

    def amend(self, bead: BeadId, ask_id: str, answer: AskAnswer) -> tuple[Ask | None, str]:
        """Replace an answer no run has used yet."""
        with self._lock(bead):
            a, why = self.state(bead, ask_id)
            if a is None or why not in ("", "answered"):
                return a, why
            done = a.replace(status=AskStatus.ANSWERED, answer=answer, answered=answer.t)
            self.put(done)
            self.log(done, "answer", answer.t)
        return done, ""

    def consume(self, bead: BeadId, now: float, *, unanswered: bool = False) -> Ask | None:
        """A run starts from this ask: it will not be asked again. None when nothing is live, or when the ask has no answer
        (open or parked) and `unanswered` is not said: only a run that goes on because its bead changed (or --fresh) passes it.
        The answer is judged on the copy read under the lock, so one filed meanwhile is kept, never overwritten with none."""
        with self._lock(bead):
            a = self.get(bead)
            if a is None or a.status not in (*LIVE, AskStatus.ANSWERED) or a.consumed is not None:
                return None
            if a.answer is None and not unanswered:
                return None
            done = a.replace(status=AskStatus.ANSWERED, answered=a.answered or now, consumed=now)
            self.put(done)
            self.log(done, "consume", now)
        return done

    def withdraw(self, bead: BeadId, ask_id: str, why: str, now: float) -> tuple[Ask | None, str]:
        """The owner dismisses an ask no run has used. An answer given and not used goes with it."""
        with self._lock(bead):
            a, problem = self.state(bead, ask_id)
            if a is None or problem in ("gone", "superseded", "closed", "consumed"):
                return a, problem
            if problem == "withdrawn":
                return a, ""
            done = a.replace(status=AskStatus.WITHDRAWN, closed_why=why, answered=now if a.answer else None)
            self.put(done)
            self.log(done, "withdraw", now, why=why)
        return done, ""

    def close(self, bead: BeadId, ask_id: str, why: str, now: float = 0.0) -> bool:
        """The bead is closed or gone, or the run landed: close only the ask that is still the one read (a newer one stays)."""
        with self._lock(bead):
            a = self.get(bead)
            if a is None or a.id != ask_id or a.status not in (*LIVE, AskStatus.ANSWERED) or a.consumed is not None:
                return False
            done = a.replace(status=AskStatus.CLOSED, closed_why=why)
            self.put(done)
            self.log(done, "close", now, why=why)
        return True

    def park(self, bead: BeadId, ask_id: str) -> bool:
        with self._lock(bead):
            a = self.get(bead)
            if a is None or a.id != ask_id or a.status != AskStatus.OPEN or a.answer is not None:
                return False
            self.put(a.replace(status=AskStatus.PARKED))
            return True

    def follow(self, ask_id: str, event: LedgerEvent, now: float, **changes: Any) -> bool:
        """A row after the newest one of the ask, with `changes` (cause, outcome...). Works for a past ask too: its document may
        be gone (one per bead) but its ledger rows are not. -> False when the ledger has never heard of the ask."""
        rows = [row for row in self.history(ask_id) if row.event != "answer_refused"]
        if not rows or self.ledger is None:
            return False
        self.ledger.append(rows[-1].replace(**{"t": now, "event": event, "similar": [], "why": "", **changes}))
        return True

    def correct_cause(self, bead: BeadId, ask_id: str, cause: OwnerCause, now: float) -> bool:
        """The owner names the cause of an ask: on the document while it is still the bead's ask, and a ledger row."""
        with self._lock(bead):
            a = self.get(bead)
            if a is not None and a.id == ask_id:
                self.put(a.replace(owner_cause=cause, cause_by="owner"))
            return self.follow(ask_id, "cause", now, cause=cause, cause_by="owner")

    def stuck(self, bead: BeadId, ask_id: str, outcome: Stick, ref: str, now: float) -> bool:
        """What the owner made of the answer (adr, ref, factory, fix, demote, once): on the document while it is still the bead's ask,
        and a ledger row (`demote` for a demotion, `stick` for the rest)."""
        with self._lock(bead):
            a = self.get(bead)
            if a is not None and a.id == ask_id:
                self.put(a.replace(outcome=outcome, outcome_ref=ref))
            return self.follow(ask_id, "demote" if outcome is Stick.DEMOTE else "stick", now, outcome=outcome, outcome_ref=ref)

    def say(self, bead: BeadId, ask_id: str, entry: ThreadEntry) -> tuple[Ask | None, str]:
        """An ask-back entry on a live ask (the ask stays open). -> (the ask, "" or why not)."""
        with self._lock(bead):
            a, why = self.state(bead, ask_id)
            if a is None or why not in ("", "answered"):
                return a, why
            done = a.replace(thread=[*a.thread, entry])
            self.put(done)
            return done, ""


class LoopStateStore(JsonStore[LoopState]):
    def __init__(self, cfg: paths.ConfigDir, repo_key: str) -> None:
        super().__init__(cfg.loop_state(repo_key), LoopState)


class LoopCommandStore(JsonStore[LoopCommand]):
    def __init__(self, cfg: paths.ConfigDir, repo_key: str) -> None:
        super().__init__(cfg.loop_command(repo_key), LoopCommand)


class RestStore(JsonStore[Rest]):
    def __init__(self, cfg: paths.ConfigDir, repo_key: str) -> None:
        super().__init__(cfg.loop_rest(repo_key), Rest)


class StatusStore(RowDoc[StatusSnapshot]):
    def __init__(self, cfg: paths.ConfigDir, quiet: bool = False) -> None:
        super().__init__(singleton(cfg, StatusSnapshot, "snapshot:delegate.status", cfg.snapshot("delegate", "status"), quiet).docs, "")


class StatusTriedStore(RowDoc[StatusTried]):
    def __init__(self, cfg: paths.ConfigDir) -> None:
        super().__init__(singleton(cfg, StatusTried, "snapshot:delegate.tried", cfg.snapshot("delegate", "tried")).docs, "")


class SharedNotesStore(RowDoc[SharedNotes]):
    def __init__(self, cfg: paths.ConfigDir, repo_key: str) -> None:
        super().__init__(singleton(cfg, SharedNotes, "shared:" + repo_key, cfg.shared(repo_key)).docs, "")


class ReposStore:
    """The repos index: every repo `tl` has seen, by name, as the `kv` row `repos` of factory.db. Adding one reads and writes under a lock,
    so two processes never drop a repo. An older tl's repos.json is adopted on the first read (a v1 file, keyed by path, is converted
    first); no reader of v1 stays. `quiet` (the dashboard): a database that cannot be opened reads as no repos, and nothing is adopted."""

    def __init__(self, cfg: paths.ConfigDir, quiet: bool = False) -> None:
        self.doc = singleton(cfg, ReposIndex, "repos", cfg.repos(), quiet)
        self.path = cfg.repos()  # the older file
        self.lock = cfg.lock_record("repos", "index")

    def get(self) -> ReposIndex | None:
        return self.doc.get()

    def write(self, rec: ReposIndex) -> None:
        self.doc.write(rec)

    def index(self) -> ReposIndex:
        """The index (empty when there is none). One of another version is an error (ValueError), never read as empty."""
        read = self.doc.read()
        if isinstance(read, Present):
            return read.rec
        if isinstance(read, Absent):
            return ReposIndex()
        if isinstance(read, ForeignVersion) and read.found == 1:
            return self._convert()
        raise ValueError(self._refusal())

    def _refusal(self) -> str:
        return (f"{self.path} (or its row in factory.db) is not a repos index of this version: delete it; "
                "every tl process registers its repo again")

    def _convert(self) -> ReposIndex:
        """v1 (path to added) to v2 (name to path and added). Of paths with one name the first stays; the rest are said and dropped."""
        with guard(self.lock):
            body = json.loads(self.path.read_text(encoding="utf-8"))
            if body.get("v") == 2:
                return wire.load(ReposIndex, body)
            repos: dict[str, RepoEntry] = {}
            for path, ent in body.get("repos", {}).items():
                name = repo_name(path)
                if name in repos:
                    sys.stderr.write(f"tl: repos.json: {path} dropped, {name} is already {repos[name].path}\n")
                    continue
                repos[name] = RepoEntry(path=path, added=ent["added"])
            idx = ReposIndex(repos=repos)
            self.write(idx)
            with contextlib.suppress(OSError):
                self.path.unlink()
            return idx

    def known(self) -> list[str]:
        """The repo folders, oldest first."""
        return [e.path for e in self.index().repos.values()]

    def path_of(self, name: str) -> str:
        """The folder of repo `name`: the name, or the folder when it is one; unknown and ambiguous names are a ValueError with the fix."""
        idx = self.index().repos
        if name in idx:
            return idx[name].path
        short = [n for n in idx if n.rsplit("/", 1)[-1] == name]
        if len(short) == 1:
            return idx[short[0]].path
        if short:
            raise ValueError(f"repo {name!r} is ambiguous ({', '.join(sorted(short))}): give the full owner/name")
        raise ValueError(f"repo {name!r} is not registered: run `tl register` in its folder; known: {', '.join(sorted(idx)) or 'none'}")

    def add(self, path: str, now: float) -> bool:
        """Register `path`; False when it was known. A name another folder holds is a ValueError. Another version is a ValueError too,
        and the file is never overwritten."""
        if path in self.known():
            return False
        name = repo_name(path)
        with guard(self.lock):
            idx = self.index()
            if any(e.path == path for e in idx.repos.values()):
                return False
            if name in idx.repos:
                held = idx.repos[name].path
                raise ValueError(f"repo name {name!r} is taken by {held}: remove that entry (`tl prune` drops a folder that is gone)")
            self.write(idx.replace(repos={**idx.repos, name: RepoEntry(path=path, added=now)}))
            return True

    def drop_missing(self, exists: Callable[[str], bool]) -> list[str]:
        """Drop the entries whose folder `exists` says is gone. -> their names."""
        with guard(self.lock):
            idx = self.index()
            gone = [n for n, e in idx.repos.items() if not exists(e.path)]
            if gone:
                self.write(idx.replace(repos={n: e for n, e in idx.repos.items() if n not in gone}))
            return gone


class PinStore(RowDoc[Pin]):
    def __init__(self, cfg: paths.ConfigDir) -> None:
        super().__init__(singleton(cfg, Pin, "pin", cfg.pin()).docs, "")


class ReleaseResultStore(RowDoc[ReleaseResult]):
    def __init__(self, cfg: paths.ConfigDir) -> None:
        super().__init__(singleton(cfg, ReleaseResult, "release:last", cfg.release_result()).docs, "")


class BadVersionStore(RowDoc[BadVersions]):
    def __init__(self, cfg: paths.ConfigDir) -> None:
        super().__init__(singleton(cfg, BadVersions, "bad-versions", cfg.bad_versions()).docs, "")


class ReflectStateStore(RowDoc[ReflectState]):
    def __init__(self, cfg: paths.ConfigDir) -> None:
        super().__init__(singleton(cfg, ReflectState, "reflect:digest", cfg.reflect_state()).docs, "")
