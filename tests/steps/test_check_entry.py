"""The checks entry body (S6c, tl-8bh9.14.6 section 6 and 6.1) on a factory.db file (the `on_slot` checks attempt, its
entry registered as this process's real identity), the semantic Git fake's slot, the slot environment and block over
`doubles`' scripted registered start, env files and profile port, the real slot lock and a scripted claim: each step's
order as events, every conclusion (written and released) and every counted relaunch of 6.1's table."""

import dataclasses
import json
import os
import sqlite3
import threading
from collections.abc import Generator
from functools import partial
from pathlib import Path

import pytest
from doubles import CHECKS, Command, Environment, FakeProfiles, FakeSlotFiles, PinnedViews
from git_porcelain import Recorded
from git_porcelain.testing import FakeWorktree
from sqlite_store import Store
from stream_proc import OwnedProcess, ProcessObservation, inspect_process

from taskloop.attempt import CredentialsUnavailable
from taskloop.attempt_entry import EntryArgs
from taskloop.attempt_types import AttemptResult, EntryIdentity
from taskloop.check_entry import Verdict, concluded, enter
from taskloop.check_entry import main as check_main
from taskloop.check_store import CheckStore
from taskloop.checks import Block, BlockPorts
from taskloop.claim_lease import Beat, Heartbeat
from taskloop.composition import Checking
from taskloop.evidence_files import EvidenceFiles
from taskloop.factory_schema import SCHEMA
from taskloop.git_views import GitViews
from taskloop.setup_store import SetupStore
from taskloop.slot_lock import custody

PROFILE = {"setup": [["just", "bootstrap"]], "required": ["check", "test"], "checks": [
    {"name": "check", "argv": ["just", "check"], "timeout": 600}, {"name": "test", "argv": ["just", "test"], "timeout": 30}]}
RESULTS = "SELECT block,name,conclusion FROM check_result ORDER BY block,position"
ATTEMPT = "SELECT phase,conclusion,reason,refusal,refusals,target_seen,released_at IS NOT NULL FROM checks_attempt"


def me() -> EntryIdentity:
    seen = inspect_process(os.getpid())
    assert seen.kind == "matching" and seen.identity is not None
    return seen.identity.pid, seen.identity.start, seen.identity.boot


class Stop:
    """The keep-alive's stop: the renewing thread beats once `go` is set (if given), then stops."""

    def __init__(self, go: threading.Event | None) -> None:
        self.go = go

    def wait(self, timeout: float) -> bool:
        del timeout
        if self.go is None:
            return True
        self.go.wait(5)
        self.go = None
        return False

    def set(self) -> None:
        return None


