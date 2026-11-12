"""The round applies holds (tl-8bh9.14.9 section 9, H3) over the rounds bench (`round_bench`: real factory.db,
admission, verify, release, publish and the hold operation; the Git fake; scripted agents; a semantic tracker with the
hold's label, comment and clear writes): a round-taken task that stopped is held once and then costs nothing, a pending
hold is written once per refusal, a hold never stops another task or ingestion, the person's answer (the label back)
takes the task again at plan on its branch only under the label it was taken under, `held` is removed after that, and a
task started by hand is never held."""

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from doubles import PinnedViews
from git_porcelain import Sha
from git_porcelain.testing import FakeWorktree
from round_bench import Factory, Tracker, scripted, scripts, task

from taskloop.attempt_types import SlotFiles
from taskloop.launch import LaunchUnavailable
from taskloop.operations import Failed, Round, Started, StartRequest, start
from taskloop.round import NextRequest, run_round

AFTER_DEADLINE = 31 * 60  # past an attempt's deadline: the rounds' --minutes is 30
ASKED = "Which widget shape do you want?"


@pytest.fixture
def factory(factory: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: PinnedViews, slot_files: SlotFiles) -> Factory:
    built = Factory(factory, tmp_path, slot, checkouts, slot_files, Tracker(task("tl-1")))
    scripts(built, slot, "tl-1", "tl-2", "tl-3")
    return built


def asks(factory: Factory, task_id: str, step: str) -> None:
    """The task's agent of `step` answers `needs_owner` and changes nothing."""
    plan = {"plan_path": None} if step == "plan" else {}
    factory.agents[task_id, step] = scripted(
        factory.slot.repo, {"disposition": "needs_owner", **plan, "paths": [], "message": None, "explanation": ASKED}, {})


def ready(factory: Factory, task_id: str) -> None:
    factory.tracker.beads[task_id] = task(task_id)


def labels(factory: Factory, task_id: str) -> list[object]:
    return [row[0] for row in factory.con.execute("SELECT label FROM attempt WHERE task_id=? ORDER BY seq", (task_id,))]


def moved(factory: Factory) -> None:
    """The person points the local task/tl-1 back at main: it no longer contains the step's commit."""
    factory.slot.repo.delete_branch("task/tl-1", expected=Sha(factory.tip("tl-1")))
    factory.slot.repo.add_worktree(factory.root / "elsewhere", "HEAD").checkout_new("task/tl-1")
    factory.slot.repo.drop_worktree(factory.root / "elsewhere")


def held_plan(factory: Factory) -> str:
    """tl-1 taken by a round, its plan answered `needs_owner` (collected, unreleased: `Next: release`) and held by the
    next round; the held attempt's id."""
    asks(factory, "tl-1", "plan")
    assert factory.round(frozenset()) == [("tl-1", "plan", "start", "started")]
    attempt = factory.current("tl-1")
    assert factory.round(factory.last.written) == [("tl-1", "plan", "hold", "held failed:needs_owner")]
    return attempt


def test_a_failed_task_is_held_once_then_costs_no_tracker_call_or_line(factory: Factory) -> None:
    attempt = held_plan(factory)
    bead = factory.tracker.beads["tl-1"]
    assert (bead.status, bead.assignee, bead.labels) == ("open", "", ("held",))
    assert factory.tracker.holds == ["labels tl-1 auto", "comment tl-1"]
    text = factory.tracker.comments[0][1]
    assert text.startswith("taskloop hold: failed:needs_owner\nStep plan, attempt 1") and f"> {ASKED}" in text
    assert "returned its claim" in text and "`bd label add tl-1 auto`" in text
    assert [line.split(" ")[2:] for line in factory.lines if " hold " in line] == [["tl-1", "plan", "hold", "held", "failed:needs_owner",
                                                                                     attempt]]
    assert factory.next_words() == {"tl-1": ("plan", "on_hold")}
    lines, shows, reads = len(factory.lines), len(factory.tracker.shows), factory.tracker.ready_reads
    for _ in range(2):
        assert factory.round(factory.last.written) == []
    assert factory.tracker.holds == ["labels tl-1 auto", "comment tl-1"] and len(factory.tracker.shows) == shows
    assert len(factory.lines) == lines + 1  # the closing line `moves=0` once, then quiet
    assert factory.tracker.ready_reads == reads + 2  # the ready read lists nothing: tl-1 lost its label


