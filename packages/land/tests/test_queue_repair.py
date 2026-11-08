"""Attribution waits for proof and repairs only dependent queue commits."""
import pytest

from tlland.domain.queue_model import (
    Drop,
    Eject,
    Ejected,
    Entry,
    Merge,
    Phase,
    Reset,
    apply,
    plan,
)


def chain(*phases: Phase) -> list[Entry]:
    return [Entry(branch=f"b{i}", head=f"h{i}", phase=phase, q=f"q{i}", tree=f"t{i}", ref=f"r{i}",
                  after=f"b{i - 1}" if i else "") for i, phase in enumerate(phases)]


@pytest.mark.parametrize("ahead", [Phase.GATING, Phase.RED, Phase.WAITING])
def test_red_waits_for_an_unproven_predecessor(ahead):
    actions = plan(chain(ahead, Phase.RED), "main", 2)
    assert Eject("b1", "gate") not in actions
    if ahead is Phase.RED:
        assert actions == [Eject("b0", "gate")]


def test_red_after_green_is_attributed():
    assert plan(chain(Phase.GREEN, Phase.RED), "main", 2) == [Eject("b1", "gate")]


@pytest.mark.parametrize("behind", [Phase.BUILT, Phase.GATING, Phase.GREEN, Phase.RED])
def test_middle_ejection_resets_exactly_the_chain_behind_it(behind):
    entries = apply(chain(Phase.GREEN, Phase.RED, behind, behind), Ejected("b1", "gate"))
    actions = plan(entries, "main", 4)
    assert actions == [Drop("b1", "r1"), Reset("b2", "r2"), Reset("b3", "r3")]
    for action in actions:
        if isinstance(action, Reset):
            entries = apply(entries, Reset(action.branch))
    assert entries[0].phase is Phase.GREEN
    assert all((e.phase, e.q, e.tree, e.ref, e.after) == (Phase.WAITING, "", "", "", "") for e in entries[2:])
    assert not any(isinstance(action, Reset) for action in plan(entries, "main", 4))


def test_a_merged_predecessor_does_not_invalidate_the_green_head():
    assert plan(chain(Phase.MERGED, Phase.GREEN), "main", 2) == [Drop("b0", "r0"), Merge("b1", "q1", "t1")]


def test_waiting_predecessor_invalidates_the_whole_chain():
    assert plan(chain(Phase.WAITING, Phase.GATING, Phase.RED), "main", 3) == [Reset("b1", "r1"), Reset("b2", "r2")]
