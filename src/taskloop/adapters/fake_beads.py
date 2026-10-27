"""`FakeBeads`: bd in memory, with the behaviour the code relies on (claim only an open bead, closed beads leave `find`, labels
sorted and unique, metadata values are strings, a write to an unknown bead is refused)."""
import dataclasses

from taskloop.contracts.bead import BdError, Bead, Comment
from taskloop.contracts.ports import BdFailure, BeadPatch, BeadQuery, NewBead


class FakeBeads:
    def __init__(self, actor: str = "fake", prefix: str = "fk") -> None:
        self.actor, self.prefix = actor, prefix
        self.beads: dict[str, Bead] = {}
        self.notes: dict[str, list[Comment]] = {}
        self.refuse_create: list[BdError] = []  # the next creates fail with these, in order

    def _get(self, bead: str) -> Bead:
        if bead not in self.beads:
            raise BdFailure(BdError(kind="not_found", text="Issue %s not found" % bead))
        return self.beads[bead]

    def _put(self, b: Bead, **changes: object) -> None:
        self.beads[b.id] = dataclasses.replace(b, **changes)

    def show(self, bead: str) -> Bead | None:
        return self.beads.get(bead)

    def comments(self, bead: str) -> list[Comment]:
        return list(self.notes.get(bead, []))

    def find(self, query: BeadQuery) -> list[Bead]:
        return [b for b in self.beads.values()
                if (b.status != "closed" or query.include_closed or query.status == "closed")
                and (not query.status or b.status == query.status) and (not query.label or query.label in b.labels)]

    def ready(self) -> list[Bead]:
        def open_dep(b: Bead) -> bool:
            return any(d in self.beads and self.beads[d].status != "closed" for d in b.dependencies)
        return [b for b in self.beads.values() if b.status == "open" and not open_dep(b)]

    def create(self, new: NewBead) -> str:
        if self.refuse_create:
            raise BdFailure(self.refuse_create.pop(0))
        bead = "%s-%d" % (self.prefix, len(self.beads) + 1)
        self.beads[bead] = Bead(id=bead, title=new.title, status="open", issue_type=new.issue_type, priority=new.priority,
                                labels=sorted(set(new.labels)), parent=new.parent, description=new.description,
                                acceptance_criteria=new.acceptance_criteria, dependencies=list(new.deps))
        return bead

    def update(self, bead: str, patch: BeadPatch) -> None:
        b = self._get(bead)
        meta = b.metadata
        extra = {k: v for k, v in meta.extra.items() if k not in patch.unset_metadata}
        extra.update({k: v for k, v in patch.set_metadata.items() if k != "held_bead"})
        held = patch.set_metadata.get("held_bead", meta.held_bead)
        if "held_bead" in patch.unset_metadata:
            held = ""
        self._put(b, status=patch.status or b.status, assignee=b.assignee if patch.assignee is None else patch.assignee,
                  description=b.description if patch.description is None else patch.description,
                  metadata=dataclasses.replace(meta, held_bead=held, extra=extra))

    def claim(self, bead: str) -> bool:
        b = self.beads.get(bead)
        if b is None or b.status != "open":
            return False
        self._put(b, status="in_progress", assignee=self.actor)
        return True

    def unclaim(self, bead: str, force: bool = False) -> bool:
        b = self.beads.get(bead)
        if b is None or b.status != "in_progress" or (b.assignee != self.actor and not force):
            return False
        self._put(b, status="open", assignee="")
        return True

    def heartbeat(self, bead: str) -> None:
        self._get(bead)

    def close(self, bead: str, reason: str) -> None:
        self._put(self._get(bead), status="closed")

    def add_comment(self, bead: str, text: str) -> None:
        self._get(bead)
        self.notes.setdefault(bead, []).append(Comment(author=self.actor, text=text))

    def add_label(self, bead: str, label: str) -> None:
        b = self._get(bead)
        self._put(b, labels=sorted({*b.labels, label}))

    def remove_label(self, bead: str, label: str) -> None:
        b = self._get(bead)
        self._put(b, labels=[x for x in b.labels if x != label])