def test_a_held_task_never_stops_another_task_or_ingestion_through_one_slot(factory: Factory) -> None:
    """Section 9: per-task hold words never stop admission; with one slot the order is unchanged (claimed work first)."""
    asks(factory, "tl-1", "plan")
    ready(factory, "tl-2")
    assert factory.round() == [("tl-1", "plan", "start", "started")] and factory.last.stopped == "no_free_slot"
    assert factory.round() == [("tl-1", "plan", "hold", "held failed:needs_owner"), ("tl-2", "plan", "start", "started")]
    ready(factory, "tl-3")
    assert factory.round() == [("tl-2", "plan", "verify", "verified release=released branch=published"),
                               ("tl-3", "plan", "start", "started")]
    assert factory.round() == [("tl-3", "plan", "verify", "verified release=released branch=published"),
                               ("tl-2", "implement", "advance", "started")]  # claimed work before new work, as built
    assert factory.next_words() == {"tl-1": ("plan", "on_hold"), "tl-2": ("implement", "verify"), "tl-3": ("plan", "advance")}
    assert factory.tracker.claims == ["tl-1", "tl-2", "tl-3"] and factory.tracker.holds == ["labels tl-1 auto", "comment tl-1"]


def test_the_round_s_label_is_stored_on_its_admissions_and_advances_and_none_on_a_start_by_hand(factory: Factory) -> None:
    factory.adopt("s2")
    factory.tracker.beads["tl-1"] = replace(task("tl-1"), labels=("auto", "night"))
    assert factory.round(label="night") == [("tl-1", "plan", "start", "started")]  # tl-2 is not ready yet
    ready(factory, "tl-2")
    factory.by_hand("tl-2")
    assert factory.round(label="night") == [("tl-1", "plan", "verify", "verified release=released branch=published"),
                                            ("tl-2", "implement", "advance", "started")]
    assert factory.round(label="night")[1] == ("tl-1", "implement", "advance", "started")
    assert labels(factory, "tl-1") == ["night", "night"] and labels(factory, "tl-2") == [None, None]


def test_a_task_started_by_hand_that_fails_is_reported_never_held(factory: Factory) -> None:
    asks(factory, "tl-1", "plan")
    factory.by_hand("tl-1")
    assert factory.round(frozenset()) == [("tl-1", "plan", "report", "release")]
    assert factory.round(factory.last.written) == [("tl-1", "plan", "report", "release")] and len(factory.lines) == 2
    assert factory.tracker.holds == [] and factory.tracker.beads["tl-1"].assignee == "taskloop"
    assert factory.next_words() == {"tl-1": ("plan", "release")} and labels(factory, "tl-1") == [None]


def test_a_bd_outage_mid_hold_is_pending_written_once_per_refusal_and_the_claim_returned_before_the_comment(factory: Factory) -> None:
    asks(factory, "tl-1", "plan")
    assert factory.round(frozenset()) == [("tl-1", "plan", "start", "started")]
    attempt = factory.current("tl-1")
    factory.tracker.down = {"labels"}
    pending = ("tl-1", "plan", "hold", "pending labels unavailable:tracker")
    assert factory.round(factory.last.written) == [pending] and factory.round(factory.last.written) == [pending]
    line = ["tl-1", "plan", "hold", "pending", "labels", "unavailable:tracker", attempt]
    assert [each.split(" ")[2:] for each in factory.lines].count(line) == 1  # quiet while unchanged
    assert factory.next_words() == {"tl-1": ("plan", "hold")} and factory.tracker.beads["tl-1"].assignee == "taskloop"
    factory.tracker.down = {"comment"}  # the refusal changes: written again
    assert factory.round(factory.last.written) == [("tl-1", "plan", "hold", "pending comment unavailable:tracker")]
    assert sum(" pending comment unavailable:tracker " in each for each in factory.lines) == 1
    assert factory.tracker.beads["tl-1"].assignee == "" and factory.tracker.comments == []  # abandoned: the claim returned
    factory.tracker.down = set()
    factory.now += 120  # the lease of the failed comment call lapsed
    assert factory.round(factory.last.written) == [("tl-1", "plan", "hold", "held failed:needs_owner")]
    assert factory.tracker.holds == ["labels tl-1 auto"] * 3 + ["comment tl-1"] * 2 and len(factory.tracker.comments) == 1
    assert factory.round(factory.last.written) == []