@dataclasses.dataclass
class Bench:
    """One checks entry's collaborators: `environment` holds the shared `events`, the scripted start (setup, then the
    checks), the process observations by pid (`seen`) and the profile; `beats` the claim's answers; `now` the clock."""

    db: Path
    con: sqlite3.Connection
    slot: FakeWorktree
    views: PinnedViews
    files: FakeSlotFiles
    environment: Environment
    beats: list[Beat] = dataclasses.field(default_factory=lambda: ["held"])
    thread: Beat = "held"  # the renewing thread's answer, once `go` is set
    go: threading.Event | None = None
    credentials: Exception | None = None  # raised by the scrubbed environment's read
    lines: list[str] = dataclasses.field(default_factory=list)
    emptied: list[Path] = dataclasses.field(default_factory=list)
    now: float = 10.0

    def __post_init__(self) -> None:
        self.store = CheckStore(lambda: self.con)
        self.d = self.head()
        self.x = self.con.execute("SELECT end_commit FROM attempt WHERE attempt_id='implement'").fetchone()[0]
        self.environment.clock = self.clock
        self.environment.profiles = FakeProfiles(blob=json.dumps(PROFILE).encode())

    def clock(self) -> float:
        return self.now

    def head(self) -> str:
        found = next(info.head for info in self.slot.repo.worktrees() if info.path == self.slot.path)
        assert found is not None
        return found

    def heartbeat_for(self, _root: str, _task: str) -> Heartbeat:
        def beat() -> Beat:
            if threading.current_thread().name == "claim-lease":
                return self.thread
            self.environment.events.append("renew")
            return self.beats.pop(0) if len(self.beats) > 1 else self.beats[0]

        return beat

    def scratch(self, path: Path) -> bool:
        self.emptied.append(path)
        return True

    def environ(self) -> dict[str, str]:
        if self.credentials is not None:
            raise self.credentials
        return {"HOME": "/home/p"}

    def checking(self, _database: Path, _artifacts: Path) -> Checking:
        env = self.environment
        block = Block(BlockPorts(env.process, env.process.lingering, self.clock))
        return Checking(self.store, SetupStore(lambda: self.con), EvidenceFiles(env.artifacts), self.views, self.files, env.profiles,
                        env.preparation(), block, env.observe, lambda _entry: "gone", self.scratch, self.clock, self.environ)

    def __call__(self, inspect: object = inspect_process) -> int:
        observe = inspect_process if inspect is inspect_process else self.other
        args = EntryArgs(self.db, self.db.parent, 600, "tasks", "tl-1")
        return enter(args, self.checking, observe, self.lines.append, self.heartbeat_for,
                     Stop(self.go))

    @staticmethod
    def other(_pid: int) -> ProcessObservation:
        return ProcessObservation("matching", OwnedProcess(1, 1, "another-start", "boot"))

    def attempt(self) -> tuple[object, ...]:
        return self.con.execute(ATTEMPT).fetchone()

    def results(self) -> list[tuple[object, ...]]:
        return self.con.execute(RESULTS).fetchall()

    def execs(self) -> list[str]:
        return [event for event in self.environment.events if event.startswith("exec")]

    def result(self, block: int, position: int, name: str, conclusion: str | None, pid: int | None = None) -> None:
        """A result row of an earlier entry, written straight into the table."""
        self.con.execute("""INSERT INTO check_result (attempt_id,dispatch_token,generation,block,position,name,argv_digest,timeout,
            pid,pgid,proc_start,boot,started_at,ended_at,conclusion) VALUES ('checks','checks-token',1,?,?,?,?,60,?,?,?,?,1,?,?)""",
                         (block, position, name, "e" * 64, pid, pid, None if pid is None else "start", None if pid is None else "boot",
                          None if conclusion is None else 2, conclusion))


@pytest.fixture
def bench(on_slot: Path, slot: FakeWorktree, checkouts: PinnedViews, slot_files: FakeSlotFiles, tmp_path: Path) -> Generator[Bench]:
    con = Store(SCHEMA).open_rw(on_slot)
    assert con is not None
    assert CheckStore(lambda: con).register_entry(CHECKS, me(), 10) == "accepted"
    yield Bench(on_slot, con, slot, checkouts, slot_files, Environment(con, checkouts, tmp_path / "art", tmp_bytes=4096))
    con.close()


RUN = ["exec just bootstrap", "exec just check", "exec just test"]


def test_a_passing_block_concludes_passed_releases_the_slot_at_d_and_exits_0(bench: Bench) -> None:
    """Order: the claim renewed first, X taken, the slot reset and set up at X, renewed again, the block; the release
    parks at D."""
    heads: list[str] = []
    bench.environment.process.script = [Command(effect=lambda: heads.append(bench.head()))]
    assert bench() == 0
    assert bench.lines == ["collected passed claim=held release=released"]
    events = bench.environment.events
    assert [e for e in events if e.startswith(("exec", "renew"))] == ["renew", RUN[0], "renew", *RUN[1:]] and events[0] == "renew"
    assert heads == [bench.x] and (bench.head(), bench.slot.branch()) == (bench.d, None)
    assert bench.attempt() == ("concluded", "passed", None, None, 0, None, 1) and bench.emptied == [bench.slot.path]
    assert bench.results() == [(1, "check", "passed"), (1, "test", "passed")]
    assert bench.con.execute("SELECT count(*) FROM reservation").fetchone() == (0,)
    assert bench.con.execute("SELECT profile_digest FROM checks_attempt").fetchone()[0] is not None


def test_a_failed_required_check_concludes_failed_with_its_reason_and_exit_1(bench: Bench) -> None:
    bench.environment.process.script = [Command(), Command(), Command(rc=1)]
    assert bench() == 1
    assert bench.lines == ["collected failed:test:failed claim=held release=released"]
    assert bench.attempt()[:3] == ("concluded", "failed", "test:failed")


def test_a_claim_lost_before_the_block_concludes_and_releases_without_touching_the_slot(bench: Bench) -> None:
    bench.beats = ["lost"]
    assert bench() == 1
    assert bench.lines == ["collected failed:claim_lost claim=lost release=released"]
    assert bench.execs() == [] and bench.head() == bench.d and bench.attempt()[:3] == ("concluded", "failed", "claim_lost")


