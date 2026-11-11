"""The checks block (S6b, tl-8bh9.14.6 section 7) over real SQLite (the `checking` fixture's admitted checks attempt and
its `CheckStore` through `CheckSink`), the semantic Git fake's slot detached at X, and the scripted registered start of
`doubles`: each rule of the section as recorded results, log lines and observed calls; and the readings of a block."""

import dataclasses
import hashlib
import sqlite3
from pathlib import Path

import pytest
from doubles import CHECKS, REQUIRED, Command, FakeSetupProcess, PinnedViews
from git_porcelain import GitUnavailable, Recorded, WorktreeInfo
from git_porcelain.testing import FakeRepo, FakeWorktree

from taskloop.access import folders
from taskloop.agent_credentials import PUSH_REFUSED, scrubbed
from taskloop.attempt_types import AttemptResult
from taskloop.check_store import CheckStore, Conclusion, Required, ResultRow, unsettled
from taskloop.checks import Block, BlockPorts, BlockTarget, CheckSink, argv_digest, check_env, completed, conclusion, differs, main_seen
from taskloop.evidence_files import CappedLog, EvidenceFiles
from taskloop.profile import Check

CHECK, TEST, LINT = Check("check", ("just", "check"), 600), Check("test", ("just", "test"), 30), Check("lint", ("ruff", "."), 20)
ROWS = "SELECT block,position,name,conclusion,rc,pid FROM check_result ORDER BY block,position"


@dataclasses.dataclass
class Bench:
    """One checks attempt's blocks over the fakes: `now` is the clock (the deadline is 100), `events` the shared order."""

    con: sqlite3.Connection
    slot: FakeWorktree
    views: PinnedViews
    artifacts: Path
    events: list[str] = dataclasses.field(default_factory=list)
    now: float = 10.0
    deadline: float = 100.0
    env: dict[str, str] = dataclasses.field(default_factory=lambda: {"HOME": "/home/p"})

    def __post_init__(self) -> None:
        self.process = FakeSetupProcess(self.events)
        self.x = next(info.head for info in self.slot.repo.worktrees() if info.path == self.slot.path) or ""
        self.store = CheckStore(lambda: self.con)

    def clock(self) -> float:
        return self.now

    def target(self, required: Required = REQUIRED) -> BlockTarget:
        gitdir = self.slot.repo.identity().common_dir / "worktrees" / self.slot.path.name
        return BlockTarget(self.slot.path, self.views(self.slot.path, git_dir=gitdir), self.x, required, self.deadline, self.env)

    def run(self, *checks: Check, required: Required = REQUIRED, target: BlockTarget | None = None) -> AttemptResult | None:
        sink = CheckSink(self.store, CHECKS, EvidenceFiles(self.artifacts), self.clock)
        block = Block(BlockPorts(self.process, self.process.lingering, self.clock))
        return block.run(target or self.target(required), sink, self.store.block(CHECKS), checks)

    def rows(self) -> list[tuple[object, ...]]:
        return self.con.execute(ROWS).fetchall()

    def log(self, name: str, block: int = 1) -> str:
        return EvidenceFiles(self.artifacts).check_log(CHECKS, block, name).read_text()

    def verdict(self, required: Required = REQUIRED) -> tuple[str, str | None]:
        return conclusion(self.store.results(CHECKS), required)


@pytest.fixture
def bench(checking: sqlite3.Connection, slot: FakeWorktree, checkouts: PinnedViews, tmp_path: Path) -> Bench:
    return Bench(checking, slot, checkouts, tmp_path)


def test_every_check_runs_in_order_after_its_identity_is_committed(bench: Bench) -> None:
    """A non-required failure is shown and never decides."""
    seen: list[object] = []
    bench.process.script = [Command(effect=lambda: seen.append(bench.rows())), Command(), Command(rc=1)]
    assert bench.run(CHECK, TEST, LINT) is None
    assert seen == [[(1, 0, "check", None, None, 501)]]
    assert bench.rows() == [(1, 0, "check", "passed", 0, 501), (1, 1, "test", "passed", 0, 502), (1, 2, "lint", "failed", 1, 503)]
    assert bench.events == ["exec just check", "group 501", "exec just test", "group 502", "exec ruff .", "group 503"]
    assert bench.verdict() == ("passed", None)
    assert bench.log("check") == "$ just check\ndone\nexit 0\n" and bench.log("lint") == "$ ruff .\ndone\nexit 1\n"
    stored = bench.con.execute("SELECT name,argv_digest,timeout,proc_start,boot FROM check_result ORDER BY position").fetchall()
    assert stored[0] == ("check", argv_digest(("just", "check")), 600, "start-501", "boot")