def test_a_hold_refused_by_a_dirty_slot_stays_pending_while_the_round_goes_on(factory: Factory) -> None:
    """An admitted attempt that never started is `stuck:expired_admitted` past its deadline; the person left a file in
    its slot, so the hold's abandon is `held:slot_dirty`: one line, one comment naming the slot, the claim kept; another
    slot's task still starts; once the file is gone the next round finishes the hold."""
    factory.adopt("s2")
    factory.failing = LaunchUnavailable("start")
    assert factory.round() == [("tl-1", "", "start", "unavailable:start")]
    factory.now += AFTER_DEADLINE
    factory.slot.write_file("notes.txt", "mine\n")
    ready(factory, "tl-2")
    dirty = ("tl-1", "plan", "hold", "pending abandon held:slot_dirty")
    assert factory.round(frozenset()) == [dirty, ("tl-2", "plan", "start", "started")] and factory.last.stopped == ""
    assert factory.round(factory.last.written)[0] == dirty
    assert sum(" pending abandon held:slot_dirty " in each for each in factory.lines) == 1
    assert factory.tracker.holds == ["labels tl-1 auto", "comment tl-1"] and factory.tracker.beads["tl-1"].assignee == "taskloop"
    assert f"slot {factory.slot.path} has files left" in factory.tracker.comments[0][1]
    factory.slot.remove_file("notes.txt")
    assert factory.round(factory.last.written)[0] == ("tl-1", "plan", "hold", "held stuck:expired_admitted")
    assert factory.tracker.holds == ["labels tl-1 auto", "comment tl-1"] and factory.tracker.beads["tl-1"].assignee == ""


def test_an_advance_refused_claim_lost_holds_a_round_taken_task_without_touching_another_actor_s_labels(factory: Factory) -> None:
    assert factory.round() == [("tl-1", "plan", "start", "started")]
    assert factory.round() == [("tl-1", "plan", "verify", "verified release=released branch=published")]
    factory.tracker.beads["tl-1"] = replace(factory.tracker.beads["tl-1"], assignee="someone")
    assert factory.round() == [("tl-1", "plan", "hold", "held claim_lost")]
    bead = factory.tracker.beads["tl-1"]
    assert (bead.assignee, bead.labels) == ("someone", ("auto",)) and factory.tracker.holds == ["labels tl-1 auto", "comment tl-1"]
    assert "changed no label" in factory.tracker.comments[0][1] and factory.round() == []
    assert factory.con.execute("SELECT claim FROM slot_release").fetchall() == [("not_held",)]


def test_the_person_s_answer_takes_the_task_again_at_plan_on_its_branch_and_held_is_removed(factory: Factory) -> None:
    """A failed implement is held; the person adds `auto` back: the next round admits a fresh plan attempt (next seq,
    label stored) on task/tl-1 as it is (the plan commit kept) and removes `held` (`hold cleared`), once."""
    assert factory.round() == [("tl-1", "plan", "start", "started")]
    assert factory.round() == [("tl-1", "plan", "verify", "verified release=released branch=published")]
    planned = factory.tip("tl-1")
    asks(factory, "tl-1", "implement")
    assert factory.round() == [("tl-1", "implement", "advance", "started")]
    held = factory.current("tl-1")
    assert factory.round() == [("tl-1", "implement", "hold", "held failed:needs_owner")]
    assert factory.round() == [] and factory.tracker.beads["tl-1"].labels == ("held",)
    factory.tracker.answer("tl-1")
    unchanged = {"disposition": "unchanged", "plan_path": "docs/design/tl-1/plan.md", "paths": [], "message": None,
                 "explanation": "The plan still holds"}
    factory.agents["tl-1", "plan"] = scripted(factory.slot.repo, unchanged, {})
    assert factory.round(frozenset()) == [("tl-1", "plan", "start", "started"), ("tl-1", "", "hold", "cleared")]
    assert factory.last.moves[-1].attempt_id == held and factory.tracker.beads["tl-1"].labels == ("auto",)
    again = factory.current("tl-1")
    row = factory.con.execute("SELECT seq,step,label,base_commit FROM attempt WHERE attempt_id=?", (again,)).fetchone()
    assert row == (3, "plan", "auto", planned) and factory.tracker.claims == ["tl-1", "tl-1"]
    assert factory.round(factory.last.written) == [("tl-1", "plan", "verify", "reused release=released branch=published")]
    assert factory.tracker.holds == ["labels tl-1 auto", "comment tl-1", "clear tl-1"]  # cleared once


