"""The brief functions the way the tests call them (the engine no longer has them: domain/plan/brief.py and app/plan/briefs.py)."""
from collections.abc import Sequence
from typing import Any

from taskloop.app.asks import intake
from taskloop.app.plan.briefs import ENGINE_LABELS
from taskloop.contracts.bead import Bead, Comment
from taskloop.contracts.checkpoint import BriefSnap
from taskloop.domain.plan import brief as bf


def brief_digest(bead: Bead, comments: Sequence[Comment], owner_only: bool = False, ignore: Sequence[str] = ()) -> str:
    hint = str(bead.metadata.get(intake.HINT) or "")
    return bf.render(bead, comments, intake.engine_written, hint, owner_only, (*ENGINE_LABELS, *ignore)).text


def linked_text(bead_id: str, bead: Bead, comments: Sequence[Comment], show: Any, comments_of: Any, cap: int = 10, each: int = 400) -> str:
    return bf.linked(bead_id, bead, comments, intake.engine_written, show, comments_of, cap, each)


def bead_snapshot(bead: Bead, comments: Sequence[Comment]) -> BriefSnap:
    return bf.snapshot(bead, comments, intake.engine_written)


bead_diff = bf.diff
