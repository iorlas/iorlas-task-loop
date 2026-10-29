"""`tl lint` over a store: one bead, or the repo's ready beads (with --fix: drop `auto` and add `needs-ac` where they fail)."""
from taskloop.contracts.ports import BdFailure, BeadQuery, Beads
from taskloop.domain.beads import rules


def has_children(store: Beads, bead: str) -> bool:
    """Does any open bead name this one as its parent."""
    return any(x.parent == bead for x in store.find(BeadQuery()))


def lint_one(store: Beads, root: str, bead_id: str) -> int:
    bead = store.show(bead_id)
    if bead is None:
        print(f"no bead {bead_id}")
        return 1
    fails = rules.failures(bead, root, lambda: has_children(store, bead.id))
    for f in fails:
        print(f"{bead.id} {f.line()}")
    if not fails:
        print(f"{bead.id} pass")
    return 1 if fails else 0


def lint_ready(store: Beads, root: str, fix: bool) -> int:
    ready, bad = store.ready(), 0
    for bead in ready:
        fails = rules.failures(bead, root, lambda b=bead: has_children(store, b.id))
        bad += bool(fails)
        print(f"{bead.id:<16} {'auto' if rules.AUTO in bead.labels else '    '}  {'; '.join(f.line() for f in fails) or 'pass'}")
        if fails and fix:
            fix_bead(store, bead.id, bead.labels)
    print(f"{len(ready)} ready, {bad} fail")
    return 0 if fix or not bad else 1


def fix_bead(store: Beads, bead_id: str, labels: list[str]) -> None:
    try:
        if rules.AUTO in labels:
            store.remove_label(bead_id, rules.AUTO)
            print(f"  {bead_id}: removed {rules.AUTO}")
        if rules.NEEDS_AC not in labels:
            store.add_label(bead_id, rules.NEEDS_AC)
            print(f"  {bead_id}: added {rules.NEEDS_AC}")
    except BdFailure as e:
        print(f"  {bead_id}: bd refused: {e}")
