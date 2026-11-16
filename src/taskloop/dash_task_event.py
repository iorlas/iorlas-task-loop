"""Historical hold snapshots indexed by their deciding attempt, never by current card text."""

from taskloop.dash_model import TaskEventDetail, iso
from taskloop.hold_store import HoldRow


def contexts(holds: dict[str, HoldRow]) -> dict[str, TaskEventDetail]:
    """Keep the causal checks identity distinct from its held implement attempt."""
    return {row.cause_id: TaskEventDetail(event=row.event, held_at=iso(row.held_at) or "") for row in holds.values()}
