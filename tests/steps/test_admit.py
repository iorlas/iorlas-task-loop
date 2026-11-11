"""Admission through real SQLite, real files, the owning Git and task-read fakes, and a local claim double."""

import json
import sqlite3
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

import pytest
from any_agent import RunOutcome, Summary
from any_agent.procs import Worker
from any_agent.testing import FakeRun
from beads_client import Bd, BdError, Bead
from beads_client.testing import FakeTaskReadClient, Script
from git_porcelain.testing import FakeRemote, FakeRepo
from sqlite_store import Store, begin_immediate

from taskloop.admit import AdmitRefused, AdmitRequest, AdmitResult, Admitted, AdmitUnavailable, AttemptAdmission
from taskloop.attempt import Attempts
from taskloop.attempt_store import AttemptStore, StoreRefused
from taskloop.attempt_types import AttemptKey, Checkouts, FileRef, SlotFiles
from taskloop.claim_lease import BD_TIMEOUT_S
from taskloop.composition import BD_DISCOVERY, adopt_slots, open_admission, tracker_claims, tracker_located
from taskloop.evidence_files import EvidenceFiles
from taskloop.factory_schema import SCHEMA
from taskloop.slot_lock import custody
from taskloop.slot_release import NotReleased, Released, SlotRelease
from taskloop.slots import adopt
from taskloop.task import TaskBinding, TaskInspection, TaskScope
from taskloop.tracker import inspect_task

WORKER = Worker(pid=42, pgid=42, start="native-start", boot="boot")
ENTRY = (7, "entry-start", "boot")
P = "docs/design/tl-1/plan.md"
PLAN = {"disposition": "planned", "plan_path": P, "paths": [P], "message": "Plan tl-1", "explanation": "Plan written"}
TASKS = FakeTaskReadClient(
    [
        Bead("tl-1", title="Plan it", description="Do the thing", acceptance_criteria="It is done"),
        Bead("tl-2", title="Other repo"),
        Bead("tl-3", title="Unencodable \ud800"),
    ]
)


class SpyFiles(EvidenceFiles):
    """The real file owner, remembering which input each admission wrote."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.inputs: list[FileRef] = []

    def put_input(self, key: AttemptKey, text: str) -> FileRef:
        ref = super().put_input(key, text)
        self.inputs.append(ref)
        return ref


class Tracker:
    """A local claim double: beads_client ships no semantic claim fake (its Script is checked separately below)."""

    def __init__(self, con: sqlite3.Connection, artifacts: Path, *, claim: bool | BdError = True, unclaim: bool | BdError = True) -> None:
        self.con, self.files, self.claimed, self.released = con, SpyFiles(artifacts), claim, unclaim
        self.calls: list[str] = []
        self.during: Callable[[], object] = lambda: None

    def claim(self, tracker_root: str, task_id: str) -> bool:
        assert not self.con.in_transaction, "the claim must be outside any transaction"
        assert len(self.files.inputs) == 1 + self.calls.count("claim:" + task_id), "this admission wrote its input first"
        bead = TASKS.show(task_id)
        assert bead is not None and self.files.read(self.files.inputs[-1]).startswith(bead.title)
        self.calls.append("claim:" + task_id)
        self.during()
        if isinstance(self.claimed, BdError):
            raise self.claimed
        return self.claimed

    def unclaim(self, tracker_root: str, task_id: str) -> bool:
        self.calls.append("unclaim:" + task_id)
        if isinstance(self.released, BdError):
            raise self.released
        return self.released


def tasks(task_id: str, backlog: str, tracker_root: str) -> TaskInspection:
    return inspect_task(TaskBinding(TaskScope(backlog), Path(tracker_root)), TASKS, task_id)


def slots(con: sqlite3.Connection, repo: FakeRepo, root: Path, count: int) -> None:
    """A person's `git worktree add --detach` at each derived path, then adoption."""
    for number in range(1, count + 1):
        repo.add_worktree(root.resolve() / repo.identity().key / f"s{number}", "HEAD")
    adopt(lambda: con, begin_immediate, repo, root, count)


