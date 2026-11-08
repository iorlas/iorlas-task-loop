"""Persist flake scores and file repair work without changing gate results."""
from collections.abc import Callable

from tlkernel.beadsport import Beads, NewBead
from tlkernel.flakes import FlakeLog, FlakeRow
from tlkernel.ids import BeadId
from tlkernel.storeapi import Doc

from tlland.domain.flake_escalate import Escalation, escalate, record


class FlakeBook:
    def __init__(self, doc: Doc[FlakeLog], beads: Beads, clock: Callable[[], float]) -> None:
        self.doc = doc
        self.beads = beads
        self.clock = clock

    def record(self, row: FlakeRow) -> Escalation | None:
        now = self.clock()
        log = self.doc.need() or FlakeLog()
        rows = [r for r in [*log.rows, row] if r.t >= now - 30 * 86400]
        self.doc.write(FlakeLog(rows=rows))
        filed: dict[str, str] = {}
        for r in rows:
            if r.bead:
                bead = self.beads.show(BeadId(r.bead))
                if bead is not None and bead.status != "closed":
                    filed[r.test] = r.bead
        escalation = escalate(rows, filed, row.test, now)
        if escalation is None:
            return None
        bead_id = self.beads.create(NewBead(
            title=f"Fix flaky test {row.test}",
            description=f"{escalation.count} flake rows in the past week for {row.test}. The test stays in the gate.",
            labels=["auto"],
        ))
        newest = max((i for i, r in enumerate(rows) if r.test == row.test), key=lambda i: (rows[i].t, i))
        rows[newest] = record(rows[newest], str(bead_id))
        self.doc.write(FlakeLog(rows=rows))
        return escalation
