"""The task as workers read it: the bead's own text and the people's comments, never the engine's own records (plans, reviews, reflects
pile up on every rerun: 40 of lifesim-vbo's 45 KB brief). Inline, never a path: a worker's file tools reach only its worktree, and the
engine's files live outside it so the worker cannot change them."""
import hashlib
from typing import Any

from taskloop.adapters.bdsafe import peek
from taskloop.app.asks import intake
from taskloop.contracts.bead import Bead
from taskloop.domain.plan import brief as bf

ENGINE_LABELS = ("needs-owner-check",)


class Briefs:
    def __init__(self, host: Any) -> None:
        self.e = host
        self.parts: dict[str, int] = {}  # bytes per section of the last brief written: what the accounting code reads

    def text(self) -> str:
        return (self.e.run_dir / "brief.md").read_text(encoding="utf-8")

    def export(self) -> None:
        """Write the brief to the run dir and to the copy a resumed writer re-reads; refresh the hash that tells a rerun the owner changed
        something, and the snapshot a later amend diffs against."""
        e = self.e
        bead = peek(e.store, e.bead) or Bead(id=e.bead, title="", status="")
        comments = e.store.comments(e.bead)
        hint = str(bead.metadata.get(intake.HINT) or "")
        brief = bf.render(bead, comments, intake.engine_written, hint).plus(
            "linked", bf.linked(e.bead, bead, comments, intake.engine_written, lambda i: peek(e.store, i), e.store.comments))
        said = e.planner.cap.answered_words()  # the owner's typed answer is no comment: the brief carries it for the workers
        if said and e.answered:
            brief = brief.plus("answer", f"\n## Owner answer (to ask {e.answered.id})\n{said}\n")
        e.snap = bf.snapshot(bead, comments, intake.engine_written)
        (e.run_dir / "brief.md").write_text(brief.text, encoding="utf-8")
        e.brief_file.write_text(brief.text, encoding="utf-8")  # a resumed writer is told where to re-read it (tl-bxk.10.29)
        # the hash is what tells a rerun the owner changed something: the engine's own close line and labels are not that
        ours = [x for x in (e.cfg.pick_label, e.cfg.needs_info_label) if x]
        plain = bf.render(bead, comments, intake.engine_written, hint, owner_only=True, engine_labels=(*ENGINE_LABELS, *ours))
        e.brief_hash = hashlib.sha1(plain.text.encode("utf-8")).hexdigest()
        self.parts = brief.sizes()
        kb = len(brief.text.encode("utf-8")) / 1024
        if kb > float(e.cfg.brief_kb):
            e.warn(f"the brief is {kb:.0f} KB (over {e.cfg.brief_kb} KB): the bead may be too big for one task")