def test_each_command_runs_in_the_slot_with_the_scrubbed_environment_and_the_nearer_limit(bench: Bench) -> None:
    """Host networking (no `UV_OFFLINE`), the push bar, the person's HOME, the slot's folders; no credential or Codex
    companion variable, no virtualenv. The wall limit is the check's timeout or the deadline, whichever is nearer."""
    environ = {"HOME": "/home/p", "PATH": "/v/bin:/bin", "VIRTUAL_ENV": "/v", "GH_TOKEN": "t", "CODEX_COMPANION_X": "c"}
    bench.env = check_env(scrubbed(environ), bench.slot.path)
    bench.run(CHECK, TEST)
    found = folders(bench.slot.path)
    first, second = bench.process.calls
    assert (first.cwd, first.timeout, second.timeout) == (str(bench.slot.path), 90, 30)
    assert first.env == {
        "HOME": "/home/p", "PATH": "/bin", "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": f"url.{PUSH_REFUSED}.pushInsteadOf",
        "GIT_CONFIG_VALUE_0": "", "TMPDIR": str(found.tmp), "UV_CACHE_DIR": str(found.cache), "UV_TOOL_DIR": str(found.tools),
    }


def test_a_required_name_the_profile_at_x_does_not_define_is_undefined_before_any_command(bench: Bench) -> None:
    seen: list[object] = []
    bench.process.script = [Command(effect=lambda: seen.append(bench.rows()))]
    bench.run(CHECK, required=(*REQUIRED, ("smoke", "3" * 64)))
    assert seen == [[(1, 0, "check", None, None, 501), (1, 1, "test", "undefined", None, None), (1, 2, "smoke", "undefined", None, None)]]
    assert bench.verdict((*REQUIRED, ("smoke", "3" * 64))) == ("failed", "test:undefined")
    assert bench.con.execute("SELECT argv_digest,timeout FROM check_result WHERE name='smoke'").fetchone() == (None, None)


def test_its_own_timeout_is_timed_out_and_the_block_goes_on(bench: Bench) -> None:
    bench.process.script = [Command(), Command(rc=None, timed_out=True)]
    assert bench.run(CHECK, TEST, LINT) is None
    assert [row[3] for row in bench.rows()] == ["passed", "timed_out", "passed"]
    assert bench.log("test") == "$ just test\ndone\ntimed out\n" and bench.verdict() == ("failed", "test:timed_out")


@pytest.mark.parametrize(("command", "ending"), [
    (Command(rc=None, timed_out=True, survivors=True), "timed out"),
    (Command(rc=None, timed_out=True, lingering=True), "timed out"),
    (Command(lingering=True), "exit 0"),
    (Command(rc=2, lingering=True), "exit 2"),
], ids=["timeout_survivors", "timeout_group", "exit_group", "failed_group"])
def test_a_process_left_after_any_end_is_lingering_and_stops_the_block(bench: Bench, command: Command, ending: str) -> None:
    bench.process.script = [command]
    assert bench.run(LINT, CHECK, TEST) is None
    assert bench.rows() == [(1, 0, "lint", "lingering", command.rc, 501)] and bench.process.calls[-1].argv == ("ruff", ".")
    assert bench.log("lint") == f"$ ruff .\ndone\n{ending}\nlingering\n"
    assert bench.verdict() == ("failed", "lint:lingering")  # not required, and still the reason
    assert [row.name for row in unsettled(bench.con, "checks")] == ["lint"]


def test_the_deadline_with_survivors_is_lingering_not_interrupted(bench: Bench) -> None:
    bench.process.script = [Command(rc=None, timed_out=True, survivors=True)]
    assert bench.run(CHECK, TEST) is None  # CHECK's 600 s are beyond the deadline: the deadline stopped it
    assert bench.rows() == [(1, 0, "check", "lingering", None, 501)]
    assert bench.log("check").endswith("stopped at the deadline\nlingering\n")


def test_the_deadline_without_survivors_interrupts_and_expires_the_attempt(bench: Bench) -> None:
    bench.process.script = [Command(rc=None, timed_out=True)]
    assert bench.run(CHECK, TEST) == AttemptResult("refused", "expired:check")
    assert bench.rows() == [(1, 0, "check", "interrupted", None, 501)]
    assert bench.log("check") == "$ just check\ndone\nstopped at the deadline\n"
    assert not completed(bench.store.results(CHECKS), (CHECK, TEST), REQUIRED)


def test_a_deadline_reached_between_checks_expires_at_the_next_without_starting_it(bench: Bench) -> None:
    bench.process.script = [Command(effect=lambda: setattr(bench, "now", 100.0))]
    assert bench.run(TEST, CHECK) == AttemptResult("refused", "expired:check")
    assert bench.rows() == [(1, 0, "test", "passed", 0, 501)]


