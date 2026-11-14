"""Leftover observations after the agent changes Git references."""

import sqlite3
from pathlib import Path

from doubles import FakeSlotFiles
from git_porcelain import Recorded
from git_porcelain.testing import FakeWorktree
from test_verifier import KEY, PLANNED, captured, head, trailer_commit, verifier

from taskloop.attempt_types import Checkouts, Unsettled, Verified


def test_leftovers_read_the_adopt_rule_commit_as_none_and_a_slot_left_detached_as_branch(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: FakeSlotFiles
) -> None:
    captured(registered, tmp_path, slot, checkouts, slot_files, PLANNED)
    check = verifier(registered, checkouts, slot_files)
    trailer_commit(slot, slot_files)
    assert check.leftovers(KEY) is None and isinstance(check.verify(KEY), Verified)


def test_a_slot_left_detached_by_the_agent_is_branch_in_the_leftovers(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: FakeSlotFiles
) -> None:
    captured(registered, tmp_path, slot, checkouts, slot_files, PLANNED)
    slot.park(head(slot))  # detached: not on the task branch
    assert verifier(registered, checkouts, slot_files).leftovers(KEY) == Unsettled("branch")


def test_a_head_reset_to_the_persons_main_never_lists_main_but_still_lists_an_agent_tag(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: FakeSlotFiles
) -> None:
    captured(registered, tmp_path, slot, checkouts, slot_files, PLANNED)
    main = slot.repo.worktree(slot.repo.identity().root)
    main.write_file("person.txt", "mine")
    made = main.record("the person's commit", paths="all")
    assert isinstance(made, Recorded)
    slot.reset(made.sha, mode="hard")  # the agent: `git reset --hard main`
    slot.repo.tag("task/evil", made.sha)
    result = verifier(registered, checkouts, slot_files).verify(KEY)
    assert result == Unsettled("head_moved", ("refs/tags/task/evil",)) or result == Unsettled("head_moved", ())
    assert isinstance(result, Unsettled) and "refs/heads/main" not in result.listing
