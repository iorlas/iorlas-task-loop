"""The rounds bench (S5c, S6e): one adopted slot and every round port real over factory.db and the semantic Git fake,
except the tracker (`Tracker`, with the hold's label, comment and clear writes), the agent (a scripted agent per task and
step, run at once by the launch port as the registered entry would run it) and the slot setup's process. `test_advance`,
`test_checks_round` and `test_round_holds` drive it."""

import json
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import replace
from functools import partial
from pathlib import Path

from any_agent import Harness, LaunchSpec, RunHooks, RunOutcome, Summary
from any_agent.procs import Worker
from any_agent.testing import FakeRun
from beads_client import BdError, Bead
from doubles import Environment, NoChecks, PinnedViews
from git_porcelain.testing import FakeRepo, FakeWorktree
from sqlite_store import begin_immediate

from taskloop.admit import AdmitRefused, AdmitResult, AttemptAdmission
from taskloop.admit_chain import NextAdmission
from taskloop.agents.launch import AgentLaunch
from taskloop.agents.settings import Overrides, StepSettings
from taskloop.attempt import Attempts
from taskloop.attempt_status import Listed, StatusPorts, current_view, list_attempts
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, EntryIdentity, Seen, SlotFiles
from taskloop.check_admit import ChecksRequest
from taskloop.evidence_files import EvidenceFiles
from taskloop.hold import HoldPorts
from taskloop.hold_store import HoldStore
from taskloop.ids import NativeIds
from taskloop.launch import Launched, LaunchResult
from taskloop.operations import ChecksPorts, ChecksReleasing, Round, Started, StartPorts, StartRequest, start, verify_task
from taskloop.publish import BranchPublish
from taskloop.round import NextRequest, RoundPorts, run_round
from taskloop.slot_lock import custody, hold
from taskloop.slot_release import SlotRelease
from taskloop.task import TaskBinding, TaskInspection, TaskScope
from taskloop.tracker import inspect_task
from taskloop.tracker_client import HoldAnswer, HoldWrite, LabelStep, TrackerHolds
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
    """The tracker's reads, the claim and the hold's writes: a task is ready while open and labelled; the claim makes it
    in progress for taskloop, the fenced unclaim opens it again (False when it is not taskloop's or closed). `down`: the
    hold writes that fail (`unavailable`, a bd outage); `comments` every comment written, `holds` every hold write."""

    def __init__(self, *beads: Bead) -> None:
        self.beads = {bead.id: bead for bead in beads}
        self.claims: list[str] = []
        self.shows: list[str] = []
        self.ready_reads = 0
        self.down: set[str] = set()
        self.deleted_as = ""  # bd's words for a task not in `beads` (empty: `show` answers nothing)
        self.comments: list[tuple[str, str]] = []
        self.holds: list[str] = []

    def labels(self, _root: str, task_id: str, label: str) -> HoldAnswer[LabelStep]:
        """5.2: nothing written for a missing or closed task or another actor's; else `held` added and `label` removed."""
        self.holds.append(f"labels {task_id} {label}")
        found = self.beads.get(task_id)
        if "labels" in self.down:
            return HoldAnswer("unavailable", "lock")
        if found is None or found.status == "closed":
            return HoldAnswer("missing" if found is None else "closed")
        if found.assignee not in ("", "taskloop"):
            return HoldAnswer("not_ours")
        kept = tuple(each for each in found.labels if each not in ("held", label))
        self.beads[task_id] = replace(found, labels=(*kept, "held"))
        return HoldAnswer("moved" if label in found.labels else "absent", found.assignee)

    def comment(self, _root: str, task_id: str, text: str) -> HoldAnswer[HoldWrite]:
        self.holds.append(f"comment {task_id}")
        if "comment" in self.down:
            return HoldAnswer("unavailable", "lock")
        self.comments.append((task_id, text))
        return HoldAnswer("done")

    def clear(self, _root: str, task_id: str) -> HoldAnswer[HoldWrite]:
        self.holds.append(f"clear {task_id}")
        if "clear" in self.down:
            return HoldAnswer("unavailable", "lock")
        found = self.beads[task_id]
        self.beads[task_id] = replace(found, labels=tuple(each for each in found.labels if each != "held"))
        return HoldAnswer("done")

    def answer(self, task_id: str, label: str = "auto") -> None:
        """The person's answer: the label added back."""
        found = self.beads[task_id]
        self.beads[task_id] = replace(found, labels=(*found.labels, label))

    def show(self, task_id: str) -> Bead | None:
        self.shows.append(task_id)
        if task_id not in self.beads and self.deleted_as:
            raise BdError("other", self.deleted_as)
        return self.beads.get(task_id)

    def ready(self, label: str = "") -> list[Bead]:
        self.ready_reads += 1
        return [bead for bead in self.beads.values() if bead.status == "open" and (not label or label in bead.labels)]

    def find(self, status: str = "", label: str = "", *, include_closed: bool = False) -> list[Bead]:
        return [bead for bead in self.beads.values() if bead.status == status and (not label or label in bead.labels)]

    def claim(self, _root: str, task_id: str) -> bool:
        self.claims.append(task_id)
        self.beads[task_id] = replace(self.beads[task_id], status="in_progress", assignee="taskloop")
        return True

    def unclaim(self, _root: str, task_id: str) -> bool:
        found = self.beads.get(task_id)
        if found is None or found.status == "closed" or found.assignee != "taskloop":
            return False
        self.beads[task_id] = replace(found, status="open", assignee="")
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
        attempts = Attempts(
            self.store,
            EvidenceFiles(self.tmp),
            AgentLaunch(lambda _harness: ("/bin/codex", {}), ids=NativeIds()),
            self.agents[task_id, step or ""],
            lambda: self.now,
            self.checkouts,
            self.files,
            environment=self.environment.preparation(),
        )
        found = attempts.execute(key, ENTRY, lambda: "held")
        self.ran.append(f"{found.status}:{found.reason}")
        return Launched(key, ENTRY)

    def starting(self) -> StartPorts:
        files, clock = EvidenceFiles(self.tmp), lambda: self.now
        fresh = AttemptAdmission(lambda: self.con, begin_immediate, files, self.tracker.inspect, self.checkouts, self.tracker.claim,
                                 self.tracker.unclaim, clock, lambda _p: True, self.files, ids=NativeIds())
        advance = NextAdmission(lambda: self.con, begin_immediate, files, self.tracker.inspect, self.checkouts, clock, lambda _p: True,
                                self.files, ids=NativeIds())
        return StartPorts(self.store, fresh, self, clock, Never(), advance, ChecksPorts(NoRequired(), NoChecks(), NoChecks()))

    def releaser(self) -> SlotRelease:
        return SlotRelease(self.store, self.checkouts, self.files, lambda _entry: "gone", lambda _worker: True, custody,
                           self.tracker.unclaim, lambda: self.now, lambda _setup: "gone", lambda _scratch: True,
                           HoldStore(lambda: self.con), ids=NativeIds())

    def observe(self, _entry: EntryIdentity) -> Seen:
        """Called while the round reads its snapshot: `during` is another actor acting once, right after that read."""
        during, self.during = self.during, lambda: None
        during()
        return "gone"

    def checks_release(self) -> ChecksReleasing:
        """The hold's abandon of a checks attempt (none on this bench: no check step)."""
        return NoChecks()

    def holding(self, reads: StatusPorts) -> HoldPorts:
        tracker = TrackerHolds(self.tracker.labels, self.tracker.comment, self.tracker.clear)
        return HoldPorts(HoldStore(lambda: self.con), self.store, tracker, self.releaser(), self.checks_release(), lambda: self.now,
                         EvidenceFiles(self.tmp), partial(current_view, reads))

    def ports(self) -> RoundPorts:
        """Fresh ports over the same factory.db each round, as each `tl step rounds` round opens them (a restart too)."""
        verifier = Verifier(self.store, self.checkouts, self.files, lambda _worker: True, lambda: self.now, hold, ids=NativeIds())
        reads = StatusPorts(self.store, self.observe, lambda: self.now, verifier.leftovers, lambda: "boot")
        publisher = BranchPublish(self.store, self.checkouts, self.files, lambda: self.now, ids=NativeIds())
        holding = self.holding(reads)
        return RoundPorts(reads, self.starting(), verifier, self.releaser(), publisher, holding, self.tracker,
            self.lines.append, ids=NativeIds())

    def round(
        self, quiet: frozenset[tuple[str, str, str, str]] | None = None, label: str = "auto", running: int = 10
    ) -> list[tuple[str, str, str, str]]:
        self.now += 1
        request = NextRequest(
            "tasks",
            "/tracker",
            self.slot.repo.path,
            label,
            StepSettings(),
            Overrides(model="m", effort="high"),
            30,
            quiet,
            max_running=running,
        )
        found = run_round(self.ports(), request)
        assert isinstance(found, Round)
        self.last = found
        return [(each.task_id, each.step, each.action, each.word) for each in found.moves]

    def by_hand(self, task_id: str) -> None:
        """`tl step start` then `tl step verify` (its release and publication), as the person runs them."""
        self.now += 1
        assert isinstance(
            start(
                self.starting(),
                StartRequest(task_id, "tasks", "/tracker", self.slot.repo.path, StepSettings(), Overrides(model="m", effort="high"), 30),
            ),
            Started,
        )
        self.now += 1
        verify_task(self.store, Verifier(self.store, self.checkouts, self.files, lambda _w: True,
            lambda: self.now, hold, ids=NativeIds()), self.releaser(),
                    BranchPublish(self.store, self.checkouts, self.files, lambda: self.now, ids=NativeIds()), "tasks", task_id)

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
