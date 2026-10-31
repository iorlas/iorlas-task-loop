"""`tl queue [add|remove ID...]`: the owner's queue as a `queue` label on beads (contracts/pickset.py), set and cleared through bd."""
from argparse import ArgumentParser, _SubParsersAction
from collections.abc import Callable

from taskloop.contracts import pickset
from taskloop.contracts.ids import parse_bead_id
from taskloop.contracts.ports import BdFailure, BeadPatch, BeadQuery, Beads


def cmd_queue(op: str, ids: list[str], store: Beads, now: Callable[[], float], out: Callable[[str], None] = print) -> int:
    if op in ("add", "remove") and not ids:
        out(f"tl: queue {op}: name at least one bead")
        return 2
    try:
        if op == "add":
            t = int(now() * 1000)
            for n, raw in enumerate(ids):
                bid = parse_bead_id(raw)
                if store.show(bid) is None:
                    out(f"tl: no such bead {raw}")
                    return 1
                store.add_label(bid, pickset.LABEL)
                store.update(bid, BeadPatch(set_metadata={pickset.AT: str(t + n)}))
        elif op == "remove":
            for raw in ids:
                bid = parse_bead_id(raw)
                store.remove_label(bid, pickset.LABEL)
                store.update(bid, BeadPatch(unset_metadata=[pickset.AT]))
        beads = store.find(BeadQuery(label=pickset.LABEL))
    except (BdFailure, ValueError) as e:
        out(f"tl: {e}")
        return 1
    chosen = pickset.members(beads)
    by_id = {b.id: b for b in beads}
    if not chosen:
        out("queue empty: the loop takes any ready bead")
    for n, i in enumerate(chosen, 1):
        out(f"{n}. {i}  {by_id[i].status}  {by_id[i].title[:70]}")
    return 0


def add_parsers(sp: _SubParsersAction[ArgumentParser]) -> None:
    p = sp.add_parser("queue", help="the owner's queue: while any bead is queued the loop takes only queued beads, in order")
    p.add_argument("op", nargs="?", choices=["list", "add", "remove"], default="list")
    p.add_argument("ids", nargs="*")
    for verb in ("next", "loop"):  # the same set for one run, no labels touched (the parsers loop_parsers made)
        sp.choices[verb].add_argument("--only", nargs="+", default=[], metavar="ID", help="take just these beads, in this order")
