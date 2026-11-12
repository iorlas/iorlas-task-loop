"""The land (tl-8bh9.14.8 sections 4-6, slice L3) over `land_bench`: section 4's refusals in order with nothing written,
the same-tree land with no slot, a moved `main` and changed required names validated in a slot then pushed, a conflict,
a failed validation, and the no-change disposition."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from doubles import Command
from land_bench import BAR, ME, RUN, LandBench, bench

from taskloop.land import Landed, LandResult
from taskloop.operations import Failed


@pytest.fixture
def b(tmp_path: Path) -> LandBench:
    return bench(tmp_path)


def failed(found: LandResult) -> tuple[str, str]:
    assert isinstance(found, Failed), found
    return found.kind, found.reason


def nothing_changed(b: LandBench, main: str) -> None:
    """No candidate, no reservation, no push, origin's `main` where it was."""
    assert b.rows() == () and b.reservations() == [] and b.repo.pushes == 0 and b.origin_main() == main


def test_the_same_tree_lands_s_onto_o_with_no_slot_and_no_check(b: LandBench) -> None:
    person = (b.repo.refs(["refs/heads/main"]), b.repo.worktree(b.repo.path).branch())
    found = b.land()
    assert isinstance(found, Landed) and found.how == "pushed"
    s = found.row.commit
    assert b.origin_main() == s == found.row.remote_head and found.row.origin == b.base
    assert b.repo.is_ancestor(b.base, s) and b.repo.count([s], [b.base]) == 1  # S's one parent is O
    assert b.files_of(s) == b.files_of(b.x) and s != b.x
    row = b.rows()[0]
    assert (row.number, row.validation, row.slot, row.tree_same, row.delivery) == (1, "same_tree", None, True, "pushed")
    assert b.execs() == [] and b.reservations() == [] and b.repo.pushes == 1
    assert (b.repo.refs(["refs/heads/main"]), b.repo.worktree(b.repo.path).branch()) == person  # the person's main untouched


def test_a_moved_main_validates_s_in_a_slot_releases_it_then_pushes(b: LandBench) -> None:
    o = b.advance({"OTHER": "another task\n"})
    found = b.land()
    assert isinstance(found, Landed) and found.how == "pushed"
    s = found.row.commit
    assert b.origin_main() == s and b.repo.count([s], [o]) == 1 and b.repo.is_ancestor(o, s)
    assert b.files_of(s)["OTHER"] == "another task\n" and b.files_of(s)["src/x.py"] == "X = 1\n"  # X merged onto O
    assert b.execs() == RUN
    row = b.rows()[0]
    assert (row.validation, row.slot, row.tree_same, row.entry, row.parked) == ("passed", "s1", False, ME, b.d)
    assert row.released_at is not None and b.reservations() == [] and b.slot_head() == b.d
    results = b.con.execute("SELECT attempt_id,block,name,conclusion FROM check_result ORDER BY position").fetchall()
    assert results == [(row.key.attempt_id, 1, "check", "passed"), (row.key.attempt_id, 1, "test", "passed")]


def test_changed_required_names_validate_although_the_tree_is_the_same(b: LandBench) -> None:
    b.con.execute("UPDATE checks_attempt SET required=?", (json.dumps([["check", "1" * 64]]),))
    found = b.land()
    assert isinstance(found, Landed) and found.row.tree_same and found.row.validation == "passed" and b.execs() == RUN


def test_a_failed_validation_pushes_nothing_and_leaves_its_slot_released(b: LandBench) -> None:
    main = b.advance({"OTHER": "y\n"})
    b.environment.process.script = [Command(), Command(), Command(rc=1)]
    assert failed(b.land()) == ("refused", "checks_failed")
    row = b.rows()[0]
    assert (row.validation, row.reason, row.delivery) == ("failed", "test:failed", None)
    assert row.released_at is not None and b.reservations() == [] and b.origin_main() == main and b.repo.pushes == 0


def test_a_conflict_is_refused_with_its_paths_and_nothing_recorded(b: LandBench) -> None:
    main = b.advance({"src/x.py": "X = 2\n"})
    found = b.land()
    assert failed(found) == ("refused", "conflict") and isinstance(found, Failed) and "src/x.py" in found.detail
    nothing_changed(b, main)


