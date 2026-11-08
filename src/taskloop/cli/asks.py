"""Argument wiring for the owner's ask operations."""
from argparse import Namespace
from collections.abc import Callable
from typing import Any

from tlasks import ask_verbs
from tlasks.contracts.records import Arguments
from tlkernel.askstore import AskStore
from tlkernel.beadsport import Beads
from tlkernel.paths import ConfigDir


def arguments(a: Namespace) -> Arguments:
    return Arguments(
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
    """`tl ask ...` and the owner's verbs, on tl's subparsers (the parsers are the asks node's)."""
    ask_verbs.add_parsers(sp)
