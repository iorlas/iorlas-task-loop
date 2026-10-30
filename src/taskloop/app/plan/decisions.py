"""Decisions in force: the repo's ADRs as the plan stage reads them, and the record of the plans that relied on one. The store is
`taskloop.contracts.adrs.AdrStore` (under the task-loop state dir, written by `tl` and the dashboard's stick port)."""
import time
from typing import Any

from taskloop.contracts.adrs import AdrStore
from taskloop.contracts.plancheck import PlanData

SHOWN = 20  # the newest ADRs a plan prompt carries
TEXT_CAP = 600


class Decisions:
    def __init__(self, host: Any) -> None:
        self.e = host

    def store(self) -> AdrStore:
        return self.e.stores.adrs(self.e.ask_flow.repo())

    def text(self) -> str:
        """The prompt block: each ADR by id and text, and the instruction to name the ids relied on. '' when the repo has none."""
        found = self.store().in_force()[-SHOWN:]
        if not found:
            return ""
        rows = "".join(f"{a.id}: {' '.join(a.text.split())[:TEXT_CAP]}\n" for a in found)
        return ("Decisions in force for this repo: rulings the owner made on earlier questions. Follow them, never ask what they settle, "
                "and name the id of each one your plan relied on in `cited`:\n<decisions>\n" + rows + "</decisions>")

    def cited(self, data: PlanData) -> list[str]:
        """Count the plan's citations: one use per ADR it names that exists (an id the store does not know is dropped and said).
        -> the ids counted. Nothing is written on a dry run."""
        e = self.e
        ids = list(dict.fromkeys(i.strip() for i in data.get("cited") or []))
        if not ids or e.dry:
            return []
        adrs = self.store()
        live = {a.id for a in adrs.in_force()}
        known = [i for i in ids if i in live]
        for i in known:
            adrs.use(i, e.bead, e.log_path.stem, time.time())
        if len(known) < len(ids):
            e.log.note("the plan cites decisions that do not exist: " + ", ".join(i for i in ids if i not in known))
        return known