def request(tmp_path: Path, repo: FakeRepo, *, deadline: float = 100, model: str = "chosen", task_id: str = "tl-1") -> AdmitRequest:
    return AdmitRequest(task_id, "tasks", str(tmp_path), repo.path, model, "high", "workspace-write", deadline)


def time() -> float:
    return 10


def unlocked(_cwd: str) -> bool:
    """The free rule's lock probe: no other holder."""
    return True


def admission(con: sqlite3.Connection, tmp_path: Path, tracker: Tracker, *repos: FakeRepo) -> AttemptAdmission:
    by_path = {repo.path: repo for repo in repos}
    return AttemptAdmission(
        lambda: con, begin_immediate, tracker.files, tasks, by_path.__getitem__, tracker.claim, tracker.unclaim, time, unlocked
    )


def admit(con: sqlite3.Connection, tmp_path: Path, repo: FakeRepo, tracker: Tracker | None = None) -> AdmitResult:
    tracker = tracker or Tracker(con, tmp_path / "artifacts")
    return admission(con, tmp_path, tracker, repo).admit(request(tmp_path, repo))


def breaking(error: BaseException) -> Callable[[sqlite3.Connection], AbstractContextManager[None]]:
    """A writer transaction that fails on entry, with nothing written."""

    @contextmanager
    def begin(_con: sqlite3.Connection) -> Generator[None]:
        raise error
        yield

    return begin


def attempts(con: sqlite3.Connection, tmp_path: Path, run: FakeRun, checkouts: Checkouts, files: SlotFiles) -> Attempts:
    artifacts = EvidenceFiles(tmp_path / "artifacts")
    return Attempts(AttemptStore(lambda: con), artifacts, lambda: ("/bin/codex", {}), run, lambda: 10, checkouts, files)


def rows(con: sqlite3.Connection) -> tuple[int, int]:
    return con.execute("SELECT (SELECT count(*) FROM reservation),(SELECT count(*) FROM attempt)").fetchone()


