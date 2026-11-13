"""The round advances a claimed task from plan to implement (S5c), end to end over real SQLite, real admission, verify,
release and publish, the semantic Git fake with its fake remote, a scripted agent run at once by the launch port (as the
registered entry would run it), the fake slot setup and a tracker double (`round_bench`): plan, advance, implement,
`Next: advance` (to the check step, whose admission is a double here)."""

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from doubles import Command, PinnedViews
from git_porcelain.testing import FakeWorktree
from round_bench import Factory, Tracker, scripts, task

from taskloop.attempt_status import Listed, StatusPorts, list_attempts
from taskloop.attempt_types import SlotFiles
from taskloop.launch import LaunchUnavailable


@pytest.fixture
def factory(factory: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: PinnedViews, slot_files: SlotFiles) -> Factory:
    built = Factory(factory, tmp_path, slot, checkouts, slot_files, Tracker(task("tl-1"), task("tl-2")))
    scripts(built, slot, "tl-1", "tl-2")
    return built


def test_rounds_plan_advance_and_implement_a_task_to_its_check_step_without_a_second_claim_or_the_label(factory: Factory) -> None:
    factory.tracker.beads.pop("tl-2")
    assert factory.round() == [("tl-1", "plan", "start", "started")]
    assert factory.round() == [("tl-1", "plan", "verify", "verified release=released branch=published")]
    planned = factory.tip("tl-1")
    assert factory.next_words() == {"tl-1": ("plan", "advance")}
    factory.tracker.beads["tl-1"] = replace(factory.tracker.beads["tl-1"], labels=())  # removed after the claim: no effect
    advanced = factory.round()
    assert advanced == [("tl-1", "implement", "advance", "started")] and factory.last.stopped == "no_free_slot"
    assert factory.round() == [("tl-1", "implement", "verify", "verified release=released branch=published")]
    # the check step is next: this `main` requires no check, so the done implement attempt is skipped (S6d)
    assert factory.round() == [("tl-1", "implement", "skip", "no_required")]
    assert factory.next_words() == {"tl-1": ("implement", "advance")}
    x = factory.tip("tl-1")
    tree = factory.slot.repo.tree(x)
    assert tree is not None and {"src/tl-1.py", "tests/test_tl-1.py", "docs/design/tl-1/plan.md"} <= set(tree.files)
    assert [each.sha for each in factory.slot.repo.history([x], not_on=[planned])] == [x]  # one implement commit on the plan
    assert factory.tracker.claims == ["tl-1"]
    implement = factory.current("tl-1")
    words = [line.split(" ")[2:] for line in factory.lines]
    assert ["tl-1", "implement", "advance", "started", implement] in words
    assert ["round", "moves=1", "stopped=no_free_slot"] in words



def test_two_done_tasks_and_one_slot_advance_oldest_release_first_and_new_work_waits(factory: Factory) -> None:
    factory.by_hand("tl-2")  # released first
    factory.by_hand("tl-1")
    factory.tracker.beads["tl-3"] = task("tl-3")  # a new ready task: claimed work goes first
    scripts(factory, factory.slot, "tl-3")
    reads, shows = factory.tracker.ready_reads, len(factory.tracker.shows)
    assert factory.round() == [("tl-2", "implement", "advance", "started")] and factory.last.stopped == "no_free_slot"
    assert factory.tracker.ready_reads == reads and factory.tracker.claims == ["tl-2", "tl-1"]  # no ready read, no claim
    assert factory.tracker.shows[shows:] == ["tl-2"]  # tl-1 found no free slot before any tracker read
    assert factory.round() == [("tl-2", "implement", "verify", "verified release=released branch=published"),
                               ("tl-1", "implement", "advance", "started")]
    assert factory.round() == [("tl-1", "implement", "verify", "verified release=released branch=published"),
                               ("tl-2", "implement", "skip", "no_required"), ("tl-3", "plan", "start", "started")]
    assert factory.next_words() == {"tl-1": ("implement", "advance"), "tl-2": ("implement", "advance"), "tl-3": ("plan", "verify")}


def test_a_task_a_person_abandoned_is_restarted_by_a_round_while_it_carries_the_label(factory: Factory) -> None:
    factory.by_hand("tl-1")
    found = factory.store.attempt_of("tasks", "tl-1")
    assert found is not None and factory.releaser().release(found[0], True)  # the person's `tl step release --abandon`
    assert factory.round() == [("tl-1", "plan", "start", "started")]  # the restart takes the one free slot first
    assert factory.current("tl-1") != found[0].attempt_id  # a fresh attempt: the one restart route, no `tl step start`


def test_an_abandon_after_the_rounds_read_is_restarted_by_the_round_that_sees_the_label(factory: Factory) -> None:
    factory.tracker.beads.pop("tl-2")
    factory.by_hand("tl-1")
    found = factory.store.attempt_of("tasks", "tl-1")
    assert found is not None
    factory.during = lambda: factory.releaser().release(found[0], True)
    assert factory.round() == [("tl-1", "plan", "skip", "abandoned"), ("tl-1", "plan", "skip", "attempted")]  # the snapshot predates it
    assert factory.current("tl-1") == found[0].attempt_id
    assert factory.round() == [("tl-1", "plan", "start", "started")]  # the next snapshot sees the abandon and the label
    assert factory.current("tl-1") != found[0].attempt_id


