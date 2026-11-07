"""The queue planner (merge-queue.md section 3): pure, so the merge order, the gates in flight and the cleanup are tables."""
import pytest

from taskloop.domain.land.queue_model import Build, Built, Drop, Ejected, Entry, Gate, Gated, Landed, Merge, Phase, apply, plan
from tlkernel.config import ConfigError, load

MAIN = "main0"


def entries(*phases: Phase) -> list[Entry]:
    built = [p is not Phase.WAITING for p in phases]
    return [Entry(branch=f"b{i}", head=f"h{i}", phase=p, q=f"q{i}" * b, tree=f"t{i}" * b, ref=f"r{i}" * b)
            for i, (p, b) in enumerate(zip(phases, built, strict=True))]


def test_the_first_waiting_entry_is_built_on_main_and_the_next_waits_for_its_q():
    assert plan(entries(Phase.WAITING, Phase.WAITING), MAIN, 2) == [Build("b0", "h0", MAIN)]


def test_the_next_entry_is_built_on_the_q_of_the_one_ahead():
    assert plan(entries(Phase.BUILT, Phase.WAITING), MAIN, 2) == [Gate("b0", "q0"), Build("b1", "h1", "q0", "b0")]


def test_gates_in_flight_bound_the_gates_started():
    assert plan(entries(Phase.GATING, Phase.BUILT, Phase.BUILT), MAIN, 1) == []
    assert plan(entries(Phase.BUILT, Phase.BUILT, Phase.BUILT), MAIN, 2) == [Gate("b0", "q0"), Gate("b1", "q1")]


def test_at_one_in_flight_the_queue_is_serial_build_gate_merge():
    assert plan(entries(Phase.WAITING), MAIN, 1) == [Build("b0", "h0", MAIN)]
    assert plan(entries(Phase.BUILT, Phase.WAITING), MAIN, 1) == [Gate("b0", "q0")]
    assert plan(entries(Phase.GREEN, Phase.WAITING), MAIN, 1) == [Merge("b0", "q0", "t0")]


def test_only_the_head_merges_and_a_green_behind_a_gating_head_waits():
    assert plan(entries(Phase.GATING, Phase.GREEN), MAIN, 2) == []
    assert plan(entries(Phase.GREEN, Phase.GREEN), MAIN, 2) == [Merge("b0", "q0", "t0")]


def test_an_entry_that_left_has_its_refs_dropped_and_is_skipped_for_the_chain():
    es = entries(Phase.MERGED, Phase.EJECTED, Phase.WAITING)
    assert plan(es, MAIN, 2) == [Drop("b0", "r0"), Drop("b1", "r1"), Build("b2", "h2", MAIN)]


def test_a_conflict_is_a_result_the_entry_is_ejected_and_the_queue_goes_on():
    es = apply(entries(Phase.WAITING, Phase.WAITING), Ejected("b0", "conflict"))
    assert [(e.phase, e.reason) for e in es] == [(Phase.EJECTED, "conflict"), (Phase.WAITING, "")]
    assert plan(es, MAIN, 2) == [Build("b1", "h1", MAIN)]


def test_events_move_an_entry_through_its_phases():
    es = entries(Phase.WAITING)
    es = apply(es, Built("b0", "q", "t"))
    assert (es[0].phase, es[0].q, es[0].tree) == (Phase.BUILT, "q", "t")
    assert apply(es, Gated("b0", True))[0].phase is Phase.GREEN
    assert apply(es, Gated("b0", False))[0].phase is Phase.RED
    assert apply(es, Landed("b0"))[0].phase is Phase.MERGED


@pytest.mark.parametrize("in_flight", [1, 2, 3])
def test_a_run_to_the_end_merges_in_queue_order_whatever_order_the_gates_finish(in_flight):
    es = entries(*[Phase.WAITING] * 4)
    merged: list[str] = []
    for _ in range(40):
        acts = plan(es, MAIN, in_flight)
        if not acts and all(e.phase is Phase.MERGED for e in es):
            break
        for act in reversed(acts):  # the latest gate answers first
            if isinstance(act, Build):
                es = apply(es, Built(act.branch, "q-" + act.branch, "t-" + act.branch))
            elif isinstance(act, Gate):
                es = apply(es, Gated(act.branch, True))
            elif isinstance(act, Merge):
                merged.append(act.branch)
                es = apply(es, Landed(act.branch))
    assert merged == ["b0", "b1", "b2", "b3"]


def test_the_config_key_defaults_to_off_and_reads_shadow_and_on():
    assert load({}).engine.land_queue == "off"
    assert load({"engine": {"land_queue": "on"}}).engine.land_queue == "on"


def test_the_cap_key_defaults_to_four_and_refuses_less_than_one():
    assert load({}).engine.land_queue_max_in_flight == 4
    assert load({"engine": {"land_queue_max_in_flight": 2}}).engine.land_queue_max_in_flight == 2
    with pytest.raises(ConfigError, match="at least 1"):
        load({"engine": {"land_queue_max_in_flight": 0}})