def test_admitted_rows_are_what_the_body_loads_and_stay_unregistered(
    factory: sqlite3.Connection, repo: FakeRepo, root: Path, tmp_path: Path, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    slots(factory, repo, root, 2)
    result = admit(factory, tmp_path, repo)
    assert isinstance(result, Admitted) and result.slot == "s1" and result.key.reservation_generation == 1
    key, repo_id = result.key, repo.identity().key
    cwd = str(root.resolve() / repo_id / "s1")
    assert factory.execute("SELECT * FROM reservation").fetchall() == [("s1", repo_id, cwd, 1, key.attempt_id)]
    columns = "backlog,task_id,repo_id,slot,model,phase,entry_pid,entry_start,entry_boot"
    stored = factory.execute(f"SELECT {columns} FROM attempt").fetchone()
    assert stored == ("tasks", "tl-1", repo_id, "s1", "chosen", "admitted", None, None, None)
    assert AttemptStore(lambda: factory).tracker_root(key) == str(tmp_path.resolve())  # the claimed root, renewed by the entry
    with pytest.raises(StoreRefused, match="unregistered_entry"):
        AttemptStore(lambda: factory).load(key)
    run = FakeRun(RunOutcome(rc=0, worker=WORKER))
    refused = attempts(factory, tmp_path, run, checkouts, slot_files).execute(key, ENTRY)
    assert (refused.status, refused.reason) == ("refused", "unregistered_entry") and run.calls == []
    pending = attempts(factory, tmp_path, run, checkouts, slot_files).collect(key)
    assert (pending.status, pending.reason) == ("pending", "admitted")


def test_admit_then_register_entry_then_execute_by_that_entry_is_collected(
    factory: sqlite3.Connection, repo: FakeRepo, root: Path, tmp_path: Path, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    slots(factory, repo, root, 1)
    result = admit(factory, tmp_path, repo)
    assert isinstance(result, Admitted)
    store = AttemptStore(lambda: factory)
    assert store.register_entry(result.key, ENTRY, time()) == "accepted"
    run = FakeRun(RunOutcome(rc=0, worker=WORKER, summary=Summary(text=json.dumps(PLAN), rc=0, stands=True)))
    other = attempts(factory, tmp_path, run, checkouts, slot_files).execute(result.key, (8, "entry-start", "boot"))
    assert (other.status, other.reason) == ("refused", "not_entry") and run.calls == []
    collected = attempts(factory, tmp_path, run, checkouts, slot_files).execute(result.key, ENTRY)
    assert (collected.status, collected.reason) == ("pending", "verification") and len(run.calls) == 1
    _harness, spec, _timeout, _hooks = run.calls[0]
    assert spec.cwd == str(root.resolve() / repo.identity().key / "s1")
    prompt = spec.stdin + " ".join(spec.argv)
    assert "Do the thing" in prompt and "It is done" in prompt
    closing = "First read `docs/design/tl-1/plan.md` if it exists. If it is still valid for the task and the code as they are now"
    assert closing in prompt and "answer `unchanged`" in prompt and "do not run `git add`, `git commit`, `git push`" in prompt
    assert "list in `paths` every file you want committed and give a one-line commit `message`" in prompt
    assert prompt.index("It is done") < prompt.index(closing)  # the fixed closing words come last, in the admitted input


@pytest.mark.parametrize("case", ["none_adopted", "held", "dirty", "attached", "main_only"])
def test_no_free_slot_refuses_before_any_effect(factory: sqlite3.Connection, repo: FakeRepo, root: Path, tmp_path: Path, case: str) -> None:
    if case != "none_adopted":
        slots(factory, repo, root, 1)
    path = root.resolve() / repo.identity().key / "s1"
    if case == "held":
        held = "INSERT INTO reservation (slot,repo_id,cwd,generation,attempt_id) VALUES ('s1',?,'x',1,'x')"
        factory.execute(held, (repo.identity().key,))
    elif case == "dirty":
        repo.worktree(path).write_file("scratch", "x")
    elif case == "attached":  # adopted while detached, then a branch was checked out there
        repo.worktree(path).checkout_new("task/tl-1")
    elif case == "main_only":
        repo.drop_worktree(path)
    tracker = Tracker(factory, tmp_path / "artifacts")
    result = admit(factory, tmp_path, repo, tracker)
    assert isinstance(result, AdmitRefused) and result.reason == "no_free_slot"
    assert len(result.slots) == (0 if case == "none_adopted" else 1)
    assert tracker.calls == [] and not (tmp_path / "artifacts").exists()
    assert rows(factory) == ((1 if case == "held" else 0), 0)


def test_a_slot_taken_between_observe_and_commit_moves_to_the_next_or_refuses(
    factory: sqlite3.Connection, repo: FakeRepo, root: Path, tmp_path: Path
) -> None:
    slots(factory, repo, root, 2)
    repo_id = repo.identity().key
    tracker = Tracker(factory, tmp_path / "artifacts")
    taken = "INSERT INTO reservation (slot,repo_id,cwd,generation,attempt_id) VALUES (?,?,'x',1,?)"
    tracker.during = lambda: factory.execute(taken, ("s1", repo_id, "other"))
    result = admit(factory, tmp_path, repo, tracker)
    assert isinstance(result, Admitted) and result.slot == "s2" and tracker.calls == ["claim:tl-1"]
    factory.execute("DELETE FROM attempt")
    factory.execute("DELETE FROM reservation WHERE slot='s2'")
    tracker = Tracker(factory, tmp_path / "artifacts")
    tracker.during = lambda: factory.execute(taken, ("s2", repo_id, "third"))
    raced = admit(factory, tmp_path, repo, tracker)
    assert isinstance(raced, AdmitRefused) and raced.reason == "no_free_slot" and not raced.claim_leaked
    assert tracker.calls == ["claim:tl-1", "unclaim:tl-1"] and rows(factory) == (2, 0)


@pytest.mark.parametrize("count", [1, 2])
def test_one_attempt_per_task_even_when_every_slot_is_held(
    factory: sqlite3.Connection, repo: FakeRepo, root: Path, tmp_path: Path, count: int
) -> None:
    slots(factory, repo, root, count)
    assert isinstance(admit(factory, tmp_path, repo), Admitted)
    tracker = Tracker(factory, tmp_path / "artifacts")
    again = admit(factory, tmp_path, repo, tracker)
    assert again == AdmitRefused("task_attempted") and tracker.calls == [] and rows(factory) == (1, 1)


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (None, AdmitRefused("task_attempted")),
        (sqlite3.OperationalError("database is locked"), AdmitUnavailable("store", False, "OperationalError: database is locked")),
        (sqlite3.IntegrityError("mismatch"), AdmitRefused("constraint", detail="IntegrityError: mismatch")),
        (BdError("other", "down"), AdmitUnavailable("tracker", False, "BdError: other: down")),
    ],
)
def test_a_concurrent_admission_of_the_task_keeps_the_winners_claim_with_one_slot(
    factory: sqlite3.Connection, repo: FakeRepo, root: Path, tmp_path: Path, failure: Exception | None, expected: AdmitResult
) -> None:
    """Both claim (Bd.claim is idempotent for the actor); the winner commits first; the loser must never unclaim."""
    slots(factory, repo, root, 1)
    winner = Tracker(factory, tmp_path / "artifacts")
    loser = Tracker(factory, tmp_path / "artifacts", claim=failure if isinstance(failure, BdError) else True)
    loser.during = lambda: admission(factory, tmp_path, winner, repo).admit(request(tmp_path, repo))
    admitter = admission(factory, tmp_path, loser, repo)
    if isinstance(failure, sqlite3.Error):
        admitter.begin = breaking(failure)
    assert admitter.admit(request(tmp_path, repo)) == expected
    assert winner.calls == ["claim:tl-1"] and loser.calls == ["claim:tl-1"] and rows(factory) == (1, 1)


