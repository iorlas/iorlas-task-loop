"""The ask ledger as bead comments: the authority. A row the owner's verbs cause is written first as a comment on the ask's bead
(`tl-ledger <json>`), then to the `ask_ledger` table, which is a cache: after a loss of the table `rebuild` reads the comments back and
puts in the rows the table lacks. An ask the engine alone moves (raise, close, park) is operational and stays in the table."""
import json
from collections.abc import Iterable

from taskloop.contracts import wire
from taskloop.contracts.askstore import AskStore
from taskloop.contracts.ids import BeadId
from taskloop.contracts.ledger import LedgerEntry
from taskloop.contracts.ports import BdFailure, Beads

PREFIX = "tl-ledger "


def line(entry: LedgerEntry) -> str:
    return PREFIX + json.dumps(wire.dump(entry), ensure_ascii=False, sort_keys=True)


def parse(text: str) -> LedgerEntry | None:
    """The row a comment holds; None for any other comment or one this tl cannot read."""
    if not text.startswith(PREFIX):
        return None
    try:
        return wire.load(LedgerEntry, json.loads(text[len(PREFIX):]))
    except ValueError:
        return None


def record(beads: Beads):
    """The `before` hook of an AskStore: the comment on the entry's bead. A failure propagates (no comment, no row); a bead that does
    not exist has nowhere to carry it and the row goes to the table alone."""
    def write(entry: LedgerEntry) -> None:
        try:
            beads.add_comment(entry.bead, line(entry))
        except BdFailure as err:
            if err.error.kind != "not_found":
                raise
    return write


def rebuild(asks: AskStore, beads: Beads, ids: Iterable[BeadId]) -> int:
    """Put into the ledger every row the comments of `ids` hold and the table lacks, oldest first. -> how many."""
    if asks.ledger is None:
        return 0
    have = {json.dumps(wire.dump(e), ensure_ascii=False, sort_keys=True) for e in asks.rows()}
    found = [e for bead in ids for c in beads.comments(bead) if (e := parse(c.text)) is not None]
    added = 0
    for entry in sorted(found, key=lambda e: e.t):
        if json.dumps(wire.dump(entry), ensure_ascii=False, sort_keys=True) not in have:
            asks.ledger.append(entry)
            added += 1
    return added
