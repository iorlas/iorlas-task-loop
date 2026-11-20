"""The adopted slots as factory.db holds them and whether a reservation holds each; no Git, no write."""

from dataclasses import dataclass
from enum import StrEnum

from taskloop.attempt_reads import StoreConnection, as_nullable_text, as_text


class SlotHold(StrEnum):
    FREE = "free"
    HELD = "held"


@dataclass(frozen=True)
class SlotRow:
    name: str
    path: str
    repo_id: str
    state: SlotHold
    attempt_id: str | None  # the holding attempt, None while free


class SlotListStore(StoreConnection):
    def slots(self) -> tuple[SlotRow, ...]:
        with self._connection() as con:
            rows = con.execute("""SELECT s.name,s.path,s.repo_id,r.attempt_id FROM slot s
                LEFT JOIN reservation r ON r.repo_id=s.repo_id AND r.slot=s.name
                ORDER BY s.repo_id,length(s.name),s.name""").fetchall()
        return tuple(
            SlotRow(as_text(r[0]), as_text(r[1]), as_text(r[2]), SlotHold.FREE if r[3] is None else SlotHold.HELD, as_nullable_text(r[3]))
            for r in rows
        )