@pytest.mark.parametrize(
    ("claim", "unclaim", "expected", "released"),
    [
        (False, True, AdmitRefused("claimed_elsewhere"), False),
        (BdError("other", "down"), True, AdmitUnavailable("tracker", False, "BdError: other: down"), True),
        (BdError("timeout", "slow"), False, AdmitUnavailable("tracker", True, "BdError: timeout: slow"), True),
        (BdError("other", "down"), BdError("timeout"), AdmitUnavailable("tracker", True, "BdError: other: down"), True),
        (BdError("not_found", "gone"), True, AdmitUnavailable("tracker", False, "BdError: not_found: gone"), False),
        (BdError("missing_binary", "no bd"), True, AdmitUnavailable("tracker", False, "BdError: missing_binary: no bd"), False),
    ],
)
def test_claim_refusal_and_unknown_claim(
    factory: sqlite3.Connection,
    repo: FakeRepo,
    root: Path,
    tmp_path: Path,
    claim: bool | BdError,
    unclaim: bool | BdError,
    expected: AdmitResult,
    released: bool,
) -> None:
    slots(factory, repo, root, 1)
    tracker = Tracker(factory, tmp_path / "artifacts", claim=claim, unclaim=unclaim)
    assert admit(factory, tmp_path, repo, tracker) == expected
    assert tracker.calls == ["claim:tl-1"] + (["unclaim:tl-1"] if released else [])
    assert rows(factory) == (0, 0)


@pytest.mark.parametrize("unclaim", [True, False])
def test_constraint_is_caught_after_rollback_and_compensated(
    factory: sqlite3.Connection, repo: FakeRepo, root: Path, tmp_path: Path, unclaim: bool
) -> None:
    slots(factory, repo, root, 1)
    factory.execute("CREATE TEMP TRIGGER mismatch BEFORE INSERT ON attempt BEGIN SELECT RAISE(ABORT, 'schema mismatch'); END")
    tracker = Tracker(factory, tmp_path / "artifacts", unclaim=unclaim)
    result = admit(factory, tmp_path, repo, tracker)
    assert isinstance(result, AdmitRefused) and result.reason == "constraint" and result.claim_leaked is not unclaim
    assert result.detail == "IntegrityError: schema mismatch"
    assert tracker.calls == ["claim:tl-1", "unclaim:tl-1"] and rows(factory) == (0, 0)


