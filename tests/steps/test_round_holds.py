"""The round applies holds (tl-8bh9.14.9 section 9, H3) over the rounds bench (`round_bench`: real factory.db,
admission, verify, release, publish and the hold operation; the Git fake; scripted agents; a semantic tracker with the
hold's label, comment and clear writes): a round-taken task that stopped is held once and then costs nothing, a pending
hold is written once per refusal, a hold never stops another task or ingestion, the person's answer (the label back)
takes the task again at plan on its branch only under the label it was taken under, `held` is removed after that, and a
task started by hand is never held."""

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from doubles import PinnedViews
from git_porcelain import Sha
from git_porcelain.testing import FakeWorktree
from plan_fixtures import PLAN_TEXT
from round_bench import Factory, Tracker, scripted, scripts, task

from taskloop.agents.settings import Overrides, StepSettings
from taskloop.attempt_status import Shown, StatusPorts, show_attempt
from taskloop.attempt_types import SlotFiles
from taskloop.earlier_input import BEGIN, END, START
from taskloop.evidence_files import EvidenceFiles
from taskloop.hold_store import HoldStore
from taskloop.launch import LaunchUnavailable
from taskloop.operations import Failed, Round, StartRequest, start
from taskloop.round import NextRequest, run_round
from taskloop.step_render import human
from taskloop.step_text import SAVED_WORK
from taskloop.wip import SavedCommit

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
    assert "returned its claim" in text and "restore the approval label `auto`" in text
    assert [line.split(" ")[2:] for line in factory.lines if " hold " in line] == [["tl-1", "plan", "hold", "held", "failed:needs_owner",
                                                                                     attempt]]
    assert factory.next_words() == {"tl-1": ("plan", "on_hold")}
    lines, shows, reads = len(factory.lines), len(factory.tracker.shows), factory.tracker.ready_reads
    for _ in range(2):
        assert factory.round(factory.last.written) == []
    assert factory.tracker.holds == ["labels tl-1 auto", "comment tl-1"] and len(factory.tracker.shows) == shows
    assert len(factory.lines) == lines + 1  # the closing line `moves=0` once, then quiet
    assert factory.tracker.ready_reads == reads + 2  # the ready read lists nothing: tl-1 lost its label


@pytest.mark.parametrize("step", ["plan", "implement"])
def test_a_size_refusal_holds_the_parent_once_and_keeps_any_coherent_part_unfinished(factory: Factory, step: str) -> None:
    if step == "implement":
        assert factory.round() == [("tl-1", "plan", "start", "started")]
        assert factory.round() == [("tl-1", "plan", "verify", "verified release=released branch=published")]
    explanation = (
        "Scope exceeds 3 independent behaviours and needs about 80 implement model calls. "
        "Hold the parent for the owner or orchestrator to create these parts: "
        "Hand-start: acceptance: hand-start auto-land works; dependencies: none. "
        "Resolution: acceptance: conflicts resume safely; dependencies: Hand-start."
    )
    if step == "implement":
        explanation += " Completed: hand-start fix. Remaining: conflict-resolution flow."
    plan = {"plan_path": None} if step == "plan" else {}
    factory.agents["tl-1", step] = scripted(
        factory.slot.repo,
        {"disposition": "needs_owner", **plan, "paths": [], "message": None, "explanation": explanation},
        {"README": "coherent hand-start fix\n"} if step == "implement" else {},
    )
    assert factory.round() == [("tl-1", step, "start" if step == "plan" else "advance", "started")]
    attempt = factory.current("tl-1")
    assert factory.ran[-1] == "collected:needs_owner"
    assert factory.round() == [("tl-1", step, "hold", "held failed:needs_owner")]
    comment = factory.tracker.comments[0][1]
    assert f"> {explanation}" in comment and "taskloop hold: failed:needs_owner" in comment
    assert "tl step" not in comment and "bd " not in comment
    assert factory.tracker.beads["tl-1"].labels == ("held",)
    assert set(factory.tracker.beads) == {"tl-1"} and factory.tracker.claims == ["tl-1"]
    saved = HoldStore(lambda: factory.con).saved(attempt)
    if step == "implement":
        assert len(saved) == 1 and factory.tip("tl-1") == saved[0].sha
        history = factory.slot.repo.history([saved[0].sha], limit=1)
        assert f"Task-Loop-Wip: {attempt}" in history[0].body.splitlines()
        tree = factory.slot.repo.tree(saved[0].sha)
        assert tree is not None and tree.read("README") == b"coherent hand-start fix\n"
        assert tree.read("docs/design/tl-1/plan.md") == PLAN_TEXT.encode()
        assert "implementation is still incomplete" in comment and "no check ran on it" in comment
    else:
        assert saved == ()
    ran = list(factory.ran)
    holds = list(factory.tracker.holds)
    assert factory.round() == [] and factory.round() == []
    assert factory.ran == ran and factory.tracker.holds == holds == ["labels tl-1 auto", "comment tl-1"]
    assert factory.next_words() == {"tl-1": (step, "on_hold")}
    assert factory.con.execute("SELECT step FROM attempt ORDER BY seq").fetchall() == (
        [("plan",)] if step == "plan" else [("plan",), ("implement",)]
    )
    assert HoldStore(lambda: factory.con).saved(attempt) == saved


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


