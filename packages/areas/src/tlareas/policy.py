"""Area membership, ancestor lookup and running-bead exclusion policy."""
from collections.abc import Callable, Mapping, Sequence
from typing import Protocol

from tlkernel.bead import Bead
from tlkernel.beadsport import BdFailure, Beads
from tlkernel.ids import BeadId, is_bead_id
from tlkernel.loop import Skip

ANY_AREA = "*"  # An unreadable running bead makes every area busy.


class AreaConfig(Protocol):
    @property
    def areas(self) -> Mapping[str, object]: ...

    @property
    def area_label_prefix(self) -> str: ...


def has_areas(cfg: AreaConfig) -> bool:
    return bool(cfg.areas or cfg.area_label_prefix)


def area_skip(area: str, holder: str, where: str) -> Skip:
    return Skip(why=f"area {area} busy: {holder} in {where}", kind="area", area=area, holder=holder, where=where)


class Areas:
    def __init__(self, store: Beads, areas: Mapping[str, Sequence[str] | None], area_label_prefix: str,
                 running: dict[BeadId, str], say: Callable[[str], None] = print) -> None:
        self.store, self.configured, self.prefix = store, areas, area_label_prefix
        self.running, self.say = running, say
        self.parents: dict[BeadId, BeadId | None] = {}

    def parent_of(self, bead_id: BeadId) -> BeadId | None:
        if bead_id not in self.parents:
            try:
                found = self.store.show(bead_id)
            except BdFailure:
                found = None
            self.parents[bead_id] = found.parent if found and is_bead_id(found.parent) else None
        return self.parents[bead_id]

    def epics_of(self, b: Bead) -> list[BeadId]:
        """Every ancestor of a bead, nearest first; `parent` in bd's JSON is the direct one only."""
        out: list[BeadId] = []
        pid = b.parent if is_bead_id(b.parent) else None
        while pid and pid not in out:
            out.append(pid)
            pid = self.parent_of(pid)
        return out

    def area_of(self, b: Bead) -> str:
        """The bead's area, "" for none. engine.areas {area: [epic id or label, ...]} first, in its order: the bead, any of its
        ancestors or one of its labels named; then the first label with engine.area_label_prefix (lane:live is area live)."""
        ups: list[str] | None = None
        for name, members in self.configured.items():
            if ups is None:
                ups = [b.id, *self.epics_of(b)]
            if any(m in ups or m in b.labels for m in members or []):
                return name
        prefix = self.prefix
        if prefix:
            for x in b.labels:
                if x.startswith(prefix) and len(x) > len(prefix):
                    return x[len(prefix):]
        return ""

    def busy_areas(self, but: str = "") -> dict[str, tuple[str, str]]:
        """{area: (bead, where)} of the areas a running bead (other than `but`) works in."""
        out: dict[str, tuple[str, str]] = {}
        for bid, where in sorted(self.running.items()):
            if bid == but or not is_bead_id(bid):
                continue
            try:
                held = self.store.show(bid)
            except BdFailure:
                held = None
            if held is None:  # its area is unknown: it may be any, so every area waits
                self.say(f"running bead {bid} in {where} is unreadable (bd show failed): every area counts as busy")
                out.setdefault(ANY_AREA, (bid, where))
                continue
            area = self.area_of(held)
            if area:
                out.setdefault(area, (bid, where))
        return out

    def area_busy(self, b: Bead, busy_areas: Callable[[str], dict[str, tuple[str, str]]] | None = None) -> tuple[str, Skip | None]:
        """(area, the skip) of a bead whose area runs elsewhere; (area, None) when it is free; ("", None) for no area."""
        area = self.area_of(b)
        if not area:
            return "", None
        busy = (busy_areas or self.busy_areas)(b.id)
        hit = busy.get(area) or busy.get(ANY_AREA)
        return area, area_skip(area, *hit) if hit else None

    def drop_busy[T](self, keep: list[T], bead_of: Callable[[T], Bead],
                     busy: dict[str, tuple[str, str]]) -> tuple[list[T], list[tuple[BeadId, Skip]]]:
        """Filter candidates without reserving areas among this queue's own candidates."""
        free: list[T] = []
        skipped: list[tuple[BeadId, Skip]] = []
        for item in keep:
            bead = bead_of(item)
            area = self.area_of(bead)
            hit = busy.get(area) or (busy.get(ANY_AREA) if area else None)
            if hit:
                skipped.append((bead.id, area_skip(area, *hit)))
            else:
                free.append(item)
        return free, skipped


def area_busy_text(areas: Areas, bead: Bead) -> tuple[str, str]:
    """Return the area and the existing busy explanation, or an empty explanation."""
    area, skip = areas.area_busy(bead)
    return area, skip.why if skip else ""