def test_a_claim_lost_between_steps_is_skipped_and_written_once(factory: Factory) -> None:
    factory.tracker.beads.pop("tl-2")
    factory.by_hand("tl-1")
    factory.tracker.beads["tl-1"] = replace(factory.tracker.beads["tl-1"], status="in_progress", assignee="someone")
    first = factory.round(frozenset())
    assert first == [("tl-1", "plan", "skip", "claim_lost")] and factory.last.stopped == ""
    written = len(factory.lines)
    assert factory.round(factory.last.written) == first and len(factory.lines) == written  # tried each round, logged once
    assert factory.con.execute("SELECT count(*) FROM attempt WHERE step='implement'").fetchone() == (0,)


def test_a_restart_after_the_advance_was_admitted_but_never_launched_continues_it(factory: Factory) -> None:
    """The rounds process stops after the next step's admission, before its entry runs; a restart over the intact
    factory.db relaunches that attempt (never a second advance) and finishes it."""
    factory.tracker.beads.pop("tl-2")
    factory.by_hand("tl-1")
    factory.failing = LaunchUnavailable("start")
    assert factory.round() == [("tl-1", "plan", "advance", "unavailable:start")] and factory.last.stopped == "unavailable:start"
    assert factory.next_words() == {"tl-1": ("implement", "start")}
    assert factory.round() == [("tl-1", "implement", "relaunch", "relaunched")]
    assert factory.round() == [("tl-1", "implement", "verify", "verified release=released branch=published")]
    assert factory.next_words() == {"tl-1": ("implement", "advance")}
    assert factory.con.execute("SELECT count(*) FROM attempt WHERE step='implement'").fetchone() == (1,)


def test_a_setup_failing_twice_after_the_advance_is_stuck_and_never_relaunched_again(factory: Factory) -> None:
    """The advance's entry runs setup once, the next round's relaunch once more: two failed runs make the attempt
    `stuck:setup_failed`, which rounds report (written once) and never relaunch."""
    factory.tracker.beads.pop("tl-2")
    factory.by_hand("tl-1")
    factory.environment.process.script = [Command(rc=1), Command(rc=1)]
    assert factory.round(frozenset()) == [("tl-1", "implement", "advance", "started")]
    implement = factory.current("tl-1")
    assert factory.round(factory.last.written) == [("tl-1", "implement", "relaunch", "relaunched")]
    assert factory.round(factory.last.written) == [("tl-1", "implement", "report", "stuck:setup_failed")]
    written = len(factory.lines)
    assert factory.round(factory.last.written) == [("tl-1", "implement", "report", "stuck:setup_failed")]
    assert len(factory.lines) == written and len(factory.environment.process.calls) == 2
    assert factory.ran[-2:] == ["unavailable:environment:exit"] * 2  # no third entry: nothing relaunched
    assert factory.next_words() == {"tl-1": ("implement", "stuck:setup_failed")} and factory.current("tl-1") == implement
    listed = list_attempts(StatusPorts(factory.store, lambda _entry: "gone", lambda: factory.now, lambda _key: None, lambda: "boot"),
                           stuck=True)
    assert isinstance(listed, Listed) and [each.next for each in listed.attempts] == ["stuck:setup_failed"]


def test_a_claimed_task_the_tracker_lost_is_skipped_and_the_next_advance_and_new_work_proceed(factory: Factory) -> None:
    """One claimed task's own refusal (`task`: deleted from its tracker) never stops the round: the next done task
    advances and a new ready task starts, every round."""
    factory.adopt("s2")
    factory.by_hand("tl-1")  # released first: tried first
    factory.by_hand("tl-2")
    factory.tracker.beads.pop("tl-1")
    factory.tracker.beads["tl-3"] = task("tl-3")
    scripts(factory, factory.slot, "tl-3")
    assert factory.round() == [("tl-1", "plan", "skip", "task_missing"), ("tl-2", "implement", "advance", "started"),
                               ("tl-3", "plan", "start", "started")]
    assert factory.last.stopped == ""
    assert ("tl-1", "plan", "skip", "task_missing") in factory.round() and factory.last.stopped == ""
    assert factory.con.execute("SELECT count(*) FROM attempt WHERE task_id='tl-1' AND step='implement'").fetchone() == (0,)


@pytest.mark.parametrize("words", ['resolving tl-1: no issue found matching "tl-1"', "no issues found matching the provided IDs"])
def test_a_task_deleted_at_its_next_advance_is_skipped_task_missing_in_either_of_bd_s_words(factory: Factory, words: str) -> None:
    """tl-8bh9.14.65: `bd show` answers a deleted task with an error whose words differ by command; neither stops the round."""
    factory.adopt("s2")
    factory.by_hand("tl-1")
    factory.by_hand("tl-2")
    factory.tracker.beads.pop("tl-1")
    factory.tracker.deleted_as = words
    assert factory.round() == [("tl-1", "plan", "skip", "task_missing"), ("tl-2", "implement", "advance", "started")]
    assert factory.last.stopped == ""
