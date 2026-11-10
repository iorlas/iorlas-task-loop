"""The entry process body on a real factory.db file, its own real process identity, the owning agent fake and the fake slot."""

import dataclasses
import json
import os
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path

import pytest
from any_agent import Harness, LaunchSpec, RunHooks, RunOutcome, Summary
from any_agent.procs import Worker
from any_agent.testing import FakeRun
from git_porcelain import Repo
from git_porcelain.testing import FakeWorktree
from sqlite_store import Store
from stream_proc import ProcessObservation, inspect_process

from taskloop.attempt_entry import EntryArgs, arguments, enter, main
from taskloop.claim_lease import Beat, Heartbeat
from taskloop.plan import PlanAttempts
from taskloop.plan_files import EvidenceError, PlanFiles
from taskloop.plan_schema import SCHEMA
from taskloop.plan_store import PlanStore
from taskloop.plan_types import AttemptKey, Checkouts, Evidence, SlotFiles
from taskloop.slot_lock import SlotBusy, acquire, lock_path

KEY = AttemptKey("attempt", "dispatch", 1)
WORKER = Worker(pid=42, pgid=42, start="native-start", boot="boot")
P = "docs/design/tl-1/plan.md"
PLAN = {"disposition": "planned", "plan_path": P, "paths": [P], "message": "Plan tl-1", "explanation": "Plan written"}


def me() -> tuple[int, str, str]:
    observation = inspect_process(os.getpid())
    assert observation.kind == "matching" and observation.identity is not None
    return observation.identity.pid, observation.identity.start, observation.identity.boot


class FlakyFiles(PlanFiles):
    """The real file owner whose evidence capture fails the first `failures` times."""

    def __init__(self, root: Path, failures: int) -> None:
        super().__init__(root)
        self.failures, self.captures = failures, 0

    def capture(self, key: AttemptKey, raw: RunOutcome) -> Evidence:
        self.captures += 1
        if self.captures <= self.failures:
            raise EvidenceError("Cannot capture artifact")
        return super().capture(key, raw)


class Stop:
    """The renewing thread's stop event, scripted: `wait` answers False (renew now) `rounds` times, then True (stopped).
    `set` changes nothing, so the thread always makes its scripted beats before the join returns, however late it runs."""

    def __init__(self, rounds: int) -> None:
        self.rounds, self.waits, self.set_calls = rounds, 0, 0

    def wait(self, timeout: float) -> bool:
        self.waits += 1
        return self.waits > self.rounds

    def set(self) -> None:
        self.set_calls += 1


