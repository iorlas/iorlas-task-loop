"""The ask store: the open and parked asks of a repo, answered, amended, withdrawn and parked through one writer."""
import contextlib
from collections.abc import Callable
from typing import Any, Final, Protocol

from tlkernel import paths
from tlkernel.ask import Ask, AskAnswer, ThreadEntry
from tlkernel.askrows import AskRows, DbDocs, DbLedger
from tlkernel.dash import OwnerCause, Stick
from tlkernel.docstore import ForeignVersion, Ledger, Present, Torn, refusal
from tlkernel.enums import AskStatus
from tlkernel.ids import BeadId
from tlkernel.ledger import LedgerEntry, LedgerEvent
from tlkernel.wire import Refused

LIVE = (AskStatus.OPEN, AskStatus.PARKED)


HAD_PICK: Final = "had_pick_label"  # bead metadata: the pick label the park took off, to give back


ORPHAN: Final = "parked; its ask was dropped at upgrade; `tl answer --rerun` or reopen to re-ask"


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
        self.before: Callable[[LedgerEntry], None] | None = None  # the record that comes first: a bead comment (app/asks/ledgercomments.py)

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
            self.append(LedgerEntry(
                t=t, event=event, ask=a.id, bead=a.bead, repo=a.repo, question=a.decision, key=a.key, blocking=a.blocking,
                cause=a.owner_cause, cause_by=a.cause_by, answer=answer, outcome=a.outcome, outcome_ref=a.outcome_ref,
                similar=list(a.similar) if event == "raise" else [], why=why))

    def append(self, entry: LedgerEntry) -> None:
        """The comment first (`before`, when set: a refusal leaves no row), then the row: the comment is the record, the row its cache."""
        if self.before is not None:
            self.before(entry)
        if self.ledger is not None:
            self.ledger.append(entry)

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
        self.append(rows[-1].replace(**{"t": now, "event": event, "similar": [], "why": "", **changes}))
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
