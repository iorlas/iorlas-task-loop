"""Crash at every sub-step of ejection, rebuilding and landing."""
from dataclasses import dataclass, replace

import pytest

from tlland.domain.queue_model import Entry, Phase, live
from tlland.domain.queue_reconcile import (
    PREFIX,
    BuildFact,
    Facts,
    PrFact,
    apply_actions,
    reconcile,
    settle,
)


@dataclass
class World:
    entries: list[Entry]
    facts: Facts


def initial_world():
    entries = [Entry(branch=str(i), head=f"h{i}", phase=Phase.GATING,
                     q=f"q{i}", tree=f"t{i}", ref=PREFIX + str(i)) for i in (1, 2, 3)]
    builds = {e.branch: BuildFact(e.branch, i, "start", 20.0, "tree-" + e.branch)
              for i, e in enumerate(entries, 1)}
    return World(entries, Facts(frozenset(e.ref for e in entries),
                               frozenset(b.worktree for b in builds.values()),
                               dict.fromkeys((1, 2, 3), "start"), "main", {}, builds,
                               frozenset(), frozenset(), 10.0))


def eject_second(world):
    world.entries = [e.replace(phase=Phase.EJECTED) if e.branch == "2" else e for e in world.entries]


def drop_second_ref(world):
    world.facts = replace(world.facts, refs=world.facts.refs - {PREFIX + "2"})


def stop_second_build(world):
    world.facts = replace(world.facts, alive={p: s for p, s in world.facts.alive.items() if p != 2})


def invalidate_third(world):
    world.facts = replace(world.facts, refs=world.facts.refs - {PREFIX + "3"})


def reset_third(world):
    world.entries = [e.replace(phase=Phase.WAITING, q="", tree="", ref="")
                     if e.branch == "3" else e for e in world.entries]


def build_third_on_first(world):
    first = world.entries[0]
    world.entries = [e.replace(phase=Phase.BUILT, q=first.q + "+h3", tree="t13", ref=PREFIX + "3")
                     if e.branch == "3" else e for e in world.entries]
    world.facts = replace(world.facts, refs=world.facts.refs | {PREFIX + "3"})


def gate_third(world):
    world.entries = [e.replace(phase=Phase.GATING) if e.branch == "3" else e for e in world.entries]
    world.facts = replace(world.facts, builds={**world.facts.builds,
                         "3": BuildFact("3", 4, "new", 30.0, "tree-3-new")},
                         alive={**world.facts.alive, 4: "new"},
                         worktrees=world.facts.worktrees | {"tree-3-new"})


def green_first(world):
    world.entries = [e.replace(phase=Phase.GREEN) if e.branch == "1" else e for e in world.entries]


def merge_first(world):
    world.facts = replace(world.facts, prs={"1": PrFact("merged", "landed-1")}, main_sha="landed-1")


def drop_first_ref(world):
    world.facts = replace(world.facts, refs=world.facts.refs - {PREFIX + "1"})


def record_first(world):
    world.entries = [e.replace(phase=Phase.MERGED) if e.branch == "1" else e for e in world.entries]
    world.facts = replace(world.facts, recorded=world.facts.recorded | {"1"})


STEPS = (eject_second, drop_second_ref, stop_second_build, invalidate_third,
         reset_third, build_third_on_first, gate_third, green_first,
         merge_first, drop_first_ref, record_first)


def assert_invariants(world):
    queue = live(world.entries)
    for entry in queue:
        if entry.phase is Phase.WAITING:
            continue
        assert entry.ref in world.facts.refs
        if entry.phase is Phase.GATING:
            build = world.facts.builds[entry.branch]
            assert world.facts.alive.get(build.pid) == build.start_id
            assert build.lease_expires > world.facts.now
            assert build.worktree in world.facts.worktrees
    assert all(not ref.startswith(PREFIX) or any(e.ref == ref for e in queue)
               for ref in world.facts.refs)
    assert world.facts.worktrees <= {world.facts.builds[e.branch].worktree for e in queue
                                    if e.branch in world.facts.builds}


@pytest.mark.parametrize("prefix", range(len(STEPS) + 1))
def test_every_crash_prefix(prefix):
    world = initial_world()
    for step in STEPS[:prefix]:
        step(world)
    actions = reconcile(world.entries, world.facts)
    world.entries = apply_actions(world.entries, actions)
    world.facts = settle(world.facts, actions)
    assert_invariants(world)
    assert reconcile(world.entries, world.facts) == []
