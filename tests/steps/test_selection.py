"""Selection over the owner-accepted hierarchical-priority contract (tl-8bh9.3): every scenario row, the padding and
natural-id rules, the non-transitive trap, eligibility skips and an ancestry read that does no IO in the comparator."""

from collections.abc import Mapping

import pytest

from taskloop.selection import Lookup, natural, order
from taskloop.task import TaskInspectionError
from taskloop.tracker import TaskRow


def row(task_id: str, priority: int | None, parent: str = "", assignee: str = "") -> TaskRow:
    return TaskRow(task_id, priority, parent, assignee)


class Tasks:
    """A counting lookup over known tasks: `failing` ids raise as an unreadable record; any other unknown id is absent."""

    def __init__(self, *rows: TaskRow, failing: tuple[str, ...] = ()) -> None:
        self.rows, self.failing = {each.task_id: each for each in rows}, failing
        self.calls: list[str] = []

    def __call__(self, task_id: str) -> TaskRow | None:
        self.calls.append(task_id)
        if task_id in self.failing:
            raise TaskInspectionError("tracker_unavailable", "bd timed out")
        return self.rows.get(task_id)


def first(candidates: list[TaskRow], lookup: Lookup, attempts: Mapping[str, bool] | None = None) -> str:
    ordered, skipped = order(candidates, lookup, attempts or {}, "taskloop")
    assert skipped == ()
    return ordered[0].task_id


# (candidates, parents and grandparents, expected first) per row of the contract's scenario table
SCENARIOS: list[tuple[str, list[TaskRow], list[TaskRow], str]] = [
    ("own priority dominates every ancestor", [row("a-1", 0, "p2"), row("a-2", 3, "p0")], [row("p2", 2), row("p0", 0)], "a-1"),
    ("direct parent breaks an own-priority tie", [row("a-1", 1, "p2"), row("a-2", 1, "p0")], [row("p2", 2), row("p0", 0)], "a-2"),
    ("outward only while nearer ties", [row("a-1", 1, "x"), row("a-2", 1, "y")],
     [row("x", 2, "g3"), row("y", 2, "g0"), row("g3", 3), row("g0", 0)], "a-2"),
    ("specific subgroup beats broad portfolio", [row("a-1", 1, "p4"), row("a-2", 1, "q0")],
     [row("p4", 4, "r0"), row("q0", 0, "r2"), row("r0", 0), row("r2", 2)], "a-2"),
    ("standalone vs only P2 ancestors: id decides", [row("a-2", 1), row("a-1", 1, "p2")], [row("p2", 2)], "a-1"),
    ("standalone vs only P2 ancestors: id decides, other way", [row("a-1", 1), row("a-2", 1, "p2")], [row("p2", 2)], "a-1"),
    ("known urgent parent beats default context", [row("a-1", 1), row("a-2", 1, "p0")], [row("p0", 0)], "a-2"),
    ("deferred context loses to default context", [row("a-1", 1, "p4"), row("a-2", 1)], [row("p4", 4)], "a-2"),
    ("missing own priority stays P2", [row("a-1", None, "p0"), row("a-2", 0)], [row("p0", 0)], "a-2"),
    ("identical siblings: id decides", [row("a-2", 1, "p1"), row("a-1", 1, "p1")], [row("p1", 1)], "a-1"),
]


@pytest.mark.parametrize("candidates, ancestors, expected", [case[1:] for case in SCENARIOS], ids=[case[0] for case in SCENARIOS])
def test_every_scenario_of_the_contract(candidates: list[TaskRow], ancestors: list[TaskRow], expected: str) -> None:
    assert first(candidates, Tasks(*ancestors)) == expected
    assert first(list(reversed(candidates)), Tasks(*ancestors)) == expected  # the tracker's order never decides


def test_missing_levels_pad_with_p2_to_the_deepest_chain() -> None:
    """A standalone P1 equals a P1 under P2 ancestors at every level; a P3 grandparent behind a P2 parent loses to it."""
    lookup = Tasks(row("p2", 2, "g3"), row("g3", 3), row("q2", 2))
    ordered, _ = order([row("t-3", 1, "p2"), row("t-1", 1), row("t-2", 1, "q2")], lookup, {}, "taskloop")
    assert [each.task_id for each in ordered] == ["t-1", "t-2", "t-3"]


def test_the_non_transitive_trap_gives_one_total_order() -> None:
    """A (parent P0, id 3), C (parent P4, id 1), standalone B (id 2): padding compares (P0) < (P2) < (P4)."""
    lookup = Tasks(row("p0", 0), row("p4", 4))
    candidates = [row("t-3", 1, "p0"), row("t-1", 1, "p4"), row("t-2", 1)]
    for shuffled in (candidates, candidates[::-1], [candidates[1], candidates[2], candidates[0]]):
        ordered, _ = order(shuffled, lookup, {}, "taskloop")
        assert [each.task_id for each in ordered] == ["t-3", "t-2", "t-1"]


def test_natural_ids_compare_digit_runs_as_numbers() -> None:
    ordered, _ = order([row("t-10", 1), row("t-2", 1), row("t-2.10", 1), row("t-2.9", 1), row("s-30", 1)], Tasks(), {}, "taskloop")
    assert [each.task_id for each in ordered] == ["s-30", "t-2", "t-2.9", "t-2.10", "t-10"]
    assert natural("t-\u0663") == ((0, "t-"), (1, 3))  # a decimal digit of another script is a number, as int() reads it


def test_a_cyclic_missing_or_unreadable_chain_skips_only_that_candidate() -> None:
    lookup = Tasks(row("c1", 0, "c2"), row("c2", 0, "c1"), failing=("bad",))
    candidates = [row("t-1", 1, "c1"), row("t-2", 1, "gone"), row("t-3", 1, "bad"), row("t-4", 3), row("t-5", 0, "t-5")]
    ordered, skipped = order(candidates, lookup, {}, "taskloop")
    assert [each.task_id for each in ordered] == ["t-4"]
    assert skipped == (("t-1", "ancestry"), ("t-2", "ancestry"), ("t-3", "unavailable:ancestry"), ("t-5", "ancestry"))


def test_eligibility_skips_attempted_abandoned_and_another_actors_task_but_keeps_the_factorys() -> None:
    candidates = [row("t-1", 0), row("t-2", 0), row("t-3", 0, assignee="person"), row("t-4", 1, assignee="taskloop"), row("t-5", 2)]
    lookup = Tasks()
    ordered, skipped = order(candidates, lookup, {"t-1": False, "t-2": True}, "taskloop")
    assert [each.task_id for each in ordered] == ["t-4", "t-5"]
    assert skipped == (("t-1", "attempted"), ("t-2", "abandoned"), ("t-3", "assigned"))
    assert lookup.calls == []  # no parent: nothing read


def test_a_whole_chain_decides_and_every_read_happens_before_the_order_is_fixed() -> None:
    """Grandparents decide when parents tie; an ancestor read is never needed again once the order is returned."""
    lookup = Tasks(row("p-a", 1, "g-0"), row("p-b", 1, "g-3"), row("g-0", 0), row("g-3", 3))
    ordered, _ = order([row("t-1", 1, "p-b"), row("t-2", 1, "p-a")], lookup, {}, "taskloop")
    lookup.rows.clear()
    assert [each.task_id for each in ordered] == ["t-2", "t-1"]
    assert set(lookup.calls) == {"p-a", "p-b", "g-0", "g-3"}