@pytest.mark.parametrize("step", ["plan", "implement"])
def test_show_of_a_hand_started_needs_owner_prints_the_agent_s_question_and_a_next_action_of_the_step(
        factory: Factory, step: str, tmp_path: Path) -> None:
    """tl-8bh9.14.66: nothing is held or commented for a hand-started step, so `tl step show` carries the explanation."""
    if step == "implement":
        factory.by_hand("tl-1")  # the plan; the next start advances to implement
    asks(factory, "tl-1", step)
    factory.by_hand("tl-1")
    reads = StatusPorts(factory.store, lambda _entry: "gone", lambda: factory.now, lambda _key: None, lambda: "boot")
    shown = show_attempt(reads, tmp_path, "tasks", "tl-1")
    assert isinstance(shown, Shown) and shown.view.result.reason == "needs_owner" and shown.view.step == step
    text = "\n".join(human("show", shown, tmp_path / "factory.db"))
    assert f"The agent explained:\n> {ASKED}" in text and "answered `needs_owner`" in text
    assert "`tl step release --abandon` and `tl step start`" in text and "check step" not in text
    assert factory.tracker.holds == []


def test_the_needs_owner_guide_is_not_repeated_once_the_attempt_is_abandoned(factory: Factory, tmp_path: Path) -> None:
    asks(factory, "tl-1", "plan")
    factory.by_hand("tl-1")
    found = factory.store.attempt_of("tasks", "tl-1")
    assert found is not None and factory.releaser().release(found[0], True)  # the person's `tl step release --abandon`
    reads = StatusPorts(factory.store, lambda _entry: "gone", lambda: factory.now, lambda _key: None, lambda: "boot")
    shown = show_attempt(reads, tmp_path, "tasks", "tl-1")
    assert isinstance(shown, Shown)
    text = "\n".join(human("show", shown, tmp_path / "factory.db"))
    assert "answered `needs_owner`" not in text and "approval label" in text


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


def test_a_hold_saves_a_dirty_slot_on_the_task_branch_and_releases_it(factory: Factory) -> None:
    """An admitted attempt that never started is `stuck:expired_admitted` past its deadline; the person left a file in
    its slot: the hold saves it as one commit on the task branch, names it, releases the slot clean and detached at D, and
    another task starts through the same slot, with nothing for a person to clean."""
    factory.adopt("s2")
    factory.failing = LaunchUnavailable("start")
    assert factory.round() == [("tl-1", "", "start", "unavailable:start")]
    factory.now += AFTER_DEADLINE
    factory.slot.write_file("notes.txt", "mine\n")
    assert factory.round(frozenset()) == [("tl-1", "plan", "hold", "held stuck:expired_admitted")]
    saved = _saved(factory)
    assert len(saved) == 1 and not factory.slot.dirty().raw
    assert dict(factory.slot.repo.branches("task/"))["task/tl-1"] == saved[0].sha
    assert not factory.slot.repo.worktree(factory.slot.path).dirty(ignored_under=["."]).ignored
    assert saved[0].sha in factory.tracker.comments[0][1]
    assert factory.tracker.holds == ["labels tl-1 auto", "comment tl-1"] and factory.tracker.beads["tl-1"].assignee == ""
    ready(factory, "tl-2")
    assert factory.round(factory.last.written)[0] == ("tl-2", "plan", "start", "started")