@pytest.mark.parametrize("unclaim", [True, False, BdError("timeout")])
def test_store_failure_after_the_claim_is_compensated(
    factory: sqlite3.Connection, repo: FakeRepo, root: Path, tmp_path: Path, unclaim: bool | BdError
) -> None:
    slots(factory, repo, root, 1)
    tracker = Tracker(factory, tmp_path / "artifacts", unclaim=unclaim)
    admitter = admission(factory, tmp_path, tracker, repo)
    admitter.begin = breaking(sqlite3.OperationalError("database is locked"))
    leaked = unclaim is not True
    assert admitter.admit(request(tmp_path, repo)) == AdmitUnavailable("store", leaked, "OperationalError: database is locked")
    assert tracker.calls == ["claim:tl-1", "unclaim:tl-1"] and rows(factory) == (0, 0)


def test_an_unreadable_attempt_check_keeps_the_claim_and_reports_it_leaked(
    factory: sqlite3.Connection, repo: FakeRepo, root: Path, tmp_path: Path
) -> None:
    slots(factory, repo, root, 1)
    tracker = Tracker(factory, tmp_path / "artifacts")
    tracker.during = lambda: factory.execute("DROP TABLE attempt")
    result = admit(factory, tmp_path, repo, tracker)
    assert isinstance(result, AdmitUnavailable) and result.what == "store" and result.claim_leaked
    assert result.detail == "OperationalError: no such table: attempt"
    assert tracker.calls == ["claim:tl-1"] and factory.execute("SELECT count(*) FROM reservation").fetchone() == (0,)


def test_an_unexpected_failure_compensates_then_propagates(factory: sqlite3.Connection, repo: FakeRepo, root: Path, tmp_path: Path) -> None:
    slots(factory, repo, root, 1)
    tracker = Tracker(factory, tmp_path / "artifacts")
    admitter = admission(factory, tmp_path, tracker, repo)
    admitter.begin = breaking(KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        admitter.admit(request(tmp_path, repo))
    assert tracker.calls == ["claim:tl-1", "unclaim:tl-1"] and rows(factory) == (0, 0)


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ("model", "choices"),
        ("nan", "deadline"),
        ("inf", "deadline"),
        ("deadline", "expired"),
        ("task", "task"),
        ("checkout", "checkout"),
        ("input", "input"),
        ("store", "store"),
        ("version", "store"),
        ("reservations", "store"),
    ],
)
def test_invalid_request_or_store_refuses_before_any_claim(
    factory: sqlite3.Connection, repo: FakeRepo, root: Path, tmp_path: Path, change: str, expected: str
) -> None:
    slots(factory, repo, root, 1)
    tracker = Tracker(factory, tmp_path / "artifacts")
    deadline = {"nan": float("nan"), "inf": float("inf"), "deadline": 5.0}.get(change, 100.0)
    wanted = request(tmp_path, repo, model=" " if change == "model" else "chosen", deadline=deadline)
    if change in ("task", "input"):
        wanted = request(tmp_path, repo, task_id="tl-404" if change == "task" else "tl-3")
    elif change == "checkout":
        wanted = AdmitRequest("tl-1", "tasks", str(tmp_path), repo.path / "subdir", "chosen", "high", "workspace-write", 100)
    elif change == "version":
        factory.execute("PRAGMA user_version=1")
    elif change == "reservations":
        factory.execute("DROP TABLE reservation")
    admitter = admission(factory, tmp_path, tracker, repo)
    if change == "store":
        admitter.connect = lambda: None
    admitter.checkouts = lambda _path: repo
    result = admitter.admit(wanted)
    assert (result.reason if isinstance(result, AdmitRefused) else getattr(result, "what", None)) == expected
    assert tracker.calls == [] and tracker.files.inputs == []
    assert change == "input" or not (tmp_path / "artifacts").exists()


