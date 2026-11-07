"""The queue rule: ready beads with the pick label, minus skip labels, epics, slots, beads that fail bead lint (domain/beads/rules.py)
and beads whose area runs elsewhere; then priority, epic order, lowest id. Every skip says which rule skipped it as a typed
Skip; nothing is parsed back out of text."""
import itertools
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from tlkernel import pickset
from tlkernel.bead import Bead
from tlkernel.beadsport import BdFailure, BeadPatch, BeadQuery, Beads
from tlkernel.config import EngineConfig
from tlkernel.ids import BeadId, is_bead_id, parse_bead_id
from tlkernel.loop import Skip

from taskloop.app.loop import hosts
from taskloop.app.loop.env import LoopEnv
from taskloop.domain.asks import hold

Key = tuple[int, int, list[tuple[int, int | str]], Bead]  # (priority, epic rank, natural id, bead)
ORDERED = "ordered"  # the label of an epic whose children must name what they follow
ANY_AREA = "*"  # busy_areas key for a running bead that could not be read: every area waits


def natural(bead_id: BeadId) -> list[tuple[int, int | str]]:
    """a1.26.9 before a1.26.10: digit runs compare as numbers."""
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
    bead: BeadId
    skip: Skip
    of: Bead | None = None  # the bead itself, when the skip is a lint refusal (the loop labels it)


@dataclass
class Queue:
    ranked: list[Ranked] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)

    def areas(self) -> list[Skipped]:
        return [s for s in self.skipped if s.skip.kind == "area"]


def area_skip(area: str, holder: str, where: str) -> Skip:
    return Skip(why=f"area {area} busy: {holder} in {where}", kind="area", area=area, holder=holder, where=where)


class QueueRule:
    def __init__(self, store: Beads, cfg: EngineConfig, running: dict[BeadId, str], lint: Callable[[Bead], str],
                 say: Callable[[str], None] = print, now: Callable[[], float] = time.time,
                 parked: Callable[[Bead], Skip | None] = lambda b: None,
                 hosted: Callable[[Bead], Skip | None] = lambda b: None) -> None:
        self.store, self.cfg, self.running, self.lint, self.say, self.now = store, cfg, running, lint, say, now
        self.parked = parked  # a bead whose last run ended on a question and whose text is the same (tl-7y6.7.3)
        self.hosted = hosted  # a bead whose needs label names a resource this host lacks (tl-7k8.8)
        self.parents: dict[BeadId, BeadId | None] = {}
        self.ordered: dict[str, bool] = {}  # epic -> carries the `ordered` label
        self.umbrellas: set[str] = set()
        self.chosen: list[BeadId] = []  # the pick set (contracts/pickset.py); [] = every ready bead
        self.only = False

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
        if b.id in self.umbrellas:
            return Skip(why="an umbrella: it has open children", kind="epic")
        if "slot" in b.labels:
            return Skip(why="a slot", kind="slot")
        if hit:
            return Skip(why="label " + hit, kind="label")
        who = hold.held(b.metadata, self.now())
        if who:
            until = float(b.metadata.get(hold.HOLD_UNTIL) or 0)
            return Skip(why=f"held by {who}", kind="hold", until=until or None)
        return self.hosted(b) or self.parked(b) or self.unordered(b)

    def unordered(self, b: Bead) -> Skip | None:
        """A direct child of an epic labelled `ordered` that waits for nothing: the order is data, so the child names what it follows
        (a `blocks` dep; the parent-child link is no order). An epic or child bd cannot show is not a reason to skip."""
        parent = b.parent
        if not is_bead_id(parent) or (parent not in self.ordered and not self.reads_ordered(BeadId(parent))):
            return None
        if not self.ordered[parent]:
            return None
        try:
            held = self.store.show(b.id)
        except BdFailure:
            return None
        if held is None or any(d.type != "parent-child" for d in held.dependencies):
            return None
        return Skip(why=f"ordered epic {parent}: add a dep (bd dep add) or drop the label", kind="unordered")

    def reads_ordered(self, epic: BeadId) -> bool:
        """Remember whether the epic carries the `ordered` label; False (and nothing remembered) when bd cannot show it."""
        try:
            found = self.store.show(epic)
        except BdFailure:
            return False
        self.ordered[epic] = bool(found and ORDERED in found.labels)
        return True

    def rank(self, ready: list[Bead], repo: str, open_beads: Sequence[Bead] | None = None) -> Queue:
        self.umbrellas = {b.parent for b in (ready if open_beads is None else open_beads) if b.parent and b.status != "closed"}
        order = list(self.cfg.epic_order)
        keep: list[Key] = []
        q = Queue()
        for b in ready:
            skip = pickset.outside(b.id, self.chosen, self.only) or self.why_not(b)
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
                q.skipped.append(Skipped(b.id, skip, b if skip.kind == "lint" else None))
            else:
                keep.append((b.priority if b.priority is not None else 2, rank, natural(b.id), b))
        keep.sort(key=lambda k: (self.chosen.index(k[3].id), *k[:3]) if self.chosen else k[:3])
        if has_areas(self.cfg) and keep:
            keep = self.drop_busy(keep, q)
        q.ranked = [Ranked(k[3], f"{ordinal(self.chosen.index(k[3].id) + 1)} of {len(self.chosen)} chosen" if self.chosen
                           else self.reason(keep, i, order)) for i, k in enumerate(keep)]
        self.unready(q, ready)
        return q

    def unready(self, q: Queue, ready: list[Bead]) -> None:
        """A chosen bead bd does not list as ready is named with the reason, so `tl next` explains it."""
        seen = {b.id for b in ready}
        for bid in self.chosen:
            if bid not in seen:
                try:
                    held = self.store.show(BeadId(bid))
                except BdFailure:
                    held = None
                q.skipped.append(Skipped(BeadId(bid), pickset.unready(held, bid)))

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