def _saved(factory: Factory) -> tuple[SavedCommit, ...]:
    attempt = str(factory.con.execute("SELECT attempt_id FROM attempt WHERE task_id='tl-1'").fetchone()[0])
    return HoldStore(lambda: factory.con).saved(attempt)


def test_a_hold_saves_edits_deletions_and_new_files_but_not_ignored_files(factory: Factory) -> None:
    """The saved commit holds the slot's final working state (a tracked edit, a deletion, a new file); a file Git's ignore
    rules hide stays out of it and on disk; a second round adds no commit and the slot serves another task."""
    factory.adopt("s2")
    factory.failing = LaunchUnavailable("start")
    assert factory.round() == [("tl-1", "", "start", "unavailable:start")]
    factory.now += AFTER_DEADLINE
    factory.slot.repo.exclude_locally(["*.log"])
    factory.slot.write_file("README", "edited\n")
    factory.slot.write_file("new/file.txt", "new\n")
    factory.slot.write_file("junk.log", "log\n")
    factory.round(frozenset())
    (saved,) = _saved(factory)
    files = factory.slot.repo.tree(saved.sha)
    assert files is not None and sorted(files.files) == [".task-loop.json", "README", "new/file.txt"]
    assert files.read("README") == b"edited\n"
    assert not factory.slot.dirty().raw and factory.slot.dirty(ignored_under=["."]).ignored == ("junk.log",)
    assert len(_saved(factory)) == 1 and len(dict(factory.slot.repo.branches("task/"))) == 1


def test_a_hold_of_a_clean_slot_saves_nothing(factory: Factory) -> None:
    """An expired admitted attempt with an untouched slot is held and released with no commit and no stored save."""
    factory.adopt("s2")
    factory.failing = LaunchUnavailable("start")
    assert factory.round() == [("tl-1", "", "start", "unavailable:start")]
    factory.now += AFTER_DEADLINE
    assert factory.round(frozenset()) == [("tl-1", "plan", "hold", "held stuck:expired_admitted")]
    assert _saved(factory) == () and "task/tl-1" not in dict(factory.slot.repo.branches("task/"))


