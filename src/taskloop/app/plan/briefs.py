"""The task as workers read it: the bead's own text and the people's comments, never the engine's own records (plans, reviews, reflects
pile up on every rerun: 40 of one consumer run's 45 KB brief). Inline, never a path: a worker's file tools reach only its worktree, and the
engine's files live outside it so the worker cannot change them."""
import hashlib

from tlkernel import planbrief as bf
from tlkernel.bdsafe import peek
from tlkernel.bead import Bead
from tlkernel.ids import BeadId
from tlkernel.stagefacts import RunFacts

from taskloop.adapters.bdids import mentioned_ids
from taskloop.app.asks import intake
from taskloop.app.plan.amend import AmendState
from taskloop.app.plan.host import PlanHand, PlanPorts
from taskloop.app.plan.state import PlanState
from taskloop.domain.asks import text as asktext

ENGINE_LABELS = ("needs-owner-check",)


class Briefs:
    def __init__(self, facts: RunFacts, ports: PlanPorts, plan_state: PlanState, amend: AmendState,
                 hand: PlanHand) -> None:
        self.facts, self.ports, self.plan_state, self.amend, self.hand = facts, ports, plan_state, amend, hand
        self.parts: dict[str, int] = {}  # bytes per section of the last brief written: what the accounting code reads

    def text(self) -> str:
        return (self.facts.run_dir / "brief.md").read_text(encoding="utf-8")

    def fit(self, bead: Bead, comments: list, hint: str, other: int) -> bf.Brief:
        """The brief with the oldest comments left out until it fits cfg.brief_kb: the bead's text, the hint, the linked beads and the
        owner's answer (`other` bytes) are never cut. The limit stays; it is not raised."""
        base = bf.render(bead, [], self.facts.cfg.owner_author, hint)
        room = int(float(self.facts.cfg.brief_kb) * 1024) - len(base.text.encode()) - other
        return bf.render(bead, comments, self.facts.cfg.owner_author, hint, room=max(room, 0))

    def export(self) -> None:
        """Write the brief to the run dir and to the copy a resumed writer re-reads; refresh the hash that tells a rerun the owner changed
        something, and the snapshot a later amend diffs against."""
        bead = peek(self.ports.store, self.facts.bead) or Bead(id=self.facts.bead, title="", status="")
        comments = self.ports.store.comments(self.facts.bead)
        hint = str(bead.metadata.get(intake.HINT) or "")
        linked = bf.linked(self.facts.bead, bead, comments, self.facts.cfg.owner_author,
                           lambda i: peek(self.ports.store, BeadId(i)), lambda i: self.ports.store.comments(BeadId(i)), mentioned_ids)
        # the owner's typed answer is no comment: the brief carries it for the workers
        said = asktext.words(self.hand.answered.answer if self.hand.answered else None)
        answer = f"\n## Owner answer (to ask {self.hand.answered.id})\n{said}\n" if said and self.hand.answered else ""
        brief = self.fit(bead, comments, hint, len(linked.encode()) + len(answer.encode())).plus("linked", linked).plus("answer", answer)
        self.hand.snap = bf.snapshot(bead, comments, self.facts.cfg.owner_author)
        (self.facts.run_dir / "brief.md").write_text(brief.text, encoding="utf-8")
        self.facts.brief_file.write_text(brief.text, encoding="utf-8")  # a resumed writer is told where to re-read it (tl-bxk.10.29)
        # the hash is what tells a rerun the owner changed something: the engine's own close line and labels are not that
        ours = [x for x in (self.facts.cfg.pick_label, self.facts.cfg.needs_info_label) if x]
        plain = bf.render(bead, comments, self.facts.cfg.owner_author, hint, owner_only=True, engine_labels=(*ENGINE_LABELS, *ours))
        self.hand.brief_hash = hashlib.sha1(plain.text.encode("utf-8")).hexdigest()
        self.parts = brief.sizes()
        if brief.dropped:
            self.ports.log.note(f"brief: {brief.dropped} oldest comments left out to fit {self.facts.cfg.brief_kb} KB "
                                "(all stay in bd comments)")
        kb = len(brief.text.encode("utf-8")) / 1024
        if kb > float(self.facts.cfg.brief_kb):
            self.ports.warn(f"the brief is {kb:.0f} KB (over {self.facts.cfg.brief_kb} KB) with the comments cut to the newest: "
                            "the bead's own text is "
                   f"{len(self.fit(bead, [], hint, 0).text.encode('utf-8')) / 1024:.0f} KB, too big for one task")
