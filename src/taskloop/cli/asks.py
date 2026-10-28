"""`tl ask list|answer|withdraw|age` and the owner's typed verbs `tl answer|hint|hold|override`: the argument handling over app/asks. Every
write is a typed record (an AskAnswer, or a metadata key on the bead); nothing here reads or writes prose that something later parses."""
import json
from argparse import Namespace
from collections.abc import Callable
from typing import Any, Final

from taskloop.app.asks import intake, sweeps
from taskloop.contracts import codec
from taskloop.contracts.ask import Ask, AskAction
from taskloop.contracts.ports import BdFailure, Beads
from taskloop.contracts.stores import AskStore

Out = Callable[[str], None]
SAYS: Final = {"gone": "there is no ask for this bead", "superseded": "the engine asked again; the new ask replaces this one",
        "withdrawn": "the ask was withdrawn", "closed": "the ask is closed", "consumed": "a run already used the answer",
        "answered": "this ask is already answered (replace the answer with --amend)"}
NEXT: Final = "The bead %s runs again from your answer on the next pass of its loop."


def action_of(a: Namespace, ask: Ask | None) -> tuple[AskAction, str]:
    """(the typed action, its text): --option N picks one of the ask's own options; a flag names a bare action; words are `text`."""
    words = " ".join(getattr(a, "text", None) or [])
    pick = getattr(a, "option", None)
    if pick is not None and ask is not None and 1 <= pick <= len(ask.options):
        o = ask.options[pick - 1]
        return o.action, " ".join(x for x in (o.text, words) if x)
    for flag, action in (("rerun", "rerun"), ("confirm", "confirm"), ("split", "split")):
        if getattr(a, flag, False):
            return action, words  # type: ignore[return-value]
    return "text", words


def listing(asks: list[Ask], out: Out, as_json: bool, orphans: list[str]) -> None:
    if as_json:
        out(json.dumps([codec.to_json(x) for x in asks], indent=1))
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


def run(a: Namespace, asks: AskStore, store_at: Callable[[str], Beads], now: Callable[[], float], by: str, out: Out = print) -> int:
    """One verb. `store_at(repo)` is the tracker of the ask's repo ('' = here)."""
    op = a.op
    if op == "list":
        listing(asks.pending(), out, bool(getattr(a, "json", False)), sweeps.orphan_lines(asks))
        return 0
    if op == "age":
        return age(asks, now(), out)
    bead = getattr(a, "bead", "")
    if not bead:
        out(f"tl: {op} needs a bead id")
        return 2
    ask = asks.get(bead)
    verbs = intake.Intake(asks, store_at(ask.repo if ask else ""), now, by)
    try:
        return verb(a, op, bead, ask, verbs, out)
    except (BdFailure, ValueError) as e:
        out("tl: %s" % ((getattr(e, "error", None) and e.error.text) or e))  # type: ignore[attr-defined]
        return 1


def verb(a: Namespace, op: str, bead: str, ask: Ask | None, verbs: intake.Intake, out: Out) -> int:
    words = " ".join(getattr(a, "text", None) or [])
    if op == "answer":
        action, said = action_of(a, ask)
        _done, why = verbs.answer(bead, action, said, amend=bool(getattr(a, "amend", False)))
        out(NEXT % bead if not why else "tl: " + SAYS.get(why, why))
        return 0 if not why else 1
    if op == "withdraw":
        _done, why = verbs.withdraw(bead, words or "withdrawn with tl ask withdraw")
        out("done" if not why else "tl: " + SAYS.get(why, why))
        return 0 if not why else 1
    if op == "hint":
        verbs.hint(bead, words)
    elif op == "hold":
        verbs.hold(bead, on=not getattr(a, "release", False))
    elif op == "override":
        verbs.override(bead, words)
    else:
        out(f"tl: no such verb {op}")
        return 2
    out("done")
    return 0


def add_parsers(sp: Any) -> None:
    """`tl ask ...` and the owner's verbs `tl answer|hint|hold|override`, on tl's subparsers."""
    p = sp.add_parser("ask", help="the owner's inbox: list the open asks, answer one, withdraw one that no longer applies, or their age")
    p.add_argument("op", choices=["list", "answer", "withdraw", "age"])
    p.add_argument("bead", nargs="?")
    p.add_argument("text", nargs="*", help="answer: the answer; withdraw: why")
    p.add_argument("--json", action="store_true")
    answer_flags(p)
    for verb, what in (("answer", "answer an ask (same as tl ask answer)"), ("hint", "give the bead a hint the next run reads"),
                       ("hold", "keep the loop off a bead (--release lets it go)"), ("override", "override a cap once: replan-cap")):
        p = sp.add_parser(verb, help=what)
        p.set_defaults(op=verb)
        p.add_argument("bead")
        p.add_argument("text", nargs="*")
        if verb == "answer":
            answer_flags(p)
        if verb == "hold":
            p.add_argument("--release", action="store_true")


def answer_flags(p: Any) -> None:
    p.add_argument("--amend", action="store_true", help="replace an answer no run has used yet")
    p.add_argument("--option", type=int, help="pick option N of the ask")
    p.add_argument("--rerun", action="store_true", help="run again, nothing else")
    p.add_argument("--confirm", action="store_true", help="yes, go on as it is")
    p.add_argument("--split", action="store_true", help="split the bead")
