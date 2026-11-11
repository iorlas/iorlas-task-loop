"""The advance from a done plan to the implement step (`admit_next`), through real SQLite, the semantic Git fake with its
fake remote, the owning agent and task-read fakes: what it stores, what refuses it, the implement step verified and
published on top of the plan, a repeat staying in implement, an abandon restarting at plan, and the v11 CHECKs."""

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
from beads_client.testing import FakeTaskReadClient
from doubles import PinnedViews
from git_porcelain.testing import FakeRemote, FakeRepo, FakeWorktree
from sqlite_store import begin_immediate

from taskloop.admit import AdmitRefused, AdmitRequest, Admitted, AttemptAdmission
from taskloop.admit_chain import ChainAdmission, NextAdmission, NextStepRequest, RepeatRequest
from taskloop.attempt import Attempts
from taskloop.attempt_status import Shown, StatusPorts, show_attempt
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, Checkouts, EntryIdentity, FileRef, SlotFiles
from taskloop.evidence_files import EvidenceFiles
from taskloop.launch import Launched, LaunchResult
from taskloop.operations import Started, StartPorts, StartRequest, VerifiedTask, start, verify_task
from taskloop.publish import BranchPublish, NotPublished, PublishResult
from taskloop.slot_lock import custody, hold
from taskloop.slot_release import Released, SlotRelease
from taskloop.task import TaskBinding, TaskInspection, TaskScope
from taskloop.tracker import inspect_task
from taskloop.verifier import Verifier

KEY = AttemptKey("attempt", "dispatch", 1)
ENTRY = (7, "entry-start", "boot")
WORKER = Worker(pid=42, pgid=42, start="native-start", boot="boot")
PLAN = "docs/design/tl-1/plan.md"
CLAIMED = Bead("tl-1", title="Add a widget", description="It must do X", status="in_progress", assignee="taskloop")
type Agent = Callable[[Harness, LaunchSpec, float, RunHooks | None], RunOutcome]


