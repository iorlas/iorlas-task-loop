"""Owner ask operations and their terminal presentation, owned by the asks node."""
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from tlkernel import wire
from tlkernel.ask import Ask, AskAction
from tlkernel.askstore import AskStore
from tlkernel.beadsport import BdFailure, Beads
from tlkernel.ids import BeadId
from tlkernel.lookrows import LookRows
from tlkernel.paths import ConfigDir

from taskloop.app.asks import intake, sweeps
from taskloop.app.asks import owner_verbs as requests

Out = Callable[[str], None]
FLAG_ACTIONS: Final[tuple[AskAction, ...]] = ("rerun", "confirm", "split")  # `tl answer --rerun|--confirm|--split`
SAYS: Final = {"gone": "there is no ask for this bead", "superseded": "the engine asked again; the new ask replaces this one",
        "withdrawn": "the ask was withdrawn", "closed": "the ask is closed", "consumed": "a run already used the answer",
        "answered": "this ask is already answered (replace the answer with --amend)"}
NEXT: Final = "The bead %s runs again from your answer on the next pass of its loop."


@dataclass(frozen=True)
class Arguments:
    """An owner operation, independent of the command-line parser."""

    op: str
    bead: BeadId | None = None
    text: tuple[str, ...] = ()
    json: bool = False
    option: int | None = None
    verdict: str | None = None
    rerun: bool = False
    confirm: bool = False
    split: bool = False
    amend: bool = False
    expect: str | None = None
    waive: str | None = None
    defer: str | None = None
    drop: str | None = None
    approval: str | None = None
    until: str | None = None
    release: bool = False


def action_of(a: Arguments, ask: Ask | None) -> tuple[AskAction, str]:
    """(the typed action, its text): --option N picks one of the ask's own options; a flag names a bare action; words are `text`."""
    words = " ".join(a.text or [])
    pick = a.option
    if pick is not None and ask is not None and 1 <= pick <= len(ask.options):
        o = ask.options[pick - 1]
        return o.action, " ".join(x for x in (o.text, words) if x)
    verdict = a.verdict
    if verdict:  # the three answers an owner gives a question about work: yes as it is, do the work, no
        decline = words or "declined by the owner: do not do this"
        if verdict == "decline":
            return "text", decline
        return ("confirm" if verdict == "confirm" else "rerun"), words
    for flag in FLAG_ACTIONS:
        if getattr(a, flag, False):
            return flag, words
    return "text", words


def listing(asks: list[Ask], out: Out, as_json: bool, orphans: list[str]) -> None:
    if as_json:
        out(json.dumps([wire.dump(x) for x in asks], indent=1))
        return
    for k in asks:
        out(f"{k.bead:<22} {k.kind.value:<8} {(k.title or k.decision)[:70]}")
        out("    " + k.decision)
        for n, o in enumerate(k.options, 1):
            out(f"    {n}. {'* ' if o.recommended else ''}{o.label}: {o.consequence}")
        out(f"    (tl answer {k.bead} --option N | words)")
    for line in orphans:
        out(line)
    if not asks and not orphans:
        out("nothing waits on you")