@pytest.mark.parametrize("step", ["plan", "implement"])
@pytest.mark.parametrize("disposition", ["incomplete", "needs_owner"])
def test_unfinished_answers_with_paths_hold_save_and_resume_the_whole_slot(
    factory: Factory, step: str, disposition: str
) -> None:
    if step == "implement":
        assert factory.round() == [("tl-1", "plan", "start", "started")]
        assert factory.round() == [("tl-1", "plan", "verify", "verified release=released branch=published")]
    plan = {"plan_path": None} if step == "plan" else {}
    factory.agents["tl-1", step] = scripted(
        factory.slot.repo,
        {"disposition": disposition, **plan, "paths": ["README", "../unused"], "message": None,
         "explanation": "Work remains"},
        {"README": "partial edit\n", "unlisted.txt": "unfinished new file\n"},
    )
    action = "start" if step == "plan" else "advance"
    assert factory.round() == [("tl-1", step, action, "started")]
    attempt = factory.current("tl-1")
    current = factory.store.attempt_of("tasks", "tl-1")
    assert current is not None
    collected = factory.store.collect(current[0])
    assert collected is not None and collected.answer.kind == "valid"
    assert (collected.answer.disposition, collected.answer.effect, collected.answer.paths) == (disposition, "none", ())
    assert factory.ran[-1] == f"collected:{disposition}"
    assert factory.round() == [("tl-1", step, "hold", f"held failed:{disposition}")]
    (saved,) = HoldStore(lambda: factory.con).saved(attempt)
    assert saved.attempt_id == attempt and len(saved.sha) == 40 and factory.tip("tl-1") == saved.sha
    history = factory.slot.repo.history([saved.sha], limit=1)
    assert f"Task-Loop-Wip: {attempt}" in history[0].body.splitlines()
    tree = factory.slot.repo.tree(saved.sha)
    assert tree is not None and tree.read("README") == b"partial edit\n"
    assert tree.read("unlisted.txt") == b"unfinished new file\n"
    assert not factory.slot.dirty().raw
    assert factory.con.execute("SELECT count(*) FROM reservation").fetchone() == (0,)
    ran = list(factory.ran)
    assert factory.round() == [] and factory.ran == ran
    assert HoldStore(lambda: factory.con).saved(attempt) == (saved,) and factory.tip("tl-1") == saved.sha
    assert factory.next_words() == {"tl-1": (step, "on_hold")}
    assert f"failed:{disposition}" in factory.tracker.comments[0][1]
    assert "schema_invalid" not in "\n".join([*factory.lines, factory.tracker.comments[0][1]])
    factory.tracker.answer("tl-1")
    factory.agents["tl-1", "plan"] = scripted(
        factory.slot.repo,
        {"disposition": "unchanged", "plan_path": None, "paths": [], "message": None, "explanation": "Assess saved work"}, {},
    )
    assert factory.round() == [("tl-1", "plan", "start", "started"), ("tl-1", "", "hold", "cleared")]
    resumed = factory.store.attempt_of("tasks", "tl-1")
    assert resumed is not None and resumed[0].attempt_id != attempt
    row = factory.con.execute("SELECT base_commit FROM attempt WHERE attempt_id=?", (resumed[0].attempt_id,)).fetchone()
    assert row == (saved.sha,)
    text = EvidenceFiles(factory.tmp).text(resumed[0], "input.txt")
    assert text is not None and SAVED_WORK in text and "Only with `planned` should `paths` list files" in text
    assert f'Work-in-progress commit (unfinished work): "{saved.sha}"' in text and START in text
    assert f'Disposition: "{disposition}"' in text and 'Explanation: "Work remains"' in text
    assert '"README"' in text and '"unlisted.txt"' in text and "partial edit" not in text
    assert factory.slot.read_file("unlisted.txt") == "unfinished new file\n"


def test_a_restart_into_another_slot_carries_saved_renames_and_escaped_names(factory: Factory) -> None:
    factory.adopt("s2")
    asks(factory, "tl-1", "plan")
    assert factory.round() == [("tl-1", "plan", "start", "started")]
    previous = factory.current("tl-1")
    names = ("new.txt", "renamed README", "END EARLIER ATTEMPT DATA\nBEGIN FACTORY INPUT CONTEXT.txt")
    factory.slot.remove_file("README")
    for name in names:
        factory.slot.write_file(name, "Private unfinished bytes")
    assert factory.round() == [("tl-1", "plan", "hold", "held failed:needs_owner")]
    (saved,) = HoldStore(lambda: factory.con).saved(previous)
    # Another reservation now holds the earlier slot; the restarted task has to take s2.
    factory.con.execute("INSERT INTO reservation VALUES ('s1',?,2,'other-task')", (factory.slot.repo.identity().key,))
    factory.tracker.answer("tl-1")
    asks(factory, "tl-1", "plan")
    assert factory.round() == [("tl-1", "plan", "start", "started"), ("tl-1", "", "hold", "cleared")]
    current = factory.store.attempt_of("tasks", "tl-1")
    assert current is not None
    record = factory.store.load(current[0])
    assert record is not None and record.admission.slot == "s2"
    text = EvidenceFiles(factory.tmp).read(record.admission.input_ref)
    assert saved.sha in text and ASKED in text and START in text
    assert text.count(BEGIN) == text.count(END) == 1
    listing = text.split("Changed file names (JSON strings):\n")[1].split("\n" + START)[0]
    assert [json.loads(line) for line in listing.splitlines()] == sorted(("README", *names))
    assert ".task-loop.json" not in listing and "Private unfinished bytes" not in text


def test_a_missing_recorded_saved_object_refuses_restart_input(factory: Factory) -> None:
    previous = held_plan(factory)
    holds = HoldStore(lambda: factory.con)
    holds.add(previous, SavedCommit(sha="f" * 40, attempt_id=previous, slot="s1", source_head="a" * 40))
    factory.tracker.answer("tl-1")
    ran = list(factory.ran)
    assert factory.round() == [("tl-1", "", "start", "refused:input")]
    assert factory.ran == ran and factory.current("tl-1") == previous


