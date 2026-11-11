"""The status of a task in its check step (S6d, tl-8bh9.14.6 section 9) over a factory.db file (the `done` implement
attempt and a checks attempt the real admission stored): the view takes the checks attempt's fields, every row of the
`Next` table, `tl step show`'s directory, setup, logs and earlier attempts, and `--stuck`."""

import dataclasses
from collections.abc import Callable, Generator
from pathlib import Path

import pytest
from doubles import ChecksBench, Done, FakeSlotFiles, PinnedViews
from git_porcelain.testing import FakeRepo
from stream_proc import OwnedProcess

from taskloop.admit import Admitted
from taskloop.attempt import succeeded
from taskloop.attempt_reads import PublishedRow, ReleaseRow
from taskloop.attempt_status import AttemptView, Listed, Shown, StatusPorts, list_attempts, show_attempt
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, AttemptResult, EntryIdentity, Seen
from taskloop.check_status import commands_seen
from taskloop.check_store import CheckStore, ResultRow
from taskloop.evidence_files import EvidenceFiles
from taskloop.setup_store import ProcessSeen, SetupStore

ENTRY = (7, "entry-start", "boot")


@dataclasses.dataclass
class Status:
    bench: ChecksBench
    key: AttemptKey
    seen: Seen = "gone"
    now: float = 10

    def observe(self, _entry: EntryIdentity) -> Seen:
        return self.seen

    def reads(self) -> StatusPorts:
        return StatusPorts(AttemptStore(lambda: self.bench.con), self.observe, lambda: self.now, lambda _key: None, lambda: "boot")

    def view(self) -> AttemptView:
        listed = list_attempts(self.reads())
        assert isinstance(listed, Listed) and len(listed.attempts) == 1
        return listed.attempts[0]

    def store(self) -> CheckStore:
        return CheckStore(lambda: self.bench.con)


@pytest.fixture
def status(done: Done, repo: FakeRepo, checkouts: PinnedViews, slot_files: FakeSlotFiles) -> Generator[Status]:
    bench = ChecksBench(done, repo, checkouts, slot_files)
    admitted = bench.admit()
    assert isinstance(admitted, Admitted)
    yield Status(bench, admitted.key)
    bench.con.close()


def test_the_view_takes_the_latest_checks_attempt_s_fields_and_keeps_the_task_s(status: Status) -> None:
    view = status.view()
    assert (view.step, view.attempt_id, view.slot, view.phase, view.entry, view.next) == ("check", status.key.attempt_id, "s1",
                                                                                          "admitted", "none", "start")
    assert (view.result, view.number, view.deadline_passed, view.entry_process, view.worker) == (
        AttemptResult("pending", "admitted"), 1, False, None, None)
    assert (view.leftovers, view.previous_attempt_id, view.repeat_reason, view.release) == ((), None, None, None)
    assert (view.backlog, view.task_id, view.seq, view.earlier) == ("tasks", "tl-1", 2, (("implement", "advanced"),))
    x = status.bench.done.x
    assert view.published == PublishedRow(x, x, 6.0) and view.checks is not None and view.checks.row.key == status.key


def test_with_no_checks_attempt_the_done_implement_attempt_says_advance(status: Status) -> None:
    status.bench.con.execute("DELETE FROM checks_attempt")
    view = status.view()
    assert (view.step, view.attempt_id, view.next, view.checks) == ("implement", "implement", "advance", None)


def registered(status: Status) -> None:
    assert status.store().register_entry(status.key, ENTRY, 10) == "accepted"


def refused(times: int) -> Callable[[Status], object]:
    return lambda s: [s.store().refused(s.key, "checks:running") for _ in range(times)]


def concluded(conclusion: str, released: bool = True, abandoned: bool = False) -> Callable[[Status], object]:
    return lambda s: s.bench.concluded(conclusion, released=released, abandoned=abandoned)


@pytest.mark.parametrize(("arrange", "seen", "now", "expected"), [
    (lambda s: None, "gone", 10, "start"),
    (lambda s: None, "gone", 500, "start"),  # past the deadline the relaunched entry concludes `expired`
    (registered, "matching", 10, "wait"),
    (registered, "matching", 500, "stuck:hung"),
    (registered, "unknown", 10, "unknown"),
    (registered, "different_process", 10, "start"),
    (refused(1), "gone", 10, "start"),
    (refused(2), "gone", 10, "stuck:checks_refused"),
    (concluded("failed", released=False), "gone", 10, "release"),
    (lambda s: (registered(s), concluded("failed", released=False)(s)), "matching", 500, "wait"),  # releasing its slot
    (concluded("passed"), "gone", 10, "done"),
    (concluded("failed"), "gone", 10, "done"),
    (concluded("failed", abandoned=True), "gone", 10, "release"),
    (lambda s: s.bench.con.execute("UPDATE checks_attempt SET required='[]'"), "gone", 10, "unknown"),  # an unreadable row
], ids=["none", "none_expired", "running", "hung", "entry_unknown", "other_process", "refused_once", "refused_twice",
        "concluded_held", "concluded_releasing", "passed", "failed", "abandoned", "store"])
