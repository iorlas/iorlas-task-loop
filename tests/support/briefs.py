"""The brief functions the way the tests call them (the engine no longer has them: domain/plan/brief.py and app/plan/briefs.py)."""
from collections.abc import Sequence
from typing import Any

from taskloop.adapters.bdids import mentioned_ids
from taskloop.app.asks import intake
from taskloop.app.plan.briefs import ENGINE_LABELS
from taskloop.domain.plan import brief as bf
from tlkernel.bead import Bead, Comment
from tlkernel.checkpoint import BriefSnap


def brief_digest(bead: Bead, comments: Sequence[Comment], owner_only: bool = False, ignore: Sequence[str] = ()) -> str:
    hint = str(bead.metadata.get(intake.HINT) or "")
    return bf.render(bead, comments, "denis", hint, owner_only, (*ENGINE_LABELS, *ignore)).text


def linked_text(bead_id: str, bead: Bead, comments: Sequence[Comment], show: Any, comments_of: Any, cap: int = 10, each: int = 400) -> str:
    return bf.linked(bead_id, bead, comments, "denis", show, comments_of, mentioned_ids, cap, each)


def bead_snapshot(bead: Bead, comments: Sequence[Comment]) -> BriefSnap:
    return bf.snapshot(bead, comments, "denis")


bead_diff = bf.diff