def agent(answer: Mapping[str, object], change: Callable[[], None]) -> Agent:
    def run(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        change()
        outcome = RunOutcome(rc=0, worker=WORKER, summary=Summary(text=json.dumps(answer), rc=0, stands=True))
        return FakeRun(outcome)(harness, spec, timeout, hooks)

    return run


def execute(con: sqlite3.Connection, tmp_path: Path, key: AttemptKey, run: Agent, checkouts: Checkouts, files: SlotFiles) -> str:
    attempts = Attempts(AttemptStore(lambda: con), EvidenceFiles(tmp_path), lambda: ("/bin/codex", {}), run, lambda: 10, checkouts, files)
    return attempts.execute(key, ENTRY).reason


def finish(con: sqlite3.Connection, checkouts: Checkouts, files: SlotFiles, *, publish: bool = True) -> VerifiedTask:
    """`tl step verify` as built: the verdict, the settled release (the real one) and the publication to origin."""
    store = AttemptStore(lambda: con)
    verifier = Verifier(store, checkouts, files, lambda _worker: True, lambda: 20, hold)
    releaser = SlotRelease(store, checkouts, files, lambda _entry: "gone", lambda _worker: True, custody, lambda _r, _t: True, lambda: 30)
    found = verify_task(store, verifier, releaser, BranchPublish(store, checkouts, files, lambda: 40) if publish else Unpublished(),
                        "tasks", "tl-1")
    assert isinstance(found, VerifiedTask)
    return found


class Unpublished:
    def publish(self, key: AttemptKey) -> PublishResult:
        return NotPublished("unavailable", "remote", "no route")


def tasks(*beads: Bead) -> Callable[[str, str, str], TaskInspection]:
    client = FakeTaskReadClient(list(beads))
    return lambda task_id, backlog, root: inspect_task(TaskBinding(TaskScope(backlog), Path(root)), client, task_id)


def advancing(con: sqlite3.Connection, tmp_path: Path, checkouts: Checkouts, files: SlotFiles, bead: Bead = CLAIMED) -> NextAdmission:
    return NextAdmission(lambda: con, begin_immediate, EvidenceFiles(tmp_path), tasks(bead), checkouts, lambda: 10, lambda _p: True, files)


def request(repo: FakeRepo, previous: AttemptKey = KEY) -> NextStepRequest:
    return NextStepRequest(previous, repo.path, "chosen", "high", "workspace-write", 100)


def tip(repo: FakeRepo) -> str:
    return next(ref.sha for ref in repo.refs(["refs/heads/task/"]) if ref.name == "refs/heads/task/tl-1")


@pytest.fixture
def planned(registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles) -> str:
    """The registered plan attempt ran, was verified, released settled and published: its X."""
    answer = {"disposition": "planned", "plan_path": PLAN, "paths": [PLAN], "message": "Plan", "explanation": "done"}
    assert execute(registered, tmp_path, KEY, agent(answer, lambda: slot.write_file(PLAN, "# Plan\n")), checkouts, slot_files) == (
        "verification")
    assert finish(registered, checkouts, slot_files).published == "published"
    return tip(slot.repo)


def implement(con: sqlite3.Connection, tmp_path: Path, repo: FakeRepo, checkouts: Checkouts, files: SlotFiles) -> AttemptKey:
    """The advance, admitted and its entry registered (as `tl step start` then the entry would)."""
    admitted = advancing(con, tmp_path, checkouts, files).admit_next(request(repo))
    assert isinstance(admitted, Admitted)
    assert AttemptStore(lambda: con).register_entry(admitted.key, ENTRY, 10) == "accepted"
    return admitted.key


def test_a_done_plan_advances_to_implement_attempt_one_after_its_commit(
    registered: sqlite3.Connection, planned: str, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    """No claim port at all; the bead has no `auto` label; the tracker root and order carry on, D is the slot's head."""
    admitted = advancing(registered, tmp_path, checkouts, slot_files).admit_next(request(slot.repo))
    assert isinstance(admitted, Admitted) and admitted.slot == "s1"
    row = registered.execute(
        """SELECT step,number,seq,after_commit,previous_attempt_id,tracker_root,sandbox,slot_head,input_path FROM attempt
        WHERE attempt_id=?""", (admitted.key.attempt_id,)).fetchone()
    d = registered.execute("SELECT slot_head FROM attempt WHERE attempt_id='attempt'").fetchone()[0]
    assert row[:8] == ("implement", 1, 2, planned, None, "/tracker", "workspace-write", d)
    text = (tmp_path / row[8]).read_text()
    assert text.startswith("Add a widget\n\nIt must do X") and f"`{PLAN}`" in text
    assert registered.execute("SELECT attempt_id FROM reservation").fetchone() == (admitted.key.attempt_id,)


@pytest.mark.parametrize("bead", [replace(CLAIMED, status="open"), replace(CLAIMED, assignee="someone"), replace(CLAIMED, status="closed")])
def test_a_task_no_longer_in_progress_for_taskloop_is_claim_lost_with_nothing_written(
    registered: sqlite3.Connection, planned: str, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles,
    bead: Bead,
) -> None:
    found = advancing(registered, tmp_path, checkouts, slot_files, bead).admit_next(request(slot.repo))
    assert isinstance(found, AdmitRefused) and found.reason == "claim_lost"
    assert registered.execute("SELECT (SELECT count(*) FROM attempt),(SELECT count(*) FROM reservation)").fetchone() == (1, 0)


def abandon(con: sqlite3.Connection, checkouts: Checkouts, files: SlotFiles, key: AttemptKey = KEY) -> None:
    store = AttemptStore(lambda: con)
    release = SlotRelease(store, checkouts, files, lambda _entry: "gone", lambda _worker: True, custody, lambda _r, _t: True, lambda: 50)
    assert isinstance(release.release(key, True), Released)


@pytest.mark.parametrize("case", ["unpublished", "published_elsewhere", "abandoned", "unknown_key"])
def test_only_a_verified_settled_published_current_attempt_advances(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles, case: str
) -> None:
    answer = {"disposition": "planned", "plan_path": PLAN, "paths": [PLAN], "message": "Plan", "explanation": "done"}
    execute(registered, tmp_path, KEY, agent(answer, lambda: slot.write_file(PLAN, "# Plan\n")), checkouts, slot_files)
    finish(registered, checkouts, slot_files, publish=case != "unpublished")
    if case == "published_elsewhere":
        registered.execute("UPDATE published_branch SET commit_sha=?", ("f" * 40,))
    if case == "abandoned":  # the person abandons the settled plan: its claim is returned
        abandon(registered, checkouts, slot_files)
    previous = AttemptKey("attempt", "other", 1) if case == "unknown_key" else KEY
    found = advancing(registered, tmp_path, checkouts, slot_files).admit_next(request(slot.repo, previous))
    assert isinstance(found, AdmitRefused) and found.reason == "not_advanceable"
    assert registered.execute("SELECT count(*) FROM attempt").fetchone() == (1,)


class Racing(EvidenceFiles):
    """Another advance runs to its commit while this one writes its input: after its reads, before its transaction."""

    def __init__(self, root: Path, other: Callable[[], object]) -> None:
        super().__init__(root)
        self.other, self.won = other, object()

    def put_input(self, key: AttemptKey, text: str) -> FileRef:
        self.won = self.other()
        return super().put_input(key, text)


def test_a_superseded_or_racing_advance_is_task_attempted_and_one_attempt_is_admitted(
    registered: sqlite3.Connection, planned: str, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    """A second advance wins between the first one's read and its transaction: the first finds another current attempt."""
    other = advancing(registered, tmp_path / "other", checkouts, slot_files)
    files = Racing(tmp_path, lambda: other.admit_next(request(slot.repo)))
    racing = NextAdmission(lambda: registered, begin_immediate, files, tasks(CLAIMED), checkouts, lambda: 10, lambda _p: True, slot_files)
    found = racing.admit_next(request(slot.repo))
    assert isinstance(files.won, Admitted)
    assert isinstance(found, AdmitRefused) and found.reason == "task_attempted"
    again = advancing(registered, tmp_path, checkouts, slot_files).admit_next(request(slot.repo))
    assert isinstance(again, AdmitRefused) and again.reason == "task_attempted"
    assert registered.execute("SELECT count(*) FROM attempt WHERE step='implement'").fetchone() == (1,)


def test_another_repository_checkout_is_refused(
    registered: sqlite3.Connection, planned: str, tmp_path: Path, repo: FakeRepo, slot_files: SlotFiles
) -> None:
    remote = FakeRemote("https://example.invalid/other.git")
    remote.advance("main", {"README": "two"})
    other = FakeRepo.clone(remote, tmp_path / "other")
    found = advancing(registered, tmp_path, PinnedViews(repo, other), slot_files).admit_next(replace(request(repo), checkout=other.path))
    assert isinstance(found, AdmitRefused) and found.reason == "checkout"


def test_the_implement_step_commits_on_the_plan_and_is_published_then_done(
    registered: sqlite3.Connection, planned: str, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    """Code, its test and a deletion, committed by the factory as one commit on the published plan commit."""
    key = implement(registered, tmp_path, slot.repo, checkouts, slot_files)
    paths = ["src/widget.py", "tests/test_widget.py", "README"]

    def change() -> None:
        slot.write_file("src/widget.py", "X = 1\n")
        slot.write_file("tests/test_widget.py", "def test_x() -> None: ...\n")
        slot.remove_file("README")

    answer = {"disposition": "implemented", "paths": paths, "message": "Add the widget", "explanation": "ran the tests"}
    assert execute(registered, tmp_path, key, agent(answer, change), checkouts, slot_files) == "verification"
    assert finish(registered, checkouts, slot_files) == VerifiedTask("verified", "tasks", "tl-1", key.attempt_id, "released", "published")
    x = tip(slot.repo)
    tree = slot.repo.tree(x)
    assert tree is not None and set(tree.files) == {PLAN, "src/widget.py", "tests/test_widget.py"}
    assert slot.repo.is_ancestor(planned, x) and [entry.sha for entry in slot.repo.history([x], not_on=[planned])] == [x]
    reads = StatusPorts(AttemptStore(lambda: registered), lambda _entry: "gone", lambda: 10, lambda _key: None, lambda: "boot")
    shown = show_attempt(reads, tmp_path, "tasks", "tl-1")
    assert isinstance(shown, Shown)
    view = shown.view
    assert (view.step, view.next, view.earlier) == ("implement", "done", (("attempt", "advanced"),))


def test_a_repeat_of_implement_stays_in_implement_and_names_no_after_commit(
    registered: sqlite3.Connection, planned: str, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    key = implement(registered, tmp_path, slot.repo, checkouts, slot_files)
    answer = {"disposition": "implemented", "paths": ["src/a.py"], "message": "A", "explanation": "x"}

    def change() -> None:
        slot.write_file("src/a.py", "A = 1\n")
        slot.write_file("scratch.log", "left over\n")

    execute(registered, tmp_path, key, agent(answer, change), checkouts, slot_files)
    repeated = ChainAdmission(lambda: registered, begin_immediate, EvidenceFiles(tmp_path), lambda: 10).admit_repeat(
        RepeatRequest(key, "feedback", 100, "uncommitted"))
    assert isinstance(repeated, Admitted)
    row = registered.execute("SELECT step,number,after_commit,previous_attempt_id FROM attempt WHERE attempt_id=?",
                             (repeated.key.attempt_id,)).fetchone()
    assert row == ("implement", 2, None, key.attempt_id)


def test_an_abandoned_implement_restarts_the_task_at_plan(
    registered: sqlite3.Connection, planned: str, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    key = implement(registered, tmp_path, slot.repo, checkouts, slot_files)
    abandon(registered, checkouts, slot_files, key)
    fresh = AttemptAdmission(lambda: registered, begin_immediate, EvidenceFiles(tmp_path), tasks(CLAIMED), checkouts,
                             lambda _r, _t: True, lambda _r, _t: True, lambda: 10, lambda _p: True, slot_files)
    admitted = fresh.admit(AdmitRequest("tl-1", "tasks", "/tracker", slot.repo.path, "chosen", "high", "workspace-write", 100))
    assert isinstance(admitted, Admitted)
    row = registered.execute("SELECT step,number,seq,after_commit FROM attempt WHERE attempt_id=?", (admitted.key.attempt_id,)).fetchone()
    assert row == ("plan", 1, 3, None)


class Launcher:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def launch(self, backlog: str, task_id: str, minutes: int) -> LaunchResult:
        self.calls.append(task_id)
        return Launched(KEY, ENTRY)


class Never:
    def admit(self, request: AdmitRequest) -> Admitted:
        raise AssertionError("a done step never admits afresh")

    def repeat(self, backlog: str, task_id: str, current: AttemptKey, entry: EntryIdentity | None, minutes: int) -> Started:
        raise AssertionError("a done step never repeats")


def test_step_start_on_a_done_plan_admits_and_launches_implement(
    registered: sqlite3.Connection, planned: str, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    launcher, never = Launcher(), Never()
    ports = StartPorts(AttemptStore(lambda: registered), never, launcher, lambda: 10, never,
                       advancing(registered, tmp_path, checkouts, slot_files))
    started = start(ports, StartRequest("tl-1", "tasks", "/tracker", slot.repo.path, "chosen", "high", 1))
    assert isinstance(started, Started) and (started.status, started.step, started.existing) == ("started", "implement", False)
    assert launcher.calls == ["tl-1"]
    again = start(ports, StartRequest("tl-1", "tasks", "/tracker", slot.repo.path, "chosen", "high", 1))
    assert isinstance(again, Started) and again.attempt_id == started.attempt_id and again.status == "relaunched"


V11 = "INSERT INTO attempt (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,input_path,"
V11 += "input_digest,schema_version,model,effort,sandbox,deadline,number,seq,slot_head,previous_attempt_id,repeat_reason,after_commit) "
V11 += "VALUES (?,?,1,?,'beads','tasks','tl-1','/t','r','s1','i','d',1,'m','e','workspace-write',100,?,?,?,?,?,?)"
SHA = "a" * 40


@pytest.mark.parametrize(("step", "number", "after", "ok"), [
    ("implement", 1, SHA, True), ("implement", 1, None, False), ("plan", 1, None, True), ("plan", 1, SHA, False),
    ("implement", 2, None, True), ("implement", 2, SHA, False), ("implement", 1, "a" * 39, False), ("review", 1, SHA, False),
])
def test_v11_attempt_checks(factory: sqlite3.Connection, step: str, number: int, after: str | None, ok: bool) -> None:
    """Attempt 1 of every later step names the previous step's X; a plan attempt and every repeat name none."""
    if number == 2:
        factory.execute(V11, ("p", "pt", step, 1, 1, SHA, None, None, SHA if step != "plan" else None))
    values = ("n", "nt", step, number, 2, SHA, "p" if number == 2 else None, "unsafe" if number == 2 else None, after)
    if ok:
        factory.execute(V11, values)
    else:
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            factory.execute(V11, values)


SETUP = "INSERT INTO setup_run (attempt_id,run,dispatch_token,generation,commit_sha,digest,started_at,ended_at,conclusion) "
SETUP += "VALUES ('p',?,'pt',1,?,?,1,?,?)"


@pytest.mark.parametrize(("run", "commit", "digest", "ended", "conclusion", "ok"), [
    (1, SHA, "d" * 64, None, None, True), (2, SHA, "d" * 64, 2.0, "passed", True), (0, SHA, "d" * 64, None, None, False),
    (1, "a" * 12, "d" * 64, None, None, False), (1, SHA, "d" * 63, None, None, False), (1, SHA, "d" * 64, 2.0, None, False),
    (1, SHA, "d" * 64, None, "failed", False), (1, SHA, "d" * 64, 2.0, "ok", False),
])
def test_v11_setup_run_checks(
    factory: sqlite3.Connection, run: int, commit: str, digest: str, ended: float | None, conclusion: str | None, ok: bool
) -> None:
    factory.execute(V11, ("p", "pt", "plan", 1, 1, SHA, None, None, None))
    values = (run, commit, digest, ended, conclusion)
    if ok:
        factory.execute(SETUP, values)
    else:
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            factory.execute(SETUP, values)
