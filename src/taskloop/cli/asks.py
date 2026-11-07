"""Argument wiring for the owner's ask operations."""
from argparse import Namespace
from collections.abc import Callable
from typing import Any

from tlkernel.askstore import AskStore
from tlkernel.beadsport import Beads
from tlkernel.ids import parse_bead_id
from tlkernel.paths import ConfigDir

from taskloop.app.asks import ask_verbs, intake


def arguments(a: Namespace) -> ask_verbs.Arguments:
    return ask_verbs.Arguments(
        op=a.op, bead=getattr(a, "bead", None), text=tuple(getattr(a, "text", None) or ()),
        json=getattr(a, "json", False), option=getattr(a, "option", None), verdict=getattr(a, "verdict", None),
        rerun=getattr(a, "rerun", False), confirm=getattr(a, "confirm", False), split=getattr(a, "split", False),
        amend=getattr(a, "amend", False), expect=getattr(a, "expect", None), waive=getattr(a, "waive", None),
        defer=getattr(a, "defer", None), drop=getattr(a, "drop", None), approval=getattr(a, "approval", None),
        until=getattr(a, "until", None), release=getattr(a, "release", False))


def run(a: Namespace, asks: AskStore, store_at: Callable[[str], Beads], now: Callable[[], float], by: str, cfg: ConfigDir,
        out: Callable[[str], None] = print) -> int:
    return ask_verbs.run(arguments(a), asks, store_at, now, by, cfg, out)


def add_parsers(sp: Any) -> None:
    """`tl ask ...` and the owner's verbs `tl answer|hint|hold|override|park|note`, on tl's subparsers."""
    p = sp.add_parser("ask", help="the owner's inbox: list the open asks, show one, answer one, withdraw one that no longer applies, "
                    "or their age")
    p.add_argument("op", choices=["list", "show", "answer", "withdraw", "age"])
    p.add_argument("bead", nargs="?", type=parse_bead_id)
    p.add_argument("text", nargs="*", help="answer: the answer; withdraw: why")
    p.add_argument("--json", action="store_true")
    answer_flags(p)
    for verb, what in (("answer", "answer an ask (same as tl ask answer)"), ("hint", "give the bead a hint the next run reads"),
                       ("hold", "keep the loop off a bead (--release lets it go)"), ("override", "override a cap once: replan-cap"),
                       ("park", "hold a bead and end its live run at the next step, branch kept (tl hold --release lets it go)"),
                       ("note", "a note the live run's next stage reads (no run going: a hint the next run reads)")):
        p = sp.add_parser(verb, help=what)
        p.set_defaults(op=verb)
        p.add_argument("bead", type=parse_bead_id)
        p.add_argument("text", nargs="*")
        if verb == "answer":
            answer_flags(p)
        if verb == "hold":
            p.add_argument("--release", action="store_true")
            p.add_argument("--until", metavar="T", help="no claim before T (+2h, 90m, HH:MM, ISO); default: until released")
        if verb == "override":
            for kind in intake.WAIVER_KINDS:
                p.add_argument("--" + kind, metavar="CRITERION", help=f"{kind} this acceptance criterion (needs --approval)")
            p.add_argument("--approval", metavar="QUOTE", help="the owner's own words approving it, quoted; an empty quote is refused")


def answer_flags(p: Any) -> None:
    p.add_argument("--amend", action="store_true", help="replace an answer no run has used yet")
    p.add_argument("--expect", metavar="ASK_ID", help="answer only this ask; refused when the engine has asked again since")
    p.add_argument("--option", type=int, help="pick option N of the ask")
    p.add_argument("--rerun", action="store_true", help="run again, nothing else")
    p.add_argument("--confirm", action="store_true", help="yes, go on as it is")
    p.add_argument("--split", action="store_true", help="split the bead")
    p.add_argument("--verdict", choices=["confirm", "work", "decline"], help="yes as it is / do the work / no")
