"""`MemoryBeads`: the bd `tl selftest` runs on (none installed, none touched), in memory, with the behaviour the code relies on
(claim only an open bead, closed beads leave `find`, labels
sorted and unique, metadata values are strings, a write to an unknown bead is refused)."""
from typing import Any

from taskloop.contracts.bead import BdError, Bead, Comment, Dep
from taskloop.contracts.ids import BeadId, parse_bead_id
from taskloop.contracts.ports import BdFailure, BeadPatch, BeadQuery, DoltPush, NewBead


class MemoryBeads:
    def __init__(self, actor: str = "fake", prefix: str = "fk") -> None:
        self.actor, self.prefix = actor, prefix
        self.beads: dict[BeadId, Bead] = {}
        self.notes: dict[str, list[Comment]] = {}
        self.refuse_create: list[BdError] = []  # the next creates fail with these, in order

    def _get(self, bead: BeadId) -> Bead:
        if bead not in self.beads:
            raise BdFailure(BdError(kind="not_found", text=f"Issue {bead} not found"))
        return self.beads[bead]

    def _put(self, b: Bead, **changes: Any) -> None:
        self.beads[b.id] = b.replace(**changes)

    def show(self, bead: BeadId) -> Bead | None:
        return self.beads.get(bead)

    def comments(self, bead: BeadId) -> list[Comment]:
        return list(self.notes.get(bead, []))

    def find(self, query: BeadQuery) -> list[Bead]:
        return [b for b in self.beads.values()
                if (b.status != "closed" or query.include_closed or query.status == "closed")
                and (not query.status or b.status == query.status) and (not query.label or query.label in b.labels)]

    def ready(self, label: str = "") -> list[Bead]:
        def open_dep(b: Bead) -> bool:
            return any(d.id in self.beads and self.beads[d.id].status != "closed" for d in b.dependencies if d.type in ("", "blocks"))
        return [b for b in self.beads.values() if b.status == "open" and not open_dep(b) and (not label or label in b.labels)]

    def create(self, new: NewBead) -> BeadId:
        if self.refuse_create:
            raise BdFailure(self.refuse_create.pop(0))
        bead = parse_bead_id(f"{self.prefix}-{len(self.beads) + 1}")
        self.beads[bead] = Bead(id=bead, title=new.title, status="open", issue_type=new.issue_type, priority=new.priority,
                                labels=sorted(set(new.labels)), parent=new.parent, description=new.description,
                                acceptance_criteria=new.acceptance_criteria, dependencies=[Dep(id=d) for d in new.deps])
        return bead

    def update(self, bead: BeadId, patch: BeadPatch) -> None:
        b = self._get(bead)
        if patch.if_assignee and b.assignee != patch.if_assignee:
            raise BdFailure(BdError(kind="other", text="assignee changed"))
        meta = dict(patch.metadata if patch.metadata is not None else b.metadata)
        meta = {k: v for k, v in meta.items() if k not in patch.unset_metadata}
        meta.update(patch.set_metadata)
        self._put(b, status=patch.status or b.status, assignee=b.assignee if patch.assignee is None else patch.assignee,
                  description=b.description if patch.description is None else patch.description,
                  notes=b.notes if patch.notes is None else patch.notes, metadata=meta)

    def claim(self, bead: BeadId) -> bool:
        b = self.beads.get(bead)
        if b is None or b.status != "open":
            return False
        self._put(b, status="in_progress", assignee=self.actor)
        return True

    def unclaim(self, bead: BeadId, force: bool = False) -> bool:
        b = self.beads.get(bead)
        if b is None or b.status != "in_progress" or (b.assignee != self.actor and not force):
            return False
        self._put(b, status="open", assignee="")
        return True

    def heartbeat(self, bead: BeadId) -> None:
        self._get(bead)

    def close(self, bead: BeadId, reason: str, if_assignee: str = "") -> None:
        b = self._get(bead)
        if if_assignee and b.assignee != if_assignee:
            raise BdFailure(BdError(kind="other", text="assignee changed"))
        self._put(b, status="closed", close_reason=reason)

    def add_comment(self, bead: BeadId, text: str) -> None:
        self._get(bead)
        self.notes.setdefault(bead, []).append(Comment(author=self.actor, text=text))

    def add_label(self, bead: BeadId, label: str, if_assignee: str = "") -> None:
        b = self._get(bead)
        if if_assignee and b.assignee != if_assignee:
            raise BdFailure(BdError(kind="other", text="assignee changed"))
        self._put(b, labels=sorted({*b.labels, label}))

    def remove_label(self, bead: BeadId, label: str) -> None:
        b = self._get(bead)
        self._put(b, labels=[x for x in b.labels if x != label])

    def provenance(self, bead: BeadId, kind: str, source: str, ref: str = "", ref_kind: str = "", at: str = "", payload: str = "") -> None:
        self._get(bead)

    def dolt_push(self) -> DoltPush:
        return DoltPush(0, "")

    def at(self, cwd: str) -> MemoryBeads:
        return self