def test_the_next_table(status: Status, arrange: Callable[[Status], object], seen: Seen, now: float, expected: str) -> None:
    arrange(status)
    status.seen, status.now = seen, now
    assert status.view().next == expected


def test_a_passed_or_failed_result_and_the_release_are_the_checks_attempt_s(status: Status) -> None:
    status.bench.concluded("passed")
    view = status.view()
    assert view.result == AttemptResult("collected", "passed") and succeeded(view.result)
    assert view.release == ReleaseRow(status.bench.done.d, 30.0, "kept")
    assert view.release is not None and not view.release.abandoned
    status.bench.con.execute("UPDATE checks_attempt SET conclusion='failed',reason='test:failed',abandoned=1")
    view = status.view()
    assert view.result == AttemptResult("collected", "failed:test:failed") and not succeeded(view.result)
    assert view.release is not None and view.release.abandoned and view.release.claim == "kept"


def test_list_stuck_keeps_a_checks_attempt_stuck_on_refusals(status: Status) -> None:
    listed = list_attempts(status.reads(), stuck=True)
    assert isinstance(listed, Listed) and listed.attempts == ()
    refused(2)(status)
    listed = list_attempts(status.reads(), stuck=True)
    assert isinstance(listed, Listed) and [each.next for each in listed.attempts] == ["stuck:checks_refused"]


def test_show_names_the_checks_attempt_s_directory_setup_logs_and_earlier_attempts_and_creates_nothing(status: Status) -> None:
    status.bench.concluded("failed")
    again = status.bench.admit(2)
    assert isinstance(again, Admitted)
    store, x = status.store(), status.bench.done.x
    SetupStore(lambda: status.bench.con).start(again.key, 1, x, "e" * 64, 11)
    store.start(again.key, store.block(again.key), 0, "check", "1" * 64, 600, 12)
    store.undefined(again.key, 1, 1, "smoke", 12)
    artifacts = status.bench.done.path.parent / "artifacts"
    found = show_attempt(status.reads(), artifacts, "tasks", "tl-1")
    assert isinstance(found, Shown) and not artifacts.exists()
    directory = EvidenceFiles(artifacts).root / EvidenceFiles(artifacts).directory(again.key)
    assert (found.directory, found.entry_log) == (directory, directory / "entry.log")
    assert found.setup is not None
    assert (found.setup.row.run, found.setup.log, found.setup.attempt_id) == (1, directory / "setup-1.log", None)
    view = found.view
    assert view.earlier == ((status.key.attempt_id, "re-run"), ("implement", "advanced")) and view.number == 2
    assert view.checks is not None and [row.name for row in view.checks.results] == ["check", "smoke"]
    assert view.checks.logs == (directory / "check-1-check.log", None)  # an undefined result has no command, no log


def test_show_reads_the_checks_entry_s_own_last_line(status: Status, tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path / "artifacts")
    files.entry_log(status.key).write_text("refused slot_busy\nunavailable checks:running claim=held\n")
    found = show_attempt(status.reads(), tmp_path / "artifacts", "tasks", "tl-1")
    assert isinstance(found, Shown) and found.view.last_entry == "unavailable checks:running claim=held"


def test_the_commands_a_dead_checks_entry_left_are_its_setup_and_its_unsettled_results_by_the_entry_s_rule() -> None:
    setup, check, done = (OwnedProcess(pid, pid, "start", "boot") for pid in (1, 2, 3))
    passed = ResultRow(1, 1, "test", "d" * 64, 60, done, 1.0, 2.0, 0, "passed")  # settled: never observed
    running = ResultRow(1, 0, "check", "c" * 64, 60, check, 1.0, None, None, None)
    seen: dict[int, ProcessSeen] = {}

    def observed(process: OwnedProcess) -> ProcessSeen:
        return seen.get(process.pid, "alive" if process is done else "gone")

    assert commands_seen(observed, setup, (passed, running)) == "gone"
    seen[1] = "alive"
    assert commands_seen(observed, setup, (passed,)) == "alive"  # the setup run's command
    seen.update({1: "gone", 2: "unknown"})
    assert commands_seen(observed, None, (passed, running)) == "unknown"
    seen[1] = "alive"
    assert commands_seen(observed, setup, (running,)) == "alive"  # alive wins over unknown