def rank_ready(env: LoopEnv, cfg: EngineConfig, say: Callable[[str], None] = print,
               only: Sequence[str] = ()) -> tuple[Queue, QueueRule]:
    """The queue as the loop would take it now: only the chosen beads (`only`, else the beads labelled `queue`) when any are chosen."""
    ready: list[Bead] = []
    chosen: list[BeadId] = []
    open_beads: list[Bead] = []
    try:
        ready = env.store.ready(cfg.pick_label)
        open_beads = env.store.find(BeadQuery())
        chosen = pickset.members(open_beads, only)
    except BdFailure:  # a queue that cannot be read must not become "take anything"
        ready = []
    rule = QueueRule(env.store, cfg, env.running(), env.lint, say, env.now, env.asks.skip_of,
                    lambda b: hosts.skip_of(cfg, env.host(), b))
    rule.chosen, rule.only = chosen, bool(only)
    return rule.rank(ready, env.repo, open_beads), rule


def owner_queue(op: str, ids: list[str], store: Beads, now: Callable[[], float]) -> tuple[int, list[str]]:
    """Apply the owner's queue operation and return its exit code and display lines."""
    if op in ("add", "remove") and not ids:
        return 2, [f"tl: queue {op}: name at least one bead"]
    try:
        if op == "add":
            t = int(now() * 1000)
            for n, raw in enumerate(ids):
                bid = parse_bead_id(raw)
                if store.show(bid) is None:
                    return 1, [f"tl: no such bead {raw}"]
                store.add_label(bid, pickset.LABEL)
                store.update(bid, BeadPatch(set_metadata={pickset.AT: str(t + n)}))
        elif op == "remove":
            for raw in ids:
                bid = parse_bead_id(raw)
                store.remove_label(bid, pickset.LABEL)
                store.update(bid, BeadPatch(unset_metadata=[pickset.AT]))
        beads = store.find(BeadQuery(label=pickset.LABEL))
    except (BdFailure, ValueError) as e:
        return 1, [f"tl: {e}"]
    chosen = pickset.members(beads)
    by_id = {b.id: b for b in beads}
    lines = []
    if not chosen:
        lines.append("queue empty: the loop takes any ready bead")
    for n, i in enumerate(chosen, 1):
        lines.append(f"{n}. {i}  {by_id[i].status}  {by_id[i].title[:70]}")
    return 0, lines