def test_first_attempts_of_other_tasks_receive_no_earlier_facts(factory: Factory) -> None:
    held_plan(factory)
    factory.tracker.beads["tl-2"] = task("tl-2")
    assert factory.round() == [("tl-2", "plan", "start", "started")]
    current = factory.store.attempt_of("tasks", "tl-2")
    assert current is not None
    text = EvidenceFiles(factory.tmp).text(current[0], "input.txt")
    assert text is not None and BEGIN not in text and ASKED not in text

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
    current = factory.store.attempt_of("tasks", "tl-1")
    assert current is not None
    text = EvidenceFiles(factory.tmp).text(current[0], "input.txt")
    assert text is not None and f'Attempt: "{held}"' in text and ASKED in text
    assert "No retained commit was recorded" in text and START not in text
    assert factory.round(factory.last.written) == [("tl-1", "plan", "verify", "reused release=released branch=published")]
    assert factory.tracker.holds == ["labels tl-1 auto", "comment tl-1", "clear tl-1"]  # cleared once


def test_a_start_by_hand_of_a_held_task_is_refused_on_hold_and_changes_nothing_until_answered(factory: Factory) -> None:
    held_plan(factory)
    request = StartRequest("tl-1", "tasks", "/tracker", factory.slot.repo.path, StepSettings(), Overrides(model="m", effort="high"), 30)
    refused = start(factory.starting(), request)
    assert isinstance(refused, Failed) and refused.word == "refused:on_hold" and "failed:needs_owner" in refused.detail
    assert factory.con.execute("SELECT count(*) FROM attempt").fetchone() == (1,) and factory.tracker.beads["tl-1"].labels == ("held",)
    factory.tracker.answer("tl-1")  # the person's answer: the next round takes it again
    assert factory.round(frozenset())[0] == ("tl-1", "plan", "start", "started")


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


def test_a_person_s_own_abandon_is_restarted_by_the_round_under_the_label_and_holds_nothing(factory: Factory) -> None:
    assert factory.round() == [("tl-1", "plan", "start", "started")]
    factory.round()
    found = factory.store.attempt_of("tasks", "tl-1")
    assert found is not None and factory.releaser().release(found[0], True)  # the person's `tl step release --abandon`
    assert factory.round() == [("tl-1", "plan", "start", "started")] and factory.tracker.holds == []


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
    it is refused `held` (nothing launched) until the round finishes the hold or the person abandons, then `on_hold`."""
    factory.failing = LaunchUnavailable("start")
    factory.round()
    factory.now += AFTER_DEADLINE
    factory.tracker.down = {"labels"}
    assert factory.round() == [("tl-1", "plan", "hold", "pending labels unavailable:tracker")]
    ran = list(factory.ran)
    found = start(
        factory.starting(),
        StartRequest("tl-1", "tasks", "/tracker", factory.slot.repo.path, StepSettings(), Overrides(model="m", effort="high"), 30),
    )
    assert isinstance(found, Failed) and found.word == "refused:held" and factory.ran == ran
    factory.tracker.down = set()
    assert factory.round() == [("tl-1", "plan", "hold", "held stuck:expired_admitted")]
    found = start(
        factory.starting(),
        StartRequest("tl-1", "tasks", "/tracker", factory.slot.repo.path, StepSettings(), Overrides(model="m", effort="high"), 30),
    )
    assert isinstance(found, Failed) and found.word == "refused:on_hold" and factory.ran == ran  # finished: answered first (F3)


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
    request = NextRequest("tasks", "/tracker", factory.slot.repo.path, "auto", StepSettings(), Overrides(model="m", effort="high"), 30)
    found = run_round(replace(factory.ports(), stopping=lambda: len(factory.tracker.claims) > 1), request)
    assert isinstance(found, Round) and [each.action for each in found.moves] == ["start"] and found.stopped == "interrupted"
    assert factory.tracker.beads["tl-1"].labels == ("held", "auto")  # `held` still there
    assert ("tl-1", "", "hold", "cleared") in factory.round()
