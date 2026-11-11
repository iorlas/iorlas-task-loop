"""The round advances a claimed task from plan to implement (S5c), end to end over real SQLite, real admission, verify,
release and publish, the semantic Git fake with its fake remote, a scripted agent run at once by the launch port (as the
registered entry would run it), the fake slot setup and a tracker double: plan, advance, implement, `Next: advance` (to
the check step, whose admission is a double here)."""

import json
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path

import pytest
from any_agent import Harness, LaunchSpec, RunHooks, RunOutcome, Summary
from any_agent.procs import Worker
from any_agent.testing import FakeRun
from beads_client import Bead
from doubles import Command, Environment, NoChecks, PinnedViews
from git_porcelain.testing import FakeRepo, FakeWorktree
from sqlite_store import begin_immediate

from taskloop.admit import AdmitRefused, AdmitResult, AttemptAdmission
from taskloop.admit_chain import NextAdmission
from taskloop.attempt import Attempts
from taskloop.attempt_status import Listed, StatusPorts, list_attempts
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, EntryIdentity, Seen, SlotFiles
from taskloop.check_admit import ChecksRequest
from taskloop.evidence_files import EvidenceFiles
from taskloop.launch import Launched, LaunchResult, LaunchUnavailable
from taskloop.operations import ChecksPorts, Round, Started, StartPorts, StartRequest, start, verify_task
from taskloop.publish import BranchPublish
from taskloop.round import NextRequest, RoundPorts, run_round
from taskloop.slot_lock import custody, hold
from taskloop.slot_release import SlotRelease
from taskloop.task import TaskBinding, TaskInspection, TaskScope
from taskloop.tracker import inspect_task
from taskloop.verifier import Verifier

ENTRY = (7, "entry-start", "boot")
WORKER = Worker(pid=42, pgid=42, start="native-start", boot="boot")
type Agent = Callable[[Harness, LaunchSpec, float, RunHooks | None], RunOutcome]


