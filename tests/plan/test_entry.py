"""The entry process body on a real factory.db file, its own real process identity, the owning agent fake and the fake slot."""

import dataclasses
import json
import os
from collections.abc import Callable
from pathlib import Path

import pytest
from any_agent import Harness, LaunchSpec, RunHooks, RunOutcome, Summary
from any_agent.procs import Worker
from any_agent.testing import FakeRun
from git_porcelain import Recorded, Repo
from git_porcelain.testing import FakeWorktree
from sqlite_store import Store
from stream_proc import ProcessObservation, inspect_process

from taskloop.attempt_entry import EntryArgs, arguments, enter, main
from taskloop.plan import PlanAttempts
from taskloop.plan_files import EvidenceError, PlanFiles
from taskloop.plan_schema import SCHEMA
from taskloop.plan_store import PlanStore
from taskloop.plan_types import AttemptKey, Checkouts, Evidence

KEY = AttemptKey("attempt", "dispatch", 1)
WORKER = Worker(pid=42, pgid=42, start="native-start", boot="boot")
PLAN = {"disposition": "planned", "plan_path": "docs/design/tl-1/plan.md", "commit": "a" * 40, "explanation": "Plan committed"}


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


class Entry:
    """One entry's collaborators: the run fake (with `commit`, the agent first commits that file in the slot and reports
    the commit), a counting credential source and Git view, a clock the wait advances, and the log."""

    def __init__(
        self,
        db: Path,
        checkouts: Checkouts,
        entry: tuple[int, str, str] | None = None,
        failures: int = 0,
        wait_to: float = 10,
        rc: int = 0,
        text: str = "",
        commit: tuple[FakeWorktree, str] | None = None,
    ) -> None:
        self.db, self.now, self.wait_to, self.git, self.commit = db, 10.0, wait_to, checkouts, commit
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

    def credentials(self) -> tuple[str, dict[str, str]]:
        self.credential_calls += 1
        return "/bin/codex", {"SECRET": "credential"}

    def checkouts(self, path: Path) -> Repo:
        self.git_opens += 1
        return self.git(path)

    def execution(self, harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        if self.commit is not None:
            slot, path = self.commit
            slot.write_file(path, "# Plan\n")
            made = slot.record("Plan", paths="all")
            assert isinstance(made, Recorded)
            summary = dataclasses.replace(self.outcome.summary, text=json.dumps(PLAN | {"commit": made.sha}))
            self.run = FakeRun(dataclasses.replace(self.outcome, summary=summary))
        return self.run(harness, spec, timeout, hooks)

    def attempts(self, database: Path, artifacts: Path) -> PlanAttempts:
        self.opened.append((database, artifacts))
        store = Store(SCHEMA)
        connect = PlanStore(lambda: store.shared_rw(database), store.begin_immediate)
        return PlanAttempts(connect, self.files, self.credentials, self.execution, self.clock, self.checkouts)

    def clock(self) -> float:
        return self.now

    def wait(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.now = self.wait_to

    def __call__(self, inspect: Callable[[int], ProcessObservation] = inspect_process, task_id: str = "tl-1") -> int:
        args = EntryArgs(self.db, self.db.parent, "tasks", task_id)
        return enter(args, self.attempts, inspect, self.clock, self.wait, self.lines.append)


@pytest.mark.parametrize(
    ("path", "line", "code", "opens"),
    [
        ("docs/design/tl-1/plan.md", "collected verified verify=verified", 0, 5),
        ("src/plan.md", "collected rejected:paths verify=rejected:paths", 1, 5),
        (None, "pending verification verify=unsettled:head_moved", 1, 4),
    ],
    ids=["verified", "rejected", "unsettled"],
)
def test_the_registered_entry_executes_verifies_once_and_exits_0_only_when_verified(
    admitted: Path, checkouts: Checkouts, slot: FakeWorktree, path: str | None, line: str, code: int, opens: int
) -> None:
    entry = Entry(admitted, checkouts, me(), commit=None if path is None else (slot, path))
    assert entry() == code
    assert entry.lines == [line] and len(entry.run.calls) == 1 and entry.credential_calls == 1
    assert entry.opened == [(admitted, admitted.parent)]
    # two Git opens before dispatch, two for the one verification's slot reads, one for its commit reads: never retried
    assert entry.waits == [] and entry.git_opens == opens


INCOMPLETE = "collected incomplete verify=not_applicable"


@pytest.mark.parametrize(
    ("rc", "text", "line"),
    [
        (1, "", "collected run:vendor_blip verify=not_applicable"),
        (1, json.dumps(PLAN), "collected run:vendor_blip verify=not_applicable"),
        (0, "not json", "collected answer:json_invalid verify=not_applicable"),
        (0, json.dumps(PLAN | {"disposition": "incomplete", "plan_path": None, "commit": None}), INCOMPLETE),
    ],
    ids=["failed_run_no_answer", "failed_run_valid_answer", "clean_run_bad_answer", "incomplete"],
)
def test_a_terminal_failure_is_collected_with_its_reason_and_exits_1(
    admitted: Path, checkouts: Checkouts, rc: int, text: str, line: str
) -> None:
    entry = Entry(admitted, checkouts, me(), rc=rc, text=text)
    assert entry() == 1
    assert entry.lines == [line] and all("SECRET" not in logged and "credential" not in logged for logged in entry.lines)


@pytest.mark.parametrize("stored", [None, (1, "someone-else", "boot")])
def test_a_process_that_is_not_the_registered_entry_reads_no_credentials(
    admitted: Path, checkouts: Checkouts, stored: tuple[int, str, str] | None
) -> None:
    entry = Entry(admitted, checkouts, stored)
    assert entry() == 1
    assert entry.lines == ["refused identity"] and entry.credential_calls == 0 and entry.run.calls == [] and entry.git_opens == 0


def test_an_unknown_own_identity_reads_no_credentials(admitted: Path, checkouts: Checkouts) -> None:
    entry = Entry(admitted, checkouts, me())
    assert entry(lambda _pid: ProcessObservation("unknown")) == 1
    assert entry.lines == ["refused identity"] and entry.credential_calls == 0 and entry.run.calls == []


def test_an_absent_task_or_a_missing_database_runs_nothing(admitted: Path, checkouts: Checkouts, tmp_path: Path) -> None:
    entry = Entry(admitted, checkouts, me())
    assert entry(task_id="tl-9") == 1 and entry.lines == ["refused absent"]
    missing = Entry(tmp_path / "missing.db", checkouts)
    assert missing() == 1 and missing.lines == ["refused database"]
    assert not (tmp_path / "missing.db").exists() and missing.opened == [] and missing.run.calls == []


@pytest.mark.parametrize(
    ("failures", "wait_to", "line", "waits", "captures"),
    [
        (1, 10, "unavailable evidence publish=accepted then=collected:verified verify=verified", 1, 2),
        (9, 10, "unavailable evidence publish=unavailable verify=refused:not_captured", 3, 4),
        (9, 100, "unavailable evidence verify=refused:not_captured", 1, 1),
    ],
    ids=["second_try_publishes", "three_retries_at_most", "never_past_the_deadline"],
)
def test_publication_is_retried_only_while_unavailable_and_the_agent_never_again(
    admitted: Path, checkouts: Checkouts, slot: FakeWorktree, failures: int, wait_to: float, line: str, waits: int, captures: int
) -> None:
    entry = Entry(admitted, checkouts, me(), failures, wait_to, commit=(slot, "docs/design/tl-1/plan.md"))
    assert entry() == (0 if failures == 1 else 1)
    assert entry.lines == [line] and len(entry.waits) == waits and entry.files.captures == captures
    assert len(entry.run.calls) == 1
    assert all("credential" not in text and "SECRET" not in text for text in entry.lines)


@pytest.mark.parametrize(
    "argv",
    [[], ["db", "/a", "tasks", "tl-1"], ["/db", "a", "tasks", "tl-1"], ["/db", "/a", "", "tl-1"], ["/db", "/a", "tasks", "tl-1", "x"]],
)
def test_arguments_are_two_absolute_paths_a_backlog_and_a_task(argv: list[str]) -> None:
    assert arguments(argv) is None


def test_arguments_never_carry_the_dispatch_token() -> None:
    assert arguments(["/db", "/a", "tasks", "tl-1"]) == EntryArgs(Path("/db"), Path("/a"), "tasks", "tl-1")


def test_main_refuses_bad_arguments_with_one_log_line(capfd: pytest.CaptureFixture[str]) -> None:
    assert main(["relative", "/a", "tasks", "tl-1"]) == 2
    out, err = capfd.readouterr()
    assert (out + err).strip() == "refused usage"