def test_a_round_under_another_label_skips_a_held_task_even_when_it_carries_that_label(factory: Factory) -> None:
    factory.tracker.beads["tl-1"] = replace(task("tl-1"), labels=("auto", "night"))
    held_plan(factory)
    assert factory.tracker.beads["tl-1"].labels == ("night", "held")  # the label it was taken under is gone, `night` kept
    assert factory.round(frozenset(), label="night") == [("tl-1", "plan", "skip", "abandoned")]
    assert factory.round(factory.last.written, label="night") == [("tl-1", "plan", "skip", "abandoned")]
    assert len(factory.tracker.claims) == 1 and factory.tracker.holds == ["labels tl-1 auto", "comment tl-1"]
    factory.tracker.answer("tl-1")
    assert factory.round(label="auto")[0] == ("tl-1", "plan", "start", "started")


def test_a_task_whose_label_was_already_gone_is_held_absent_and_taken_again_when_the_label_comes_back(factory: Factory) -> None:
    asks(factory, "tl-1", "plan")
    assert factory.round() == [("tl-1", "plan", "start", "started")]
    factory.tracker.beads["tl-1"] = replace(factory.tracker.beads["tl-1"], labels=())  # the person removed it meanwhile
    assert factory.round() == [("tl-1", "plan", "hold", "held failed:needs_owner")]
    assert factory.con.execute("SELECT labels FROM task_hold").fetchall() == [("absent",)]
    factory.tracker.answer("tl-1")
    assert factory.round()[:2] == [("tl-1", "plan", "start", "started"), ("tl-1", "", "hold", "cleared")]


def test_an_advance_refused_branch_moved_is_held_once_instead_of_retried(factory: Factory) -> None:
    assert factory.round() == [("tl-1", "plan", "start", "started")]
    assert factory.round() == [("tl-1", "plan", "verify", "verified release=released branch=published")]
    moved(factory)
    assert factory.round() == [("tl-1", "plan", "hold", "held branch_moved")] and factory.round() == []
    assert "Restore task/tl-1 to contain" in factory.tracker.comments[0][1]
    assert factory.con.execute("SELECT count(*) FROM attempt WHERE step='implement'").fetchone() == (0,)


def test_a_task_held_again_after_its_answer_owns_held_and_the_old_hold_is_cleared_with_no_tracker_call(factory: Factory) -> None:
    first = held_plan(factory)
    factory.tracker.answer("tl-1")
    factory.tracker.down = {"clear"}
    assert factory.round(frozenset()) == [("tl-1", "plan", "start", "started"), ("tl-1", "", "hold", "clearing unavailable:tracker")]
    factory.tracker.down = set()
    assert factory.round() == [("tl-1", "plan", "hold", "held failed:needs_owner"), ("tl-1", "", "hold", "cleared")]
    assert factory.last.moves[1].attempt_id == first and factory.tracker.beads["tl-1"].labels == ("held",)
    assert factory.tracker.holds == ["labels tl-1 auto", "comment tl-1", "clear tl-1", "labels tl-1 auto", "comment tl-1"]


