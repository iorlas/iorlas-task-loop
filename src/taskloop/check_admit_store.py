"""Latest checks facts read on the admission's borrowed connection."""

import sqlite3

from pydantic import BaseModel, ConfigDict

from taskloop.attempt_reads import as_int
from taskloop.attempt_types import AttemptKey
from taskloop.factory_schema import LANDED, LANDING

LATEST = f"""SELECT number,phase,conclusion,released_at IS NOT NULL,abandoned,{LANDED},{LANDING} FROM checks_attempt c
WHERE after_attempt_id=? ORDER BY number DESC LIMIT 1"""


class LatestChecks(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    number: int
    failed_released: bool
    abandoned: bool
    landed: bool
    landing: bool


def latest(con: sqlite3.Connection, previous: AttemptKey) -> LatestChecks | None:
    """Read the highest checks number and task-wide land facts without opening or committing a connection."""
    row: tuple[object, ...] | None = con.execute(LATEST, (previous.attempt_id,)).fetchone()
    if row is None:
        return None
    number, phase, conclusion, released, abandoned, landed, landing = row
    return LatestChecks(
        number=as_int(number),
        failed_released=phase == "concluded" and conclusion == "failed" and bool(released),
        abandoned=bool(abandoned),
        landed=bool(landed),
        landing=bool(landing),
    )