class Entry:
    """One entry's collaborators: the run fake (with `written`, the agent first writes those files in the slot and lists
    the given paths), a counting credential source and Git view, the slot file port, a clock the wait advances, the log,
    and the claim's scripted beats (the first before the agent, then one per `rounds` of the renewing thread)."""

    def __init__(
        self,
        db: Path,
        checkouts: Checkouts,
        slot_files: SlotFiles,
        entry: tuple[int, str, str] | None = None,
        failures: int = 0,
        wait_to: float = 10,
        rc: int = 0,
        text: str = "",
        written: tuple[FakeWorktree, dict[str, str], list[str]] | None = None,
        beats: tuple[Beat | Exception, ...] = ("held",),
        rounds: int = 0,
    ) -> None:
        self.db, self.now, self.wait_to, self.git, self.written = db, 10.0, wait_to, checkouts, written
        self.beats, self.stop = list(beats), Stop(rounds)
        self.renewed: list[tuple[str, str]] = []
        self.slot_files = slot_files
        self.git_opens = 0
        if entry is not None:
            store = Store(SCHEMA)
            con = store.open_rw(db)
            assert con is not None
            assert PlanStore(lambda: con, store.begin_immediate).register_entry(KEY, entry, 10) == "accepted"
            con.close()
        self.files = FlakyFiles(db.parent, failures)
        summary = Summary(text=text or json.dumps(PLAN), rc=rc, stands=True, vendor="request failed SECRET=credential" if rc else "")
        self.outcome = RunOutcome(rc=rc, worker=WORKER, summary=summary, out="agent says SECRET=credential")
        self.run = FakeRun(self.outcome)
        self.credential_calls = 0
        self.waits: list[float] = []
        self.lines: list[str] = []
        self.opened: list[tuple[Path, Path]] = []
        self.observed: list[Worker] = []

    def credentials(self) -> tuple[str, dict[str, str]]:
        self.credential_calls += 1
        return "/bin/codex", {"SECRET": "credential"}

    def checkouts(self, path: Path) -> Repo:
        self.git_opens += 1
        return self.git(path)

    def execution(self, harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        if self.written is not None:
            slot, files, paths = self.written
            for path, text in files.items():
                slot.write_file(path, text)
            summary = dataclasses.replace(self.outcome.summary, text=json.dumps(PLAN | {"paths": paths}))
            self.run = FakeRun(dataclasses.replace(self.outcome, summary=summary))
        return self.run(harness, spec, timeout, hooks)

    def attempts(self, database: Path, artifacts: Path) -> PlanAttempts:
        self.opened.append((database, artifacts))
        store = Store(SCHEMA)
        connect = PlanStore(lambda: store.shared_rw(database), store.begin_immediate)
        return PlanAttempts(connect, self.files, self.credentials, self.execution, self.clock, self.checkouts, self.slot_files)

    def clock(self) -> float:
        return self.now

    def gone(self, worker: Worker) -> bool:
        self.observed.append(worker)
        return True

    def wait(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.now = self.wait_to

    def heartbeat_for(self, tracker_root: str, task_id: str) -> Heartbeat:
        def beat() -> Beat:
            self.renewed.append((tracker_root, task_id))
            answer = self.beats.pop(0) if len(self.beats) > 1 else self.beats[0]
            if isinstance(answer, Exception):
                raise answer
            return answer

        return beat

    def __call__(self, inspect: Callable[[int], ProcessObservation] = inspect_process, task_id: str = "tl-1") -> int:
        args = EntryArgs(self.db, self.db.parent, "tasks", task_id)
        return enter(args, self.attempts, inspect, self.clock, self.wait, self.lines.append, self.gone, self.heartbeat_for, self.stop)


NOTE = "docs/design/tl-1/note.md"


@pytest.mark.parametrize(
    ("files", "line", "code", "opens"),
    [
        ({P: "# Plan\n"}, "collected verified verify=verified claim=held", 0, 13),
        ({P: " \n"}, "collected rejected:plan_empty verify=rejected:plan_empty claim=held", 1, 13),
        ({P: "# Plan\n", NOTE: "n"}, "pending verification verify=unsettled:uncommitted claim=held", 1, 13),
        ({}, "pending verification verify=unsettled:unsafe claim=held", 1, 9),
    ],
    ids=["verified", "rejected", "uncommitted", "unsafe"],
)
def test_the_registered_entry_executes_verifies_once_and_exits_0_only_when_verified(
    admitted: Path, checkouts: Checkouts, slot_files: SlotFiles, slot: FakeWorktree, files: dict[str, str], line: str, code: int, opens: int
) -> None:
    entry = Entry(admitted, checkouts, slot_files, me(), written=(slot, files, [P]))
    assert entry() == code
    assert entry.lines == [line] and len(entry.run.calls) == 1 and entry.credential_calls == 1
    assert entry.opened == [(admitted, admitted.parent)]
    # six Git opens before dispatch (the slot read: root, slot; the branch rule: root; take_branch: slot; the slot read
    # again: root, slot); the one verification: four to commit (the staged set read before the
    # record), two for the clean check, one
    # to judge or list; the worker is observed right before each Git write (stage, record), never when the paths are unsafe
    assert entry.waits == [] and entry.git_opens == opens and entry.observed == ([] if files == {} else [WORKER, WORKER])


INCOMPLETE = "collected incomplete verify=not_applicable claim=held"


@pytest.mark.parametrize(
    ("rc", "text", "line"),
    [
        (1, "", "collected run:vendor_blip verify=not_applicable claim=held"),
        (1, json.dumps(PLAN), "collected run:vendor_blip verify=not_applicable claim=held"),
        (0, "not json", "collected answer:json_invalid verify=not_applicable claim=held"),
        (0, json.dumps(PLAN | {"disposition": "incomplete", "plan_path": None, "paths": [], "message": None}), INCOMPLETE),
        (0, json.dumps(PLAN | {"commit": "a" * 40}), "collected answer:schema_invalid verify=not_applicable claim=held"),
    ],
    ids=["failed_run_no_answer", "failed_run_valid_answer", "clean_run_bad_answer", "incomplete", "old_commit_key"],
)
def test_a_terminal_failure_is_collected_with_its_reason_and_exits_1(
    admitted: Path, checkouts: Checkouts, slot_files: SlotFiles, rc: int, text: str, line: str
) -> None:
    entry = Entry(admitted, checkouts, slot_files, me(), rc=rc, text=text)
    assert entry() == 1
    assert entry.lines == [line] and all("SECRET" not in logged and "credential" not in logged for logged in entry.lines)


@pytest.mark.parametrize("stored", [None, (1, "someone-else", "boot")])
def test_a_process_that_is_not_the_registered_entry_reads_no_credentials(
    admitted: Path, checkouts: Checkouts, slot_files: SlotFiles, stored: tuple[int, str, str] | None
) -> None:
    entry = Entry(admitted, checkouts, slot_files, stored)
    assert entry() == 1
    assert entry.lines == ["refused identity"] and entry.credential_calls == 0 and entry.run.calls == [] and entry.git_opens == 0
    assert entry.renewed == []


def test_an_unknown_own_identity_reads_no_credentials(admitted: Path, checkouts: Checkouts, slot_files: SlotFiles) -> None:
    entry = Entry(admitted, checkouts, slot_files, me())
    assert entry(lambda _pid: ProcessObservation("unknown")) == 1
    assert entry.lines == ["refused identity"] and entry.credential_calls == 0 and entry.run.calls == []


def test_an_absent_task_or_a_missing_database_runs_nothing(
    admitted: Path, checkouts: Checkouts, slot_files: SlotFiles, tmp_path: Path
) -> None:
    entry = Entry(admitted, checkouts, slot_files, me())
    assert entry(task_id="tl-9") == 1 and entry.lines == ["refused absent"]
    missing = Entry(tmp_path / "missing.db", checkouts, slot_files)
    assert missing() == 1 and missing.lines == ["refused database"]
    assert not (tmp_path / "missing.db").exists() and missing.opened == [] and missing.run.calls == []


@pytest.mark.parametrize(
    ("failures", "wait_to", "line", "waits", "captures"),
    [
        (1, 10, "unavailable evidence publish=accepted then=collected:verified verify=verified claim=held", 1, 2),
        (9, 10, "unavailable evidence publish=unavailable verify=refused:not_captured claim=held", 3, 4),
        (9, 100, "unavailable evidence verify=refused:not_captured claim=held", 1, 1),
    ],
    ids=["second_try_publishes", "three_retries_at_most", "never_past_the_deadline"],
)
def test_publication_is_retried_only_while_unavailable_and_the_agent_never_again(
    admitted: Path,
    checkouts: Checkouts,
    slot_files: SlotFiles,
    slot: FakeWorktree,
    failures: int,
    wait_to: float,
    line: str,
    waits: int,
    captures: int,
) -> None:
    entry = Entry(admitted, checkouts, slot_files, me(), failures, wait_to, written=(slot, {P: "# Plan\n"}, [P]))
    assert entry() == (0 if failures == 1 else 1)
    assert entry.lines == [line] and len(entry.waits) == waits and entry.files.captures == captures
    assert len(entry.run.calls) == 1
    assert all("credential" not in text and "SECRET" not in text for text in entry.lines)


def test_a_claim_found_lost_before_the_agent_refuses_and_runs_nothing(
    admitted: Path, checkouts: Checkouts, slot_files: SlotFiles, slot: FakeWorktree
) -> None:
    entry = Entry(admitted, checkouts, slot_files, me(), written=(slot, {P: "# Plan\n"}, [P]), beats=("lost", "held"), rounds=3)
    assert entry() == 1
    assert entry.lines == ["refused claim_lost"] and entry.renewed == [("/tracker", "tl-1")]
    assert entry.run.calls == [] and entry.credential_calls == 0 and entry.git_opens == 0 and entry.stop.waits == 0


@pytest.mark.parametrize("held", [True, False], ids=["slot_busy", "lock"])
def test_a_held_or_unlockable_slot_refuses_the_entry_before_anything_is_read_or_run(
    admitted: Path, checkouts: Checkouts, slot_files: SlotFiles, slot: FakeWorktree,
    occupy: Callable[[Path], AbstractContextManager[None]], held: bool,
) -> None:
    """Held by another entry or verify: `refused slot_busy`. A lock file that cannot be made (here `.locks` is a file):
    `refused lock`."""
    entry = Entry(admitted, checkouts, slot_files, me(), written=(slot, {P: "# Plan\n"}, [P]))
    path = lock_path(str(slot.path))
    if not held:
        path.parent.parent.mkdir(parents=True, exist_ok=True)
        path.parent.write_text("not a folder")
    with occupy(path) if held else nullcontext():
        assert entry() == 1
    assert entry.lines == ["refused slot_busy" if held else "refused lock"] and entry.renewed == [] and entry.run.calls == []
    assert entry.credential_calls == 0 and entry.git_opens == 0 and slot.branch() is None


def test_the_entry_holds_the_slot_while_it_runs_and_frees_it_when_it_ends_or_raises(
    admitted: Path, checkouts: Checkouts, slot_files: SlotFiles, slot: FakeWorktree
) -> None:
    """The verify inside the entry settles under the lock the entry holds (its own hold is a no-op)."""
    seen: list[bool] = []
    entry = Entry(admitted, checkouts, slot_files, me(), written=(slot, {P: "# Plan\n"}, [P]))
    gone = entry.gone

    def observed(worker: Worker) -> bool:
        with pytest.raises(SlotBusy):
            acquire(str(slot.path), "other", "verify")
        seen.append(True)
        return gone(worker)

    entry.gone = observed
    assert entry() == 0 and entry.lines == ["collected verified verify=verified claim=held"] and seen == [True, True]
    acquire(str(slot.path), "after", "verify").release()

    def broken(tracker_root: str, task_id: str) -> Heartbeat:
        raise RuntimeError(f"bug at {tracker_root} for {task_id}")

    entry.heartbeat_for = broken
    with pytest.raises(RuntimeError):
        entry()
    acquire(str(slot.path), "after", "verify").release()


@pytest.mark.parametrize(
    ("beats", "rounds", "word", "renewals"),
    [
        (("held", "lost"), 3, "lost", 2),
        (("held", TypeError("bug")), 3, "fault", 2),
        ((TypeError("bug"),), 3, "fault", 1),
        (("unrenewed",), 2, "unrenewed", 3),
        (("unrenewed", "held"), 2, "held", 3),
    ],
    ids=["lost_mid_run", "fault_mid_run", "fault_before_the_agent", "never_renewed", "renewed_after_a_failure"],
)
def test_a_claim_lost_or_faulted_while_the_step_runs_is_only_recorded(
    admitted: Path, checkouts: Checkouts, slot_files: SlotFiles, slot: FakeWorktree,
    beats: tuple[Beat | Exception, ...], rounds: int, word: str, renewals: int,
) -> None:
    entry = Entry(admitted, checkouts, slot_files, me(), written=(slot, {P: "# Plan\n"}, [P]), beats=beats, rounds=rounds)
    assert entry() == 0  # the step completes, publishes and verifies; nothing is released or re-claimed
    assert entry.lines == [f"collected verified verify=verified claim={word}"] and len(entry.run.calls) == 1
    assert entry.renewed == [("/tracker", "tl-1")] * renewals and entry.stop.set_calls == 1


@pytest.mark.parametrize(
    "argv",
    [[], ["db", "/a", "tasks", "tl-1"], ["/db", "a", "tasks", "tl-1"], ["/db", "/a", "", "tl-1"], ["/db", "/a", "tasks", "tl-1", "x"]],
)
def test_arguments_are_two_absolute_paths_a_backlog_and_a_task(argv: list[str]) -> None:
    assert arguments(argv) is None


def test_arguments_never_carry_the_dispatch_token() -> None:
    assert arguments(["/db", "/a", "tasks", "tl-1"]) == EntryArgs(Path("/db"), Path("/a"), "tasks", "tl-1")


def test_main_refuses_bad_arguments_with_one_log_line(capfd: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BEADS_DIR", "/elsewhere/.beads")
    assert main(["relative", "/a", "tasks", "tl-1"]) == 2
    assert "BEADS_DIR" not in os.environ  # dropped first: no bd child of this entry can be pointed at another tracker
    out, err = capfd.readouterr()
    assert (out + err).strip() == "refused usage"
