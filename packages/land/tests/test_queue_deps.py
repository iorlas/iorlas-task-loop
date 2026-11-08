"""Pure dependency scheduling cases from merge-queue design section 11."""
import pytest

from tlland.domain.queue_deps import Gate, State, find_cycle, gate


@pytest.mark.parametrize(("edges", "expected"), [
    ({"a": ["a"]}, ["a", "a"]),
    ({"a": ["b"], "b": ["a"]}, ["a", "b", "a"]),
    ({"a": ["b", "c"], "b": ["d"], "c": ["d"]}, []),
    ({}, []),
])
def test_cycles(edges: dict[str, list[str]], expected: list[str]) -> None:
    assert find_cycle(edges) == expected


@pytest.mark.parametrize(("parents", "states", "age", "expected"), [
    ([], {}, 0, Gate.READY),
    (["p"], {}, 0, Gate.WAITING),
    (["p"], {"p": State.MERGED}, 0, Gate.READY),
    (["p"], {"p": State.ABANDONED}, 9, Gate.WAITING),
    (["p"], {"p": State.ABANDONED}, 10, Gate.WAITING),
    (["p"], {"p": State.ABANDONED}, 11, Gate.BLOCKED_ABANDONED),
    (["p", "q"], {"p": State.MERGED, "q": State.OPEN}, 0, Gate.WAITING),
])
def test_gate(
    parents: list[str], states: dict[str, State], age: float, expected: Gate,
) -> None:
    assert gate("child", {"child": parents}, states,
                abandoned_for_s={"p": age}, timeout_s=10) is expected


@pytest.mark.parametrize("edges", [
    {"a": ["a"]}, {"a": ["b"], "b": ["a"]},
])
def test_cycle_blocks_gate(edges: dict[str, list[str]]) -> None:
    assert gate("a", edges, {"a": State.MERGED, "b": State.MERGED}) is Gate.BLOCKED_CYCLE


def test_unmerged_parent_never_releases_child() -> None:
    for state in State:
        result = gate("child", {"child": ["p", "q"]}, {"p": state, "q": State.MERGED})
        assert (result is Gate.READY) == (state is State.MERGED)


def test_deep_graph_is_iterative() -> None:
    edges = {str(i): [str(i + 1)] for i in range(2000)}
    assert find_cycle(edges) == []
    assert gate("0", edges, {}) is Gate.WAITING
