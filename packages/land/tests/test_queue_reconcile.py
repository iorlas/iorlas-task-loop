"""Recovery rules and generated fixed points, using only in-memory facts."""
import random
from dataclasses import replace

import pytest

from tlland.domain.queue_model import Entry, Phase
from tlland.domain.queue_reconcile import (
    PREFIX,
    AssertAndRecord,
    BuildFact,
    DropRef,
    Facts,
    KillBuild,
    NotifyEjected,
    PrFact,
    RemoveWorktree,
    ResetPending,
    apply_actions,
    reconcile,
    settle,
)

REF = PREFIX + "a"
ENTRY = Entry(branch="a", head="h", phase=Phase.GATING, q="q", tree="t", ref=REF)
BUILD = BuildFact("a", 7, "start", 20.0, "tree-a")
FACTS = Facts(frozenset({REF}), frozenset({"tree-a"}), {7: "start"}, "main",
              {}, {"a": BUILD}, frozenset(), frozenset(), 10.0)


@pytest.mark.parametrize(("entry", "facts", "expected"), [
    (ENTRY, replace(FACTS, alive={}),
     [RemoveWorktree("tree-a"), DropRef(REF), ResetPending("a")]),
    (ENTRY, replace(FACTS, alive={7: "reused"}),
     [RemoveWorktree("tree-a"), DropRef(REF), ResetPending("a")]),
    (ENTRY, replace(FACTS, now=20.0),
     [KillBuild("a", 7), RemoveWorktree("tree-a"), DropRef(REF), ResetPending("a")]),
    (ENTRY, replace(FACTS, builds={}),
     [RemoveWorktree("tree-a"), DropRef(REF), ResetPending("a")]),
    (ENTRY, replace(FACTS, refs=frozenset()),
     [RemoveWorktree("tree-a"), ResetPending("a")]),
    (ENTRY, replace(FACTS, refs=frozenset({REF, PREFIX + "orphan", "other"})),
     [DropRef(PREFIX + "orphan")]),
    (ENTRY, replace(FACTS, worktrees=frozenset({"tree-a", "orphan"})),
     [RemoveWorktree("orphan")]),
    (ENTRY, replace(FACTS, refs=frozenset(), prs={"a": PrFact("merged", "sha")}),
     [RemoveWorktree("tree-a"), AssertAndRecord("a", "sha")]),
    (ENTRY.replace(phase=Phase.EJECTED), FACTS,
     [RemoveWorktree("tree-a"), DropRef(REF), NotifyEjected("a")]),
    (ENTRY, FACTS, []),
])
def test_rules(entry, facts, expected):
    assert reconcile([entry], facts) == expected
    assert reconcile(apply_actions([entry], expected), settle(facts, expected)) == []


@pytest.mark.parametrize("phase", [Phase.BUILT, Phase.GATING, Phase.GREEN])
def test_missing_ref_resets_queue_commit(phase):
    actions = reconcile([ENTRY.replace(phase=phase)], replace(FACTS, refs=frozenset()))
    assert ResetPending("a") in actions
    entry, = apply_actions([ENTRY], actions)
    assert (entry.phase, entry.q, entry.tree, entry.ref) == (Phase.WAITING, "", "", "")


def test_determinism_and_order():
    entries = [ENTRY.replace(branch=b, ref=PREFIX + b) for b in ("z", "a")]
    facts = replace(FACTS, builds={}, refs=frozenset({PREFIX + "z", REF}))
    first = reconcile(entries, facts)
    assert first == reconcile(list(entries), replace(facts))
    assert first == reconcile(list(reversed(entries)), facts)
    assert first == [RemoveWorktree("tree-a"), DropRef(REF), DropRef(PREFIX + "z"),
                     ResetPending("a"), ResetPending("z")]


def random_world(seed):
    rng = random.Random(seed)
    entries, refs, paths, alive, builds, prs = [], set(), set(), {}, {}, {}
    recorded, notified = set(), set()
    for index in range(rng.randrange(1, 9)):
        branch = f"b{index}"
        ref, path = PREFIX + branch, "tree-" + branch
        phase = rng.choice(list(Phase))
        entries.append(Entry(branch=branch, head="h", phase=phase, q="q", tree="t", ref=ref))
        if rng.choice([True, False]):
            refs.add(ref)
        if rng.choice([True, False]):
            paths.add(path)
        if rng.choice([True, False]):
            alive[index] = rng.choice(["start", "other"])
        if rng.choice([True, False]):
            builds[branch] = BuildFact(branch, index, "start", rng.choice([9.0, 10.0, 11.0]), path)
        prs[branch] = PrFact(rng.choice(["open", "merged", "closed"]), rng.choice(["", "sha"]))
        if rng.choice([True, False]):
            recorded.add(branch)
        if rng.choice([True, False]):
            notified.add(branch)
    refs.update({PREFIX + "orphan", "unrelated"})
    paths.add("orphan")
    return entries, Facts(frozenset(refs), frozenset(paths), alive, "main", prs, builds,
                          frozenset(recorded), frozenset(notified), 10.0)


@pytest.mark.parametrize("seed", random.Random(731).sample(range(1000000), 300))
def test_recovery_reaches_fixed_point(seed):
    entries, facts = random_world(seed)
    actions = reconcile(entries, facts)
    assert reconcile(apply_actions(entries, actions), settle(facts, actions)) == []