def test_a_claim_lost_at_the_renewal_after_setup_concludes_before_the_block(bench: Bench) -> None:
    bench.beats = ["held", "lost"]
    assert bench() == 1 and bench.lines == ["collected failed:claim_lost claim=lost release=released"]
    assert bench.execs() == ["exec just bootstrap"]


def test_a_claim_lost_later_by_the_keep_alive_is_recorded_and_the_results_stand(bench: Bench) -> None:
    bench.thread, bench.go = "lost", threading.Event()
    bench.environment.process.script = [Command(), Command(effect=bench.go.set)]  # the first check runs: the thread beats
    assert bench() == 0 and bench.lines == ["collected passed claim=lost release=released"] and bench.execs() == RUN


@pytest.mark.parametrize(("seen", "word"), [("alive", "checks:running"), ("unknown", "checks:unknown")])
def test_a_live_or_unknown_orphan_is_reconciled_before_any_slot_read_and_counted(bench: Bench, seen: str, word: str) -> None:
    """An orphan that dirtied the slot says `checks:running`, never `slot_dirty`; nothing is signalled or run."""
    bench.result(1, 0, "check", None, pid=900)
    bench.environment.seen[900] = "alive" if seen == "alive" else "unknown"
    bench.slot.write_file("README", "dirtied by the orphan")
    opened = len(bench.views.opened)
    assert bench() == 1 and bench.lines == [f"unavailable {word} claim=held"]
    assert len(bench.views.opened) == opened and bench.execs() == [] and bench.results() == [(1, "check", None)]
    assert bench.attempt()[:5] == ("admitted", None, None, word, 1)
    bench()
    assert bench.attempt()[3:5] == (word, 2)  # two in a row: `stuck:checks_refused`


def test_a_live_setup_command_is_also_running(bench: Bench) -> None:
    setups = SetupStore(lambda: bench.con)
    setups.start(CHECKS, 1, bench.x, "e" * 64, 5)
    setups.registered(CHECKS, 1, 0, OwnedProcess(800, 800, "s", "boot"))
    bench.environment.seen[800] = "alive"
    assert bench() == 1 and bench.lines == ["unavailable checks:running claim=held"]


def test_an_interrupted_block_repeats_whole_after_its_commands_are_proven_gone(bench: Bench) -> None:
    bench.result(1, 0, "check", "passed")
    bench.result(1, 1, "test", None, pid=901)  # gone: its entry died mid-check
    assert bench() == 0 and bench.execs() == RUN
    assert bench.results() == [(1, "check", "passed"), (1, "test", "interrupted"), (2, "check", "passed"), (2, "test", "passed")]


def test_a_completed_block_is_concluded_as_it_stands_without_running_or_taking_x(bench: Bench) -> None:
    bench.result(1, 0, "check", "passed")
    bench.result(1, 1, "test", "timed_out", pid=902)  # proven gone
    assert bench() == 1 and bench.lines == ["collected failed:test:timed_out claim=held release=released"]
    assert bench.execs() == [] and bench.head() == bench.d


def test_past_the_deadline_it_concludes_expired_once_nothing_runs(bench: Bench) -> None:
    bench.now = 100
    bench.result(1, 0, "check", None, pid=903)
    bench.environment.seen[903] = "alive"
    assert bench() == 1 and bench.lines == ["unavailable checks:running claim=held"]  # the proof first
    bench.environment.seen[903] = "gone"
    assert bench() == 1 and bench.lines[-1] == "collected failed:expired claim=held release=released"
    assert bench.execs() == [] and bench.head() == bench.d  # X never taken, no setup run
    assert bench.con.execute("SELECT count(*) FROM setup_run").fetchone() == (0,)


def moved(bench: Bench) -> str:
    root = bench.slot.repo.worktree(bench.slot.repo.identity().root)
    root.write_file("README", "main moved")
    made = root.record("a person's commit", paths="all")
    assert isinstance(made, Recorded)
    return made.sha


class Claims:
    """The tracker's claim port as `main` only reads it."""

    heartbeat_for = None