def test_a_v1_file_database_is_refused_by_the_real_store(repo: FakeRepo, tmp_path: Path) -> None:
    path = tmp_path / "factory.db"
    old = sqlite3.connect(path, isolation_level=None)
    old.execute("CREATE TABLE reservation (slot TEXT PRIMARY KEY)")
    old.execute("PRAGMA user_version=1")
    old.close()
    store = Store(SCHEMA)
    unused = sqlite3.connect(":memory:")
    tracker = Tracker(unused, tmp_path / "artifacts")
    admitter = admission(unused, tmp_path, tracker, repo)
    admitter.connect, admitter.begin = (lambda: store.shared_rw(path)), store.begin_immediate
    result = admitter.admit(request(tmp_path, repo))
    assert isinstance(result, AdmitUnavailable) and result.what == "store" and result.detail.startswith("SchemaError:")
    assert tracker.calls == []
    store.close_shared()
    unused.close()


def test_composition_constructs_without_running_git_or_bd(tmp_path: Path) -> None:
    assert isinstance(open_admission(tmp_path / "factory.db", tmp_path / "artifacts"), AttemptAdmission)
    with pytest.raises(ValueError, match="at least 1"):  # refused before the real Git boundary is asked anything
        adopt_slots(tmp_path / "factory.db", tmp_path, tmp_path / "slots", 0)
    assert not (tmp_path / "factory.db").exists()


def test_two_repos_both_get_s1_and_the_fence_is_per_repo(factory: sqlite3.Connection, repo: FakeRepo, root: Path, tmp_path: Path) -> None:
    remote = FakeRemote("https://example.invalid/other.git")
    remote.advance("main", {"README": "two"})
    other = FakeRepo.clone(remote, tmp_path / "other")
    keys: list[AttemptKey] = []
    for each, task_id in ((repo, "tl-1"), (other, "tl-2")):
        slots(factory, each, root, 1)
        tracker = Tracker(factory, tmp_path / "artifacts")
        result = admission(factory, tmp_path, tracker, each).admit(request(tmp_path, each, task_id=task_id))
        assert isinstance(result, Admitted) and result.slot == "s1"
        assert AttemptStore(lambda: factory).register_entry(result.key, ENTRY, time()) == "accepted"
        keys.append(result.key)
    store = AttemptStore(lambda: factory)
    assert all(store.load(key) is not None for key in keys)
    factory.execute("DELETE FROM reservation WHERE repo_id=?", (repo.identity().key,))  # another repo's s1 must not satisfy the fence
    with pytest.raises(StoreRefused, match="stale_reservation"):
        store.load(keys[0])


def test_composition_claims_through_bd_and_unclaim_is_fenced_never_forced(tmp_path: Path) -> None:
    script = Script()
    claims = tracker_claims(script)
    assert claims.claim(str(tmp_path), "tl-1") and claims.unclaim(str(tmp_path), "tl-1")
    first, second = (argv[1:] for argv in script.calls)
    assert first == ["--actor", "taskloop", "update", "tl-1", "--claim", "--json"]
    assert second == ["--actor", "taskloop", "unclaim", "tl-1", "--if-assignee", "taskloop", "--json"]


# bd 1.3.1's measured heartbeat replies (scratch tracker, 2026-11-10): JSON on stdout, exit 1, nothing on stderr.
TAKEN = '{"error": "heartbeat tl-1: issue already claimed by someone", "schema_version": 1}'
REVERTED = '{"error": "heartbeat tl-1: issue not claimable: tl-1 status open", "schema_version": 1}'
CLOSED = '{"error": "heartbeat tl-1: issue not claimable: tl-1 status closed", "schema_version": 1}'
DELETED = '{"error": "resolving tl-1: no issue found matching \\"tl-1\\"", "schema_version": 1}'