def age(asks: AskStore, now: float, out: Out) -> int:
    """How long each pending ask has waited; an answer no run used for half an hour is an engine fault, and the exit code says so."""
    pending = asks.pending()
    for k in pending:
        mins = int((now - ((k.answered or k.t) if k.answer else k.t)) // 60)
        out(f"{k.bead:<22} {k.status.value:<9} {'answered' if k.answer else 'asked'} {mins} min")
    faults = sweeps.unused_answers(asks, now)
    for k in faults:
        out(sweeps.fault_line(k, now))
    lost = sweeps.orphan_lines(asks)
    for line in lost:
        out(line)
    if not pending and not lost:
        out("no ask waits")
    return 1 if faults else 0


def show(asks: AskStore, key: BeadId | None, out: Out) -> int:
    """One ask by its id (or its bead's id), the Ask v3 fields; reads only."""
    ask = (asks.get(key) or next((x for x in asks.all() if x.id == key), None)) if key else None
    if ask is None:
        out(f"tl: no ask {key or '(none given)'}")
        return 1
    out(f"ask {ask.id} (bead {ask.bead}, {ask.kind}, {ask.status})")
    out(f"question: {ask.decision}")
    out(f"owner cause: {ask.owner_cause} (set by {ask.cause_by})")
    out(f"blocking: {'yes' if ask.blocking else 'no'}")
    out(f"default: {ask.default or '-'}")
    out("similar: " + (", ".join(f"{s.kind} {s.id}" for s in ask.similar) or "-"))
    out("thread: " + ("" if ask.thread else "-"))
    for t in ask.thread:
        out(f"  [{t.by}] {t.md}")
    out("artifacts: " + (", ".join(ask.artifacts) or "-"))
    out(f"outcome: {ask.outcome.value if ask.outcome else '-'}" + (f" ({ask.outcome_ref})" if ask.outcome_ref else ""))
    return 0


def run(a: Arguments, asks: AskStore, store_at: Callable[[str], Beads], now: Callable[[], float], by: str, cfg: ConfigDir,
        out: Out = print) -> int:
    """One verb. `store_at(repo)` is the tracker of the ask's repo ('' = here)."""
    op = a.op
    if op == "list":
        listing(asks.pending(), out, a.json, sweeps.orphan_lines(asks))
        return 0
    if op == "age":
        return age(asks, now(), out)
    bead: BeadId | None = a.bead
    if op == "show":
        return show(asks, bead, out)
    if not bead:
        out(f"tl: {op} needs a bead id")
        return 2
    ask = asks.get(bead)
    verbs = intake.Intake(asks, store_at(ask.repo if ask else ""), now, by, look_rows=LookRows(cfg))
    try:
        return verb(a, op, bead, ask, verbs, out, cfg, now)
    except (BdFailure, ValueError) as e:
        out("tl: %s" % ((e.error.text if isinstance(e, BdFailure) else "") or e))
        return 1


def waive(a: Arguments, verbs: intake.Intake, bead: BeadId, words: str) -> None:
    for kind in intake.WAIVER_KINDS:
        if getattr(a, kind, None):
            verbs.waive(bead, kind, getattr(a, kind), a.approval or "")
            return
    verbs.override(bead, words)


def verb(a: Arguments, op: str, bead: BeadId, ask: Ask | None, verbs: intake.Intake, out: Out, cfg: ConfigDir,
         now: Callable[[], float] = time.time) -> int:
    words = " ".join(a.text or [])
    if op == "answer":
        action, said = action_of(a, ask)
        _done, why = verbs.answer(bead, action, said, amend=a.amend, expect=a.expect or "")
        out(NEXT % bead if not why else "tl: " + SAYS.get(why, why))
        return 0 if not why else 1
    if op == "withdraw":
        _done, why = verbs.withdraw(bead, words or "withdrawn with tl ask withdraw")
        out("done" if not why else "tl: " + SAYS.get(why, why))
        return 0 if not why else 1
    if op in ("park", "note"):
        owner = requests.OwnerVerbs(verbs, cfg, now(), ask.repo if ask else str(Path.cwd()))
        run = requests.newest_run(cfg, bead)
        why, said = owner.park(bead, run) if op == "park" else owner.note(bead, run, words)
        out(said if not why else "tl: " + why)
        return 0 if not why else 1
    if op == "hint":
        verbs.hint(bead, words)
    elif op == "hold":
        until = intake.parse_until(a.until, now()) if a.until else 0.0
        verbs.hold(bead, on=not a.release, until=until)
    elif op == "override":
        waive(a, verbs, bead, words)
    else:
        out(f"tl: no such verb {op}")
        return 2
    out("done")
    return 0
