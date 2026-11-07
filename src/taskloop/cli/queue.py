"""`tl queue [add|remove ID...]`: the owner's queue as a `queue` label on beads (contracts/pickset.py), set and cleared through bd."""
from argparse import ArgumentParser, _SubParsersAction
from collections.abc import Callable

from tlkernel.beadsport import Beads

from taskloop.app.loop.queue import owner_queue


def cmd_queue(op: str, ids: list[str], store: Beads, now: Callable[[], float], out: Callable[[str], None] = print) -> int:
    code, lines = owner_queue(op, ids, store, now)
    for line in lines:
        out(line)
    return code


def add_parsers(sp: _SubParsersAction[ArgumentParser]) -> None:
    p = sp.add_parser("queue", help="the owner's queue: while any bead is queued the loop takes only queued beads, in order")
    p.add_argument("op", nargs="?", choices=["list", "add", "remove"], default="list")
    p.add_argument("ids", nargs="*")
    for verb in ("next", "loop"):  # the same set for one run, no labels touched (the parsers loop_parsers made)
        sp.choices[verb].add_argument("--only", nargs="+", default=[], metavar="ID", help="take just these beads, in this order")