def advance(slot: FakeWorktree) -> str:
    made = slot.record("another commit", paths="all")
    assert isinstance(made, Recorded)
    return made.sha


@pytest.mark.parametrize("change", ["tracked", "staged", "branch", "commit"])
@pytest.mark.parametrize("command", [Command(), Command(rc=1), Command(rc=None, timed_out=True)], ids=["exit_0", "exit_1", "timeout"])
def test_a_tracked_change_or_a_moved_head_after_any_end_is_dirty_and_stops_the_block(
    bench: Bench, slot: FakeWorktree, change: str, command: Command
) -> None:
    effects = {
        "tracked": lambda: slot.write_file("README", "rewritten"),
        "staged": lambda: (slot.write_file("added", "x"), slot.stage(["added"])),
        "branch": lambda: slot.checkout_new("elsewhere"),
        "commit": lambda: (slot.write_file("README", "x"), advance(slot)),
    }
    bench.process.script = [dataclasses.replace(command, effect=effects[change])]
    assert bench.run(TEST, CHECK) is None
    assert [row[2:4] for row in bench.rows()] == [("test", "dirty")] and len(bench.process.calls) == 1
    assert bench.log("test").endswith("\ndirty\n") and bench.verdict() == ("failed", "test:dirty")


def test_untracked_files_are_listed_not_dirty(bench: Bench, slot: FakeWorktree) -> None:
    def leave() -> None:
        for index in range(52):
            slot.write_file(f"out/{index:02}", "x")

    slot.repo.exclude_locally([".venv/"])
    bench.process.script = [Command(effect=lambda: (leave(), slot.write_file(".venv/ignored", "x")))]
    assert bench.run(TEST) is None
    assert bench.rows()[0][3] == "passed"
    lines = bench.log("test").splitlines()
    assert lines[2:4] == ["exit 0", "untracked: out/00"] and lines[-1] == "untracked: +2 more" and len(lines) == 54
    assert not any("ignored" in line for line in lines)


@pytest.mark.parametrize("command", [Command(rc=None, exec_failed=True), Command(spawn_error=True)], ids=["exec", "spawn"])
def test_a_command_that_never_ran_is_failed_without_a_group_or_slot_read_and_the_block_goes_on(
    bench: Bench, slot: FakeWorktree, command: Command
) -> None:
    """The slot was already dirty: only the check that ran is judged by it."""
    slot.write_file("README", "changed before")
    bench.process.script = [command]
    assert bench.run(TEST, CHECK) is None
    assert [row[3:5] for row in bench.rows()] == [("failed", None), ("dirty", 0)]
    assert [event for event in bench.events if event.startswith("group")] == [f"group {bench.process.next_pid}"]
    assert bench.log("test") == "$ just test\nnot started\n"


@pytest.mark.parametrize(("lingering", "found"), [(False, "failed"), (True, "lingering")])
def test_a_supervision_failure_after_the_start_is_judged_by_its_group(bench: Bench, lingering: bool, found: str) -> None:
    bench.process.script = [Command(supervision_error=True, lingering=lingering)]
    bench.run(TEST, CHECK)
    assert bench.rows()[0] == (1, 0, "test", found, None, 501) and "group 501" in bench.events
    assert bench.log("test").startswith("$ just test\ndone\nended uncertainly\n")


def test_an_uncertain_start_keeps_its_identity_unjudged_and_stops_the_block(bench: Bench) -> None:
    bench.process.script = [Command(uncertain=True)]
    assert bench.run(TEST, CHECK) == AttemptResult("unavailable", "checks:uncertain")
    assert bench.rows() == [(1, 0, "test", None, None, 501)] and bench.events == ["exec just test"]
    assert bench.log("test") == "$ just test\nstart uncertain\n"


class Unreadable:
    """A pinned view whose worktree listing fails."""

    def worktrees(self) -> tuple[WorktreeInfo, ...]:
        raise GitUnavailable("listing failed")


