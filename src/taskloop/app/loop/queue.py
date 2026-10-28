"""The queue rule: ready beads with the pick label, minus skip labels, epics, slots, beads that cite material no worktree holds
and beads whose area runs elsewhere; then priority, epic order, lowest id. Every skip says which rule skipped it as a typed
Skip; nothing is parsed back out of text."""
import itertools
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from taskloop.app.asks import intake
from taskloop.app.loop.env import LoopEnv
from taskloop.contracts.bead import Bead
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.loop import Skip
from taskloop.contracts.ports import BdFailure, Beads

Key = tuple[int, int, list[tuple[int, int | str]], Bead]  # (priority, epic rank, natural id, bead)
ANY_AREA = "*"  # busy_areas key for a running bead that could not be read: every area waits


def natural(bead_id: str) -> list[tuple[int, int | str]]:
    """fld.26.9 before fld.26.10: digit runs compare as numbers."""
    return [(0, int(g)) if d else (1, g) for d, g in ((k, "".join(v)) for k, v in itertools.groupby(bead_id, str.isdigit))]


def ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def has_areas(cfg: EngineConfig) -> bool:
    return bool(cfg.areas or cfg.area_label_prefix)


@dataclass(frozen=True)
class Ranked:
    bead: Bead
    reason: str


@dataclass(frozen=True)
class Skipped:
    bead: str
    skip: Skip


@dataclass
class Queue:
    ranked: list[Ranked] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)

    def areas(self) -> list[Skipped]:
        return [s for s in self.skipped if s.skip.kind == "area"]


def area_skip(area: str, holder: str, where: str) -> Skip:
    return Skip(why=f"area {area} busy: {holder} in {where}", kind="area", area=area, holder=holder, where=where)


class QueueRule:
    def __init__(self, store: Beads, cfg: EngineConfig, running: dict[str, str], lint: Callable[[Bead], str],
                 say: Callable[[str], None] = print, now: Callable[[], float] = time.time) -> None:
        self.store, self.cfg, self.running, self.lint, self.say, self.now = store, cfg, running, lint, say, now
        self.parents: dict[str, str | None] = {}

    def parent_of(self, bead_id: str) -> str | None:
        if bead_id not in self.parents:
            try:
                found = self.store.show(bead_id)
            except BdFailure:
                found = None
            self.parents[bead_id] = found.parent if found else None
        return self.parents[bead_id]

    def epics_of(self, b: Bead) -> list[str]:
        """Every ancestor of a bead, nearest first; `parent` in bd's JSON is the direct one only."""
        out: list[str] = []
        pid = b.parent
        while pid and pid not in out:
            out.append(pid)
            pid = self.parent_of(pid)
        return out

    def area_of(self, b: Bead) -> str:
        """The bead's area, "" for none. engine.areas {area: [epic id or label, ...]} first, in its order: the bead, any of its
        ancestors or one of its labels named; then the first label with engine.area_label_prefix (lane:live is area live)."""
        ups: list[str] | None = None
        for name, members in self.cfg.areas.items():
            if ups is None:
                ups = [b.id, *self.epics_of(b)]
            if any(m in ups or m in b.labels for m in members or []):
                return name
        prefix = self.cfg.area_label_prefix
        if prefix:
            for x in b.labels:
                if x.startswith(prefix) and len(x) > len(prefix):
                    return x[len(prefix):]
        return ""

    def busy_areas(self, but: str = "") -> dict[str, tuple[str, str]]:
        """{area: (bead, where)} of the areas a running bead (other than `but`) works in."""
        out: dict[str, tuple[str, str]] = {}
        for bid, where in sorted(self.running.items()):
            if bid == but:
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

    def area_busy(self, b: Bead) -> tuple[str, Skip | None]:
        """(area, the skip) of a bead whose area runs elsewhere; (area, None) when it is free; ("", None) for no area."""
        area = self.area_of(b)
        if not area:
            return "", None
        busy = self.busy_areas(but=b.id)
        hit = busy.get(area) or busy.get(ANY_AREA)
        return area, area_skip(area, *hit) if hit else None

    def why_not(self, b: Bead) -> Skip | None:
        skip_labels = self.cfg.skip_labels
        hit = next((x for x in skip_labels if x in b.labels), None)
        if b.issue_type == "epic":
            return Skip(why="an epic", kind="epic")
        if "slot" in b.labels:
            return Skip(why="a slot", kind="slot")
        if hit:
            return Skip(why="label " + hit, kind="label")
        who = intake.held(b.metadata, self.now())
        if who:
            until = float(b.metadata.get(intake.HOLD_UNTIL) or 0)
            return Skip(why=f"held by {who}", kind="hold", until=until or None)
        return None

    def rank(self, ready: list[Bead], repo: str) -> Queue:
        order = list(self.cfg.epic_order)
        keep: list[Key] = []
        q = Queue()
        for b in ready:
            skip = self.why_not(b)
            rank = len(order)
            if skip is None and order:
                ups = self.epics_of(b)
                rank = min([order.index(e) for e in ups if e in order] or [len(order)])
                if rank == len(order) and self.cfg.epic_only:
                    skip = Skip(why="under no epic in epic_order (epic_only)", kind="epic_only")
            if skip is None:
                text = self.lint(b)
                skip = Skip(why=text, kind="lint") if text else None
            if skip is not None:
                q.skipped.append(Skipped(b.id, skip))
            else:
                keep.append((b.priority if b.priority is not None else 2, rank, natural(b.id), b))
        keep.sort(key=lambda k: k[:3])
        if has_areas(self.cfg) and keep:
            keep = self.drop_busy(keep, q)
        q.ranked = [Ranked(k[3], self.reason(keep, i, order)) for i, k in enumerate(keep)]
        return q

    def drop_busy(self, keep: list[Key], q: Queue) -> list[Key]:
        busy = self.busy_areas()
        free: list[Key] = []
        for k in keep:
            area = self.area_of(k[3])
            hit = busy.get(area) or (busy.get(ANY_AREA) if area else None)
            if hit:
                q.skipped.append(Skipped(k[3].id, area_skip(area, *hit)))
            else:
                free.append(k)
        return free

    @staticmethod
    def reason(keep: list[Key], i: int, order: list[str]) -> str:
        k = keep[i]
        if i + 1 == len(keep):
            return "only candidate" if i == 0 else "last"
        nxt = keep[i + 1]
        if k[0] != nxt[0]:
            return f"priority P{k[0]} before P{nxt[0]}"
        if k[1] != nxt[1]:
            return f"epic {order[k[1]]} ({ordinal(k[1] + 1)} in epic_order)"
        return "lowest id"


def area_busy_text(rule: QueueRule, bead: Bead) -> tuple[str, str]:
    """(area, "area A busy: B in S") for a bead whose area runs elsewhere, (area, "") when it is free, ("", "") for no area."""
    area, skip = rule.area_busy(bead)
    return area, skip.why if skip else ""


def rank_ready(env: LoopEnv, cfg: EngineConfig, say: Callable[[str], None] = print) -> tuple[Queue, QueueRule]:
    """The queue as the loop would take it now."""
    try:
        ready = env.store.ready(cfg.pick_label)
    except BdFailure:
        ready: list[Bead] = []
    rule = QueueRule(env.store, cfg, env.running(), env.lint, say, env.now)
    return rule.rank(ready, env.repo), rule