def test_main_builds_the_git_views_with_the_argv_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[object] = []
    monkeypatch.setattr("taskloop.check_entry.tracker_located", lambda: None)
    monkeypatch.setattr("taskloop.check_entry.tracker_claims", Claims)
    monkeypatch.setattr("taskloop.check_entry.enter", lambda _args, opened, *_rest: seen.append(opened) or 0)
    assert check_main(["/db", "/a", "45", "tasks", "tl-1"]) == 0
    assert isinstance(seen[0], partial) and seen[0].keywords == {"views": GitViews(45)}


def test_main_moved_before_the_block_concludes_with_main_s_commit(bench: Bench) -> None:
    seen = moved(bench)
    assert bench() == 1 and bench.lines == ["collected failed:main_moved claim=held release=released"]
    assert bench.execs() == [] and bench.attempt()[5] == seen


def test_main_moved_during_the_block_fails_a_passing_block(bench: Bench) -> None:
    bench.environment.process.script = [Command(), Command(), Command(effect=lambda: moved(bench))]
    assert bench() == 1 and bench.lines == ["collected failed:main_moved claim=held release=released"]
    assert bench.results() == [(1, "check", "passed"), (1, "test", "passed")]


@pytest.mark.parametrize(("blob", "line"), [
    (b"not json", "collected failed:profile:not_json claim=held release=released"),
    (None, "collected failed:profile:missing claim=held release=released"),
], ids=["invalid", "missing"])
def test_the_candidate_s_own_profile_refused_at_x_concludes(bench: Bench, blob: bytes | None, line: str) -> None:
    bench.environment.profiles = FakeProfiles(blob=blob)
    assert bench() == 1 and bench.lines == [line] and bench.execs() == []


def test_a_slot_on_a_branch_concludes_and_a_dirty_slot_elsewhere_is_counted(bench: Bench) -> None:
    bench.slot.write_file("README", "changed")
    assert bench() == 1 and bench.lines == ["refused slot_dirty claim=held"] and bench.attempt()[3:5] == ("slot_dirty", 1)
    bench.slot.checkout_new("elsewhere")
    assert bench() == 1 and bench.lines[-1] == "collected failed:slot:branch claim=held release=held:slot_dirty"
    assert bench.attempt()[:5] == ("concluded", "failed", "slot:branch", None, 0)  # the conclusion clears the count


@pytest.mark.parametrize(("arrange", "line"), [
    (lambda b: setattr(b.environment, "platform", "darwin"), "collected failed:environment:platform claim=held release=released"),
    (lambda b: b.environment.process.script.append(Command(rc=1)), "unavailable environment:exit claim=held"),
    (lambda b: b.environment.files.unemptiable.add(b.slot.path.parent / ".t" / "s1"), "unavailable environment:files claim=held"),
], ids=["platform", "exit", "files"])
def test_the_environment_concludes_its_refusals_and_counts_the_rest(bench: Bench, arrange: object, line: str) -> None:
    assert callable(arrange)
    arrange(bench)
    assert bench() == 1 and bench.lines == [line]


def test_two_failed_setup_runs_conclude_with_the_latest_setup_conclusion(bench: Bench) -> None:
    bench.environment.process.script = [Command(rc=1), Command(rc=None, lingering=True)]
    bench()
    bench.environment.process.groups.clear()
    bench()
    assert bench.lines == ["unavailable environment:exit claim=held", "unavailable environment:lingering claim=held"]
    assert bench.attempt()[3:5] == ("environment:lingering", 2)  # two relaunches in a row: stuck, whatever the words
    bench()  # relaunched by hand (`tl step start`)
    assert bench.lines[-1] == "collected failed:setup:lingering claim=held release=released"


def test_a_lingering_check_concludes_and_its_live_group_holds_the_release(bench: Bench) -> None:
    def left() -> None:
        bench.environment.seen[bench.environment.process.next_pid] = "alive"

    bench.environment.process.script = [Command(), Command(lingering=True, effect=left)]
    assert bench() == 1 and bench.lines == ["collected failed:check:lingering claim=held release=held:check_running"]
    assert bench.attempt()[6] == 0 and bench.con.execute("SELECT count(*) FROM reservation").fetchone() == (1,)


def test_the_deadline_mid_block_concludes_expired_with_the_check(bench: Bench) -> None:
    bench.environment.process.script = [Command(), Command(rc=None, timed_out=True)]  # CHECK's 600 s pass the deadline
    assert bench() == 1 and bench.lines == ["collected failed:expired:check claim=held release=released"]