def test_main_already_holding_x_s_changes_is_no_change_until_accepted(b: LandBench) -> None:
    main = b.advance({"src/x.py": "X = 1\n"}, "a hand land")
    assert failed(b.land()) == ("refused", "no_change")
    nothing_changed(b, main)
    b.repo.worktree(b.repo.path).checkout("task/tl-1")
    b.repo.worktree(b.repo.path).write_file("later.txt", "after X\n")
    b.repo.worktree(b.repo.path).record("after the check", paths="all")
    b.repo.worktree(b.repo.path).checkout("main")
    found = b.land(no_change=True)  # whatever the task branch holds
    assert isinstance(found, Landed) and found.how == "no_change" and found.row.delivery == "no_change"
    assert found.row.slot is None and b.origin_main() == main and b.repo.pushes == 0


def test_no_change_with_something_to_land_is_refused_changes(b: LandBench) -> None:
    assert failed(b.land(no_change=True)) == ("refused", "changes")
    nothing_changed(b, b.base)


def _profile_at_main(b: LandBench, profile: object) -> None:
    b.advance({".task-loop.json": json.dumps(profile)}, "the target's profile")


REFUSALS: list[tuple[str, Callable[[LandBench], object], tuple[str, str]]] = [
    ("minutes", lambda b: None, ("refused", "choices")),
    ("push_barred", lambda b: b.environ.update(BAR), ("refused", "push_barred")),
    ("not_done", lambda b: b.con.execute("DELETE FROM published_branch"), ("refused", "not_done")),
    ("not_checked", lambda b: b.con.execute("UPDATE checks_attempt SET conclusion='failed',reason='test:failed'"),
     ("refused", "not_checked")),
    ("unreleased", lambda b: b.con.execute("UPDATE checks_attempt SET released_at=NULL,parked=NULL"), ("refused", "not_checked")),
    ("abandoned", lambda b: b.con.execute("UPDATE checks_attempt SET abandoned=1"), ("refused", "not_checked")),
    ("offline", lambda b: setattr(b.remote, "offline", True), ("unavailable", "remote")),
    ("target", lambda b: b.remote.state.refs.pop("refs/heads/main"), ("refused", "target")),
    ("branch_moved_local", lambda b: _moved_branch(b, push=False), ("refused", "branch_moved")),
    ("branch_moved_origin", lambda b: _moved_branch(b, push=True), ("refused", "branch_moved")),
    ("claim_lost", lambda b: setattr(b, "assignee", "someone"), ("refused", "claim_lost")),
    ("closed", lambda b: setattr(b, "status", "closed"), ("refused", "closed")),
    ("target_profile", lambda b: b.advance({".task-loop.json": "{"}), ("refused", "target_profile")),
    ("target_branch", lambda b: _profile_at_main(b, {"target": "trunk", "required": ["check"], "checks": [
        {"name": "check", "argv": ["just", "check"], "timeout": 60}]}), ("refused", "target")),
    ("no_required", lambda b: _profile_at_main(b, {"required": [], "checks": []}), ("refused", "no_required")),
]


def _moved_branch(b: LandBench, *, push: bool) -> None:
    """`task/tl-1` holds a commit after the checked X: on origin only when `push`, else in the person's clone only."""
    if push:
        b.remote.advance("task/tl-1", {"later.txt": "after X\n"})
        return
    root = b.repo.worktree(b.repo.path)
    root.checkout("task/tl-1")
    root.write_file("later.txt", "after X\n")
    root.record("after the check", paths="all")
    root.checkout("main")


@pytest.mark.parametrize(("arrange", "word"), [(each[1], each[2]) for each in REFUSALS], ids=[each[0] for each in REFUSALS])
def test_each_refusal_comes_before_anything_is_written(b: LandBench, arrange: Callable[[LandBench], object],
                                                       word: tuple[str, str]) -> None:
    arrange(b)
    main = b.remote.branches().get("main")
    found = b.land(minutes=0 if word == ("refused", "choices") else 5)
    assert failed(found) == word
    assert b.rows() == () and b.reservations() == [] and b.repo.pushes == 0 and b.remote.branches().get("main") == main
    assert b.execs() == []


def test_a_checkout_of_another_repository_is_refused(b: LandBench) -> None:
    b.con.execute("UPDATE attempt SET repo_id='another' WHERE attempt_id='implement'")
    assert failed(b.land()) == ("refused", "checkout") and b.rows() == ()


def test_failed_checks_are_refused_before_any_remote_read(b: LandBench) -> None:
    """Section 4's order: the checks attempt is read before Git (an unreachable origin is never asked), not only fenced at
    the insert."""
    b.con.execute("UPDATE checks_attempt SET conclusion='failed',reason='test:failed'")
    b.remote.offline = True
    assert failed(b.land()) == ("refused", "not_checked")