@pytest.mark.parametrize(
    ("out", "err", "code", "beat"),
    [
        ('{"id": "tl-1", "owner": "taskloop", "schema_version": 1, "status": "heartbeat"}', "", 0, "held"),
        (TAKEN, "", 1, "lost"),
        (REVERTED, "", 1, "lost"),
        (CLOSED, "", 1, "lost"),
        ("", "", 13, "lost"),
        ("", "bd: no answer in 30.0s", 124, "unrenewed"),
        ("", "bd: [Errno 2] No such file or directory", 127, "unrenewed"),
        (DELETED, "", 1, "lost"),
        ('{"error": "database is down", "schema_version": 1}', "", 1, "unrenewed"),
    ],
    ids=["renewed", "taken", "reverted", "closed", "precondition", "timeout", "missing_binary", "deleted", "other"],
)
def test_composition_heartbeats_through_bd_and_maps_its_words(tmp_path: Path, out: str, err: str, code: int, beat: str) -> None:
    script = Script().say(out, err, code)
    assert tracker_claims(script).heartbeat_for(str(tmp_path), "tl-1")() == beat
    assert [argv[1:] for argv in script.calls] == [["--actor", "taskloop", "heartbeat", "tl-1", "--json"]]


def test_composition_caps_each_heartbeat_at_one_bd_call_of_bd_timeout_and_claims_with_the_defaults(tmp_path: Path) -> None:
    built: list[dict[str, object]] = []

    class Recorded(Bd):
        def __init__(self, actor: str, cwd: str | None = None, **options: object) -> None:
            built.append({"actor": actor, "cwd": cwd} | {key: value for key, value in options.items() if key != "run"})
            super().__init__(actor, cwd, run=Script())

    claims = tracker_claims(Script(), client=Recorded)
    claims.heartbeat_for(str(tmp_path / "x" / ".."), "tl-1")
    claims.claim(str(tmp_path), "tl-1")
    root = str(tmp_path.resolve())
    assert built == [
        {"actor": "taskloop", "cwd": root, "timeout": BD_TIMEOUT_S, "lock_retries": 0},
        {"actor": "taskloop", "cwd": root},
    ]


def test_bd_location_overrides_are_dropped_so_the_tracker_root_decides() -> None:
    environ = {"BEADS_DIR": "/elsewhere/.beads", "BEADS_DB": "/x", "BD_DB": "/y", "BEADS_ACTOR": "someone", "PATH": "/bin"}
    tracker_located(environ)
    assert environ == {"BEADS_ACTOR": "someone", "PATH": "/bin"} and set(BD_DISCOVERY) == {"BEADS_DIR", "BEADS_DB", "BD_DB"}


def generations(con: sqlite3.Connection) -> list[tuple[object, ...]]:
    return con.execute("SELECT name,generation FROM slot ORDER BY name").fetchall()