def scripted(repo: FakeRepo, answer: Mapping[str, object], files: Mapping[str, str]) -> Agent:
    """An agent that writes `files` in the slot it runs in (its cwd) and answers `answer`."""

    def run(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        here = repo.worktree(Path(spec.cwd or ""))
        for path, text in files.items():
            here.write_file(path, text)
        outcome = RunOutcome(rc=0, worker=WORKER, summary=Summary(text=json.dumps(answer), rc=0, stands=True))
        return FakeRun(outcome)(harness, spec, timeout, hooks)

    return run


class Tracker:
    """The tracker's reads and the claim: a task is ready while open and labelled; the claim makes it in progress for
    taskloop, an unclaim opens it again."""

    def __init__(self, *beads: Bead) -> None:
        self.beads = {bead.id: bead for bead in beads}
        self.claims: list[str] = []
        self.shows: list[str] = []
        self.ready_reads = 0

    def show(self, task_id: str) -> Bead | None:
        self.shows.append(task_id)
        return self.beads.get(task_id)

    def ready(self, label: str = "") -> list[Bead]:
        self.ready_reads += 1
        return [bead for bead in self.beads.values() if bead.status == "open" and (not label or label in bead.labels)]

    def claim(self, _root: str, task_id: str) -> bool:
        self.claims.append(task_id)
        self.beads[task_id] = replace(self.beads[task_id], status="in_progress", assignee="taskloop")
        return True

    def unclaim(self, _root: str, task_id: str) -> bool:
        self.beads[task_id] = replace(self.beads[task_id], status="open", assignee="")
        return True

    def inspect(self, task_id: str, backlog: str, root: str) -> TaskInspection:
        return inspect_task(TaskBinding(TaskScope(backlog), Path(root)), self, task_id)


class Factory:
    """One adopted slot; every port real over factory.db and the Git fake, except the tracker, the agent (`agents`, one
    per task and step) and the setup process. `launch` registers the task's current attempt's entry and runs its body at
    once; `failing` answers the next launch instead, with nothing run (an entry that never started)."""

    def __init__(self, con: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: PinnedViews, files: SlotFiles,
                 tracker: Tracker) -> None:
        con.execute("INSERT INTO slot (repo_id,name,path) VALUES (?,'s1',?)", (slot.repo.identity().key, str(slot.path)))
        self.root = slot.path.parent
        self.con, self.tmp, self.slot, self.checkouts, self.files, self.tracker = con, tmp_path, slot, checkouts, files, tracker
        self.store = AttemptStore(lambda: con)
        self.environment = Environment(con, checkouts, tmp_path, tmp_bytes=4096)
        self.agents: dict[tuple[str, str], Agent] = {}
        self.failing: LaunchResult | None = None
        self.now, self.lines = 10.0, list[str]()
        self.last = Round("tasks", ())
        self.during: Callable[[], object] = lambda: None
        self.ran: list[str] = []  # each launched body's result

    def adopt(self, name: str) -> None:
        """One more slot, made and adopted as a person does: detached at the repository's HEAD."""
        added = self.slot.repo.add_worktree(self.root / name, "HEAD")
        self.con.execute("INSERT INTO slot (repo_id,name,path) VALUES (?,?,?)", (self.slot.repo.identity().key, name, str(added.path)))

    def launch(self, backlog: str, task_id: str, minutes: int) -> LaunchResult:
        if self.failing is not None:
            failing, self.failing = self.failing, None
            return failing
        found = self.store.attempt_of(backlog, task_id)
        assert found is not None
        key = found[0]
        self.store.register_entry(key, ENTRY, self.now)  # a relaunch keeps the identity registered first
        step = self.store.step_of(key.attempt_id)
        attempts = Attempts(self.store, EvidenceFiles(self.tmp), lambda: ("/bin/codex", {}), self.agents[task_id, step or ""],
                            lambda: self.now, self.checkouts, self.files, environment=self.environment.preparation())
        found = attempts.execute(key, ENTRY, lambda: "held")
        self.ran.append(f"{found.status}:{found.reason}")
        return Launched(key, ENTRY)

    def starting(self) -> StartPorts:
        files, clock = EvidenceFiles(self.tmp), lambda: self.now
        fresh = AttemptAdmission(lambda: self.con, begin_immediate, files, self.tracker.inspect, self.checkouts, self.tracker.claim,
                                 self.tracker.unclaim, clock, lambda _p: True, self.files)
        advance = NextAdmission(lambda: self.con, begin_immediate, files, self.tracker.inspect, self.checkouts, clock, lambda _p: True,
                                self.files)
        return StartPorts(self.store, fresh, self, clock, Never(), advance, ChecksPorts(NoRequired(), NoChecks()))

    def releaser(self) -> SlotRelease:
        return SlotRelease(self.store, self.checkouts, self.files, lambda _entry: "gone", lambda _worker: True, custody,
                           self.tracker.unclaim, lambda: self.now, lambda _setup: "gone", lambda _scratch: True)

    def observe(self, _entry: EntryIdentity) -> Seen:
        """Called while the round reads its snapshot: `during` is another actor acting once, right after that read."""
        during, self.during = self.during, lambda: None
        during()
        return "gone"

    def ports(self) -> RoundPorts:
        """Fresh ports over the same factory.db each round, as each `tl step rounds` round opens them (a restart too)."""
        verifier = Verifier(self.store, self.checkouts, self.files, lambda _worker: True, lambda: self.now, hold)
        reads = StatusPorts(self.store, self.observe, lambda: self.now, verifier.leftovers, lambda: "boot")
        publisher = BranchPublish(self.store, self.checkouts, self.files, lambda: self.now)
        return RoundPorts(reads, self.starting(), verifier, self.releaser(), publisher, self.tracker, self.lines.append)

    def round(self, quiet: frozenset[tuple[str, str, str, str]] | None = None) -> list[tuple[str, str, str, str]]:
        self.now += 1
        found = run_round(self.ports(), NextRequest("tasks", "/tracker", self.slot.repo.path, "auto", "m", "high", 30, quiet))
        assert isinstance(found, Round)
        self.last = found
        return [(each.task_id, each.step, each.action, each.word) for each in found.moves]

    def by_hand(self, task_id: str) -> None:
        """`tl step start` then `tl step verify` (its release and publication), as the person runs them."""
        self.now += 1
        assert isinstance(start(self.starting(), StartRequest(task_id, "tasks", "/tracker", self.slot.repo.path, "m", "high", 30)), Started)
        self.now += 1
        verify_task(self.store, Verifier(self.store, self.checkouts, self.files, lambda _w: True, lambda: self.now, hold), self.releaser(),
                    BranchPublish(self.store, self.checkouts, self.files, lambda: self.now), "tasks", task_id)

    def next_words(self) -> dict[str, tuple[str, str]]:
        listed = list_attempts(StatusPorts(self.store, lambda _entry: "gone", lambda: self.now, lambda _key: None, lambda: "boot"))
        assert isinstance(listed, Listed)
        return {each.task_id: (each.step, each.next) for each in listed.attempts}

    def current(self, task_id: str) -> str:
        found = self.store.attempt_of("tasks", task_id)
        assert found is not None
        return found[0].attempt_id

    def tip(self, task_id: str) -> str:
        return next(ref.sha for ref in self.slot.repo.refs(["refs/heads/task/"]) if ref.name == f"refs/heads/task/{task_id}")


class NoRequired:
    """The checks admission at a `main` whose profile requires no check: every done implement attempt is skipped."""

    def admit_checks(self, request: ChecksRequest) -> AdmitResult:
        return AdmitRefused("no_required")


class Never:
    def repeat(self, backlog: str, task_id: str, current: AttemptKey, entry: EntryIdentity | None, minutes: int) -> Started:
        raise AssertionError("no step leaves leftovers here")


def task(task_id: str) -> Bead:
    return Bead(task_id, title=f"Widget {task_id}", description="It must do X", status="open", labels=("auto",))


def scripts(factory: Factory, slot: FakeWorktree, *task_ids: str) -> None:
    """Each task's plan agent writes its plan; its implement agent adds code and a test."""
    for task_id in task_ids:
        plan, code, test = f"docs/design/{task_id}/plan.md", f"src/{task_id}.py", f"tests/test_{task_id}.py"
        factory.agents[task_id, "plan"] = scripted(
            slot.repo, {"disposition": "planned", "plan_path": plan, "paths": [plan], "message": "Plan", "explanation": "planned"},
            {plan: "# Plan\n"})
        factory.agents[task_id, "implement"] = scripted(
            slot.repo, {"disposition": "implemented", "paths": [code, test], "message": "Add it", "explanation": "ran just check"},
            {code: "X = 1\n", test: "def test_x() -> None: ...\n"})


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


def test_an_abandoned_task_is_never_advanced_nor_re_admitted_by_a_round(factory: Factory) -> None:
    factory.by_hand("tl-1")
    found = factory.store.attempt_of("tasks", "tl-1")
    assert found is not None and factory.releaser().release(found[0], True)  # the person's `tl step release --abandon`
    assert factory.round() == [("tl-1", "plan", "skip", "abandoned"), ("tl-2", "plan", "start", "started")]
    assert factory.tracker.claims == ["tl-1", "tl-2"] and factory.current("tl-1") == found[0].attempt_id


def test_an_abandon_after_the_rounds_read_is_skipped_never_admitted_afresh(factory: Factory) -> None:
    factory.tracker.beads.pop("tl-2")
    factory.by_hand("tl-1")
    found = factory.store.attempt_of("tasks", "tl-1")
    assert found is not None
    factory.during = lambda: factory.releaser().release(found[0], True)
    assert factory.round() == [("tl-1", "plan", "skip", "abandoned"), ("tl-1", "plan", "skip", "attempted")]
    assert factory.tracker.claims == ["tl-1"] and factory.current("tl-1") == found[0].attempt_id
    assert factory.round() == [("tl-1", "plan", "skip", "abandoned")]


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
    assert factory.round() == [("tl-1", "plan", "skip", "task"), ("tl-2", "implement", "advance", "started"),
                               ("tl-3", "plan", "start", "started")]
    assert factory.last.stopped == ""
    assert ("tl-1", "plan", "skip", "task") in factory.round() and factory.last.stopped == ""
    assert factory.con.execute("SELECT count(*) FROM attempt WHERE task_id='tl-1' AND step='implement'").fetchone() == (0,)