def test_an_uncertain_start_is_counted_and_reconciled_by_the_next_entry(bench: Bench) -> None:
    bench.environment.process.script = [Command(), Command(uncertain=True)]
    assert bench() == 1 and bench.lines == ["unavailable checks:uncertain claim=held"]
    bench.environment.seen[502] = "alive"
    bench()
    bench.environment.seen[502] = "gone"
    assert bench() == 0 and bench.lines[1:] == ["unavailable checks:running claim=held", "collected passed claim=held release=released"]
    assert [row[:2] + row[2:] for row in bench.results()][:1] == [(1, "check", "interrupted")]


def test_only_the_registered_entry_of_an_admitted_attempt_runs(bench: Bench, tmp_path: Path) -> None:
    assert bench(inspect=Bench.other) == 1 and bench.lines == ["refused identity"]
    bench.store.conclude(CHECKS, "passed", None, 20)
    assert bench() == 1 and bench.lines[-1] == "refused concluded"
    bench.db = tmp_path / "missing.db"
    assert bench() == 1 and bench.lines[-1] == "refused database" and not bench.db.exists()
    assert bench.environment.events == []


def test_a_busy_slot_lock_is_counted_with_nothing_read(bench: Bench) -> None:
    with custody(str(bench.slot.path), "someone"):
        assert bench() == 1
    assert bench.lines == ["refused slot_busy"] and bench.environment.events == [] and bench.attempt()[3:5] == ("slot_busy", 1)


@pytest.mark.parametrize(("result", "verdict"), [
    (AttemptResult("refused", "commit_missing"), Verdict("failed", "commit_missing")),
    (AttemptResult("refused", "slot:moved"), Verdict("failed", "slot:moved")),
    (AttemptResult("refused", "slot_unborn"), Verdict("failed", "slot:unborn")),
    (AttemptResult("refused", "slot:redirected"), Verdict("failed", "slot:redirected")),
    (AttemptResult("refused", "environment:reset"), Verdict("failed", "environment:reset")),
    (AttemptResult("refused", "slot_busy"), None), (AttemptResult("refused", "slot_dirty"), None),
    (AttemptResult("refused", "stale_reservation"), None), (AttemptResult("unavailable", "repo"), None),
    (AttemptResult("unavailable", "not_listed"), None), (AttemptResult("unavailable", "environment:files"), None),
    (AttemptResult("unavailable", "git"), None), (AttemptResult("unavailable", "store"), None),
])
def test_section_6_1_concludes_what_a_relaunch_cannot_clear(result: AttemptResult, verdict: Verdict | None) -> None:
    assert concluded(result) == verdict


@pytest.mark.parametrize("script", [[Command(uncertain=True)], [Command(), Command(uncertain=True)]], ids=["setup", "block"])
def test_two_words_alternating_still_count_to_stuck(bench: Bench, script: list[Command]) -> None:
    """An uncertain start is not waited for: the next entry finds its command running. Both relaunches count."""
    bench.environment.process.script = list(script)
    bench()
    bench.environment.seen[500 + len(script)] = "alive"  # the uncertain command's pid
    bench()
    assert bench.lines[1] == "unavailable checks:running claim=held" and bench.attempt()[3:5] == ("checks:running", 2)


def test_a_completed_block_is_not_concluded_once_main_moved(bench: Bench) -> None:
    """A candidate that moved `main` and then lost its entry never passes on the relaunch."""
    bench.result(1, 0, "check", "passed")
    bench.result(1, 1, "test", "passed")
    seen = moved(bench)
    assert bench() == 1 and bench.lines == ["collected failed:main_moved claim=held release=released"]
    assert bench.attempt()[5] == seen and bench.execs() == []


def test_a_fault_of_the_environment_is_counted_once_the_attempt_is_the_entry_s_own(bench: Bench) -> None:
    bench.credentials = CredentialsUnavailable("git_config")
    assert bench() == 1 and bench() == 1
    assert bench.lines == ["unavailable fault:CredentialsUnavailable"] * 2
    assert bench.attempt()[:5] == ("admitted", None, None, "fault:CredentialsUnavailable", 2)


def test_a_lost_claim_still_marks_gone_unfinished_results_interrupted_before_it_concludes(bench: Bench) -> None:
    bench.beats = ["lost"]
    bench.result(1, 0, "check", None, pid=904)  # gone: its entry died mid-check
    assert bench() == 1 and bench.lines == ["collected failed:claim_lost claim=lost release=released"]
    assert bench.results() == [(1, "check", "interrupted")]