def test_after_an_abandon_the_task_is_admitted_afresh_on_its_existing_branch_with_a_new_generation(
    factory: sqlite3.Connection, repo: FakeRepo, root: Path, tmp_path: Path, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    slots(factory, repo, root, 2)
    tracker = Tracker(factory, tmp_path / "artifacts")
    first = admit(factory, tmp_path, repo, tracker)
    assert isinstance(first, Admitted) and first.key.reservation_generation == 1 and generations(factory) == [("s1", 1), ("s2", 0)]
    path = root.resolve() / repo.identity().key / "s1"
    d = factory.execute("SELECT slot_head FROM attempt").fetchone()[0]
    repo.worktree(path).take_branch("task/tl-1", "HEAD", mode="resume")  # as its entry prepared it
    release = SlotRelease(AttemptStore(lambda: factory), checkouts, slot_files, lambda _entry: "gone", lambda _w: True, custody,
                          tracker.unclaim, time)
    assert release.release(first.key, True) == Released("s1", d, True, "unclaimed", True)
    again = admit(factory, tmp_path, repo, tracker)
    assert isinstance(again, Admitted) and again.slot == "s1" and again.key.reservation_generation == 2  # never reused
    rows = factory.execute("SELECT attempt_id,number,seq,previous_attempt_id,slot_head FROM attempt ORDER BY seq").fetchall()
    assert rows == [(first.key.attempt_id, 1, 1, None, d), (again.key.attempt_id, 1, 2, None, d)]
    assert generations(factory) == [("s1", 2), ("s2", 0)] and tracker.calls == ["claim:tl-1", "unclaim:tl-1", "claim:tl-1"]
    assert factory.execute("SELECT generation,attempt_id FROM reservation").fetchall() == [(2, again.key.attempt_id)]
    assert AttemptStore(lambda: factory).attempt_of("tasks", "tl-1") == (again.key, "admitted", None)


def test_a_settled_release_still_answers_the_task(factory: sqlite3.Connection, repo: FakeRepo, root: Path, tmp_path: Path) -> None:
    slots(factory, repo, root, 2)
    first = admit(factory, tmp_path, repo)
    assert isinstance(first, Admitted)
    factory.execute("DELETE FROM reservation")
    factory.execute("INSERT INTO slot_release SELECT attempt_id,dispatch_token,generation,slot_head,1,0,'kept' FROM attempt")
    tracker = Tracker(factory, tmp_path / "artifacts")
    assert admit(factory, tmp_path, repo, tracker) == AdmitRefused("task_attempted") and tracker.calls == []
    factory.execute("UPDATE slot_release SET abandoned=1,claim='unclaimed'")
    assert isinstance(admit(factory, tmp_path, repo, tracker), Admitted)


def test_a_slot_whose_counter_reached_the_new_generation_is_skipped(
    factory: sqlite3.Connection, repo: FakeRepo, root: Path, tmp_path: Path
) -> None:
    """Issued above every observed-free slot's counter; under the write lock a slot whose counter moved up meanwhile is
    passed over for the next, so no generation is issued twice for a slot."""
    slots(factory, repo, root, 2)
    tracker = Tracker(factory, tmp_path / "artifacts")
    tracker.during = lambda: factory.execute("UPDATE slot SET generation=1 WHERE name='s1'")
    result = admit(factory, tmp_path, repo, tracker)
    assert isinstance(result, Admitted) and (result.slot, result.key.reservation_generation) == ("s2", 1)
    assert generations(factory) == [("s1", 1), ("s2", 1)]


def test_an_abandon_still_returning_its_claim_keeps_the_task_attempted(
    factory: sqlite3.Connection, repo: FakeRepo, root: Path, tmp_path: Path, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    """While the claim is `unclaiming`, a fresh admission would claim the task only for the abandon's own unclaim (now, or
    on its retry) to take it back: it is refused `task_attempted` before any claim, during the unclaim and after a
    failed one; once the claim is returned, the task is admitted afresh."""
    slots(factory, repo, root, 1)
    first = admit(factory, tmp_path, repo)
    assert isinstance(first, Admitted)
    raced: list[AdmitResult] = []
    contender = Tracker(factory, tmp_path / "artifacts")

    def unclaim(_root: str, _task: str) -> bool:  # a concurrent start admits while bd returns the claim
        raced.append(admit(factory, tmp_path, repo, contender))
        if len(raced) == 1:
            raise BdError("timeout", "slow")
        return True

    release = SlotRelease(
        AttemptStore(lambda: factory), checkouts, slot_files, lambda _entry: "gone", lambda _w: True, custody, unclaim, time
    )
    failed = release.release(first.key, True)
    assert isinstance(failed, NotReleased) and failed.detail.endswith("The reservation was removed, no Git write.")
    assert admit(factory, tmp_path, repo, contender) == AdmitRefused("task_attempted")
    assert release.release(first.key, True) == Released("s1", None, False, "unclaimed", True)
    assert raced == [AdmitRefused("task_attempted")] * 2 and contender.calls == []
    assert isinstance(admit(factory, tmp_path, repo, contender), Admitted) and contender.calls == ["claim:tl-1"]