def test_a_slot_unreadable_after_a_check_leaves_its_result_for_the_reconcile(bench: Bench, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(FakeRepo, "worktrees", Unreadable.worktrees)
    assert bench.run(TEST, CHECK) == AttemptResult("unavailable", "git")
    assert bench.rows() == [(1, 0, "test", None, None, 501)]


def test_a_log_that_cannot_be_opened_starts_nothing(bench: Bench) -> None:
    (bench.artifacts / "attempts").write_text("a file where the folder belongs")
    assert bench.run(TEST, CHECK) == AttemptResult("unavailable", "environment:files")
    assert bench.rows() == [] and bench.process.calls == []


def test_an_interrupted_block_repeats_whole_and_only_the_latest_block_concludes(bench: Bench) -> None:
    bench.process.script = [Command(), Command(rc=None, timed_out=True)]
    bench.deadline = 40.0  # CHECK (600 s) is stopped by it
    assert bench.run(TEST, CHECK) == AttemptResult("refused", "expired:check")
    assert not completed(bench.store.results(CHECKS), (TEST, CHECK), REQUIRED)
    bench.deadline = 1000.0
    assert bench.run(TEST, CHECK) is None
    assert [row[:4] for row in bench.rows()] == [
        (1, 0, "test", "passed"), (1, 1, "check", "interrupted"), (2, 0, "test", "passed"), (2, 1, "check", "passed")]
    assert completed(bench.store.results(CHECKS), (TEST, CHECK), REQUIRED) and bench.verdict() == ("passed", None)
    assert bench.log("check", 2) == "$ just check\ndone\nexit 0\n"


def result(name: str, found: Conclusion | None, digest: str | None = "0" * 64) -> ResultRow:
    return ResultRow(1, 0, name, digest, None if digest is None else 1, None, 1.0, None if found is None else 2.0, None, found)


@pytest.mark.parametrize(("results", "done"), [
    ((), False),
    ((result("check", "passed"), result("test", "timed_out"), result("lint", "failed")), True),
    ((result("check", "failed"), result("test", "passed")), False),  # lint missing
    ((result("check", "passed"), result("test", "passed"), result("lint", "interrupted")), False),
    ((result("check", "passed"), result("test", "passed"), result("lint", None)), False),
    ((result("check", "passed"), result("lint", "dirty")), True),
    ((result("lint", "lingering"),), True),
], ids=["empty", "terminal", "missing", "interrupted", "unfinished", "dirty", "lingering"])
def test_a_completed_block_is_every_terminal_result_or_a_stopping_one(results: tuple[ResultRow, ...], done: bool) -> None:
    assert completed(results, (CHECK, TEST, LINT), REQUIRED) is done


def test_an_undefined_required_name_needs_its_own_result_for_a_completed_block() -> None:
    required = (*REQUIRED, ("smoke", "3" * 64))
    ran = (result("check", "passed"), result("test", "passed"))
    assert not completed(ran, (CHECK, TEST), required)
    assert completed((*ran, result("smoke", "undefined", None)), (CHECK, TEST), required)


@pytest.mark.parametrize(("results", "verdict"), [
    ((result("check", "passed"), result("test", "passed"), result("lint", "failed")), ("passed", None)),
    ((result("check", "failed"), result("test", "timed_out")), ("failed", "check:failed")),
    ((result("test", "timed_out"), result("check", "failed")), ("failed", "check:failed")),  # the target's order, not the block's
    ((result("check", "passed"),), ("failed", "test:not_run")),
    ((result("check", "failed"), result("lint", "dirty")), ("failed", "lint:dirty")),
    ((result("check", "passed"), result("test", "passed"), result("lint", "lingering")), ("failed", "lint:lingering")),
], ids=["passed", "first_required", "target_order", "not_run", "stopping_wins", "stopping_not_required"])
def test_the_conclusion_reads_the_required_names_and_any_stopping_result(
    results: tuple[ResultRow, ...], verdict: tuple[str, str | None]
) -> None:
    assert conclusion(results, REQUIRED) == verdict


def test_a_required_check_whose_argv_differs_from_the_targets_is_marked() -> None:
    assert differs(REQUIRED, result("check", "passed", "9" * 64))
    assert not differs(REQUIRED, result("check", "passed", "1" * 64))
    assert not differs(REQUIRED, result("lint", "passed", "9" * 64))  # not required
    assert not differs(REQUIRED, result("test", "undefined", None))


def test_the_digest_is_of_the_argv_as_compact_json() -> None:
    assert argv_digest(("just", "check")) == hashlib.sha256(b'["just","check"]').hexdigest() == argv_digest(["just", "check"])
    assert argv_digest(("a b",)) != argv_digest(("a", "b"))


def test_main_is_read_now(repo: FakeRepo) -> None:
    first, main = main_seen(repo), repo.worktree(repo.identity().root)
    main.write_file("README", "moved")
    made = main.record("someone's commit on main", paths="all")
    assert isinstance(made, Recorded) and first is not None
    assert main_seen(repo) == made.sha != first


def test_a_capped_log_keeps_the_cap_then_one_truncated_line_and_nothing_more(tmp_path: Path) -> None:
    log = CappedLog(tmp_path / "check.log", cap=8)
    log.write(b"12345")
    log.write(b"67890")
    log.write(b"more")
    log.close()
    assert (tmp_path / "check.log").read_bytes() == b"12345678[truncated]\n"
    assert (tmp_path / "check.log").stat().st_mode & 0o777 == 0o600