def test_a_hold_whose_label_step_never_ran_is_superseded_and_held_removed_once_the_task_is_restarted_by_hand(factory: Factory) -> None:
    asks(factory, "tl-1", "plan")
    factory.round()
    factory.tracker.down = {"labels"}
    held = factory.current("tl-1")
    assert factory.round() == [("tl-1", "plan", "hold", "pending labels unavailable:tracker")]
    found = factory.store.attempt_of("tasks", "tl-1")
    assert found is not None and factory.releaser().release(found[0], True)  # the person's abandon, then a start by hand
    factory.by_hand("tl-1")
    assert factory.round() == [("tl-1", "plan", "report", "release"), ("tl-1", "", "hold", "cleared")]
    assert factory.con.execute("SELECT attempt_id,labels FROM task_hold").fetchall() == [(held, "superseded")]
    assert factory.tracker.holds[-1] == "clear tl-1" and factory.round() == [("tl-1", "plan", "report", "release")]


def test_a_person_s_own_abandon_keeps_the_abandoned_skip(factory: Factory) -> None:
    assert factory.round() == [("tl-1", "plan", "start", "started")]
    factory.round()
    found = factory.store.attempt_of("tasks", "tl-1")
    assert found is not None and factory.releaser().release(found[0], True)  # the person's `tl step release --abandon`
    assert factory.round() == [("tl-1", "plan", "skip", "abandoned")] and factory.tracker.holds == []


def test_a_publication_refused_branch_moved_is_held_once_instead_of_pushed_every_round(factory: Factory) -> None:
    assert factory.round() == [("tl-1", "plan", "start", "started")]
    factory.slot.repo.set_remote_url("origin", "/nowhere")
    assert factory.round() == [("tl-1", "plan", "verify", "verified release=released branch=unavailable:remote")]
    assert factory.next_words() == {"tl-1": ("plan", "publish")}
    moved(factory)
    assert factory.round() == [("tl-1", "plan", "hold", "held branch_moved")] and factory.round() == []
    assert factory.next_words() == {"tl-1": ("plan", "on_hold")} and factory.tracker.beads["tl-1"].labels == ("held",)


def test_a_pending_hold_refuses_the_person_s_relaunch_of_the_attempt_it_will_abandon(factory: Factory) -> None:
    """`stuck:expired_admitted` held while bd is down: `tl step start` would relaunch A, which the hold then abandons;
    it is refused `held` (nothing launched) until the round finishes the hold or the person abandons."""
    factory.failing = LaunchUnavailable("start")
    factory.round()
    factory.now += AFTER_DEADLINE
    factory.tracker.down = {"labels"}
    assert factory.round() == [("tl-1", "plan", "hold", "pending labels unavailable:tracker")]
    ran = list(factory.ran)
    found = start(factory.starting(), StartRequest("tl-1", "tasks", "/tracker", factory.slot.repo.path, "m", "high", 30))
    assert isinstance(found, Failed) and found.word == "refused:held" and factory.ran == ran
    factory.tracker.down = set()
    assert factory.round() == [("tl-1", "plan", "hold", "held stuck:expired_admitted")]
    found = start(factory.starting(), StartRequest("tl-1", "tasks", "/tracker", factory.slot.repo.path, "m", "high", 30))
    assert isinstance(found, Started) and found.status == "started"  # finished: the person may start it afresh


def test_a_hand_started_publication_refused_branch_moved_is_reported_never_held(factory: Factory) -> None:
    factory.slot.repo.set_remote_url("origin", "/nowhere")
    factory.by_hand("tl-1")
    moved(factory)
    assert factory.round(frozenset()) == [("tl-1", "plan", "publish", "refused:branch_moved")]
    assert factory.tracker.holds == [] and any(line.endswith(" publish refused:branch_moved " + factory.current("tl-1"))
                                               for line in factory.lines)


def test_a_graceful_stop_skips_the_clear_and_the_next_round_does_it(factory: Factory) -> None:
    held_plan(factory)
    factory.tracker.answer("tl-1")
    scripts(factory, factory.slot, "tl-1")
    factory.now += 1
    request = NextRequest("tasks", "/tracker", factory.slot.repo.path, "auto", "m", "high", 30)
    found = run_round(replace(factory.ports(), stopping=lambda: len(factory.tracker.claims) > 1), request)
    assert isinstance(found, Round) and [each.action for each in found.moves] == ["start"] and found.stopped == "interrupted"
    assert factory.tracker.beads["tl-1"].labels == ("held", "auto")  # `held` still there
    assert ("tl-1", "", "hold", "cleared") in factory.round()
