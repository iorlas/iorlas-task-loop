"""The shared validation (tl-8bh9.14.8 slice L2) with a land candidate's target, over a factory.db file (the
`candidate_on_slot` candidate S of `CHECKS`), the semantic Git fake's slot, the slot environment and block over `doubles`'
scripted registered start and profile port: the checks step's machinery under the candidate's key, with no `main` watch.
The checks attempt's own target is pinned by `test_check_entry`, unchanged by the extraction."""

import dataclasses
import json
import sqlite3
from collections.abc import Generator
from pathlib import Path

import pytest
from doubles import CANDIDATE, REQUIRED, Command, Environment, FakeProfiles, FakeSlotFiles, PinnedViews
from git_porcelain import Recorded
from git_porcelain.testing import FakeWorktree
from sqlite_store import Store

from taskloop.attempt_types import AttemptResult
from taskloop.check_store import CheckStore
from taskloop.checks import Block, BlockPorts
from taskloop.composition import Checking
from taskloop.evidence_files import EvidenceFiles
from taskloop.factory_schema import SCHEMA
from taskloop.land_store import LandStore
from taskloop.setup_store import SetupStore
from taskloop.validate import Ended, Target, Verdict, reconcile, validate

PROFILE = {"setup": [["just", "bootstrap"]], "required": ["check", "test"], "checks": [
    {"name": "check", "argv": ["just", "check"], "timeout": 600}, {"name": "test", "argv": ["just", "test"], "timeout": 30}]}
RUN = ["exec just bootstrap", "exec just check", "exec just test"]


@dataclasses.dataclass
class Bench:
    """One candidate's validation: `environment` holds the shared `events`, the scripted start and the observations."""

    con: sqlite3.Connection
    slot: FakeWorktree
    views: PinnedViews
    files: FakeSlotFiles
    environment: Environment
    s: str
    now: float = 10.0

    def __post_init__(self) -> None:
        self.store, self.lands = CheckStore(lambda: self.con), LandStore(lambda: self.con)
        self.d = self.head()
        self.environment.clock = lambda: self.now
        self.environment.profiles = FakeProfiles(blob=json.dumps(PROFILE).encode())

    def head(self) -> str:
        found = next(info.head for info in self.slot.repo.worktrees() if info.path == self.slot.path)
        assert found is not None
        return found

    def checking(self) -> Checking:
        env = self.environment
        block = Block(BlockPorts(env.process, env.process.lingering, lambda: self.now))
        return Checking(self.store, SetupStore(lambda: self.con), EvidenceFiles(env.artifacts), self.views, self.files, env.profiles,
                        env.preparation(), block, env.observe, lambda _entry: "gone", lambda _path: True, lambda: self.now,
                        lambda: {"HOME": "/home/p"})

    def target(self) -> Target:
        return Target(CANDIDATE, self.slot.repo.identity().key, str(self.slot.path), self.s, REQUIRED, 300.0, None,
                      lambda digest: self.lands.profiled(CANDIDATE, digest))

    def __call__(self) -> Ended:
        return validate(self.checking(), self.target(), lambda: "held")

    def results(self) -> list[tuple[object, ...]]:
        return self.con.execute("SELECT attempt_id,block,name,conclusion FROM check_result ORDER BY block,position").fetchall()

    def result(self, block: int, position: int, name: str, conclusion: str | None, pid: int | None = None) -> None:
        """A result row of an earlier land process, written straight into the table under the candidate's key."""
        self.con.execute("""INSERT INTO check_result (attempt_id,dispatch_token,generation,block,position,name,argv_digest,timeout,
            pid,pgid,proc_start,boot,started_at,ended_at,conclusion) VALUES ('candidate','candidate-token',1,?,?,?,?,60,?,?,?,?,1,?,?)""",
                         (block, position, name, "e" * 64, pid, pid, None if pid is None else "start", None if pid is None else "boot",
                          None if conclusion is None else 2, conclusion))


@pytest.fixture
def bench(candidate_on_slot: tuple[Path, str], slot: FakeWorktree, checkouts: PinnedViews, slot_files: FakeSlotFiles,
          tmp_path: Path) -> Generator[Bench]:
    path, s = candidate_on_slot
    con = Store(SCHEMA).open_rw(path)
    assert con is not None
    yield Bench(con, slot, checkouts, slot_files, Environment(con, checkouts, tmp_path / "art", tmp_bytes=4096), s)
    con.close()


def test_a_candidate_s_block_runs_at_s_under_its_own_key_and_passes(bench: Bench) -> None:
    """Setup and every check at S, results and setup runs under the candidate's key, the digest on the candidate; the
    checks attempt's own rows untouched. `main` moving during the block is not watched (the names were read at O)."""
    heads: list[str] = []

    def moved() -> None:
        heads.append(bench.head())
        root = bench.slot.repo.worktree(bench.slot.repo.identity().root)
        root.write_file("README", "main moved")
        assert isinstance(root.record("a person's commit", paths="all"), Recorded)

    bench.environment.process.script = [Command(effect=moved)]
    assert bench() == Verdict("passed")
    assert heads == [bench.s] and [e for e in bench.environment.events if e.startswith("exec")] == RUN
    assert bench.results() == [("candidate", 1, "check", "passed"), ("candidate", 1, "test", "passed")]
    assert bench.con.execute("SELECT DISTINCT attempt_id FROM setup_run").fetchall() == [("candidate",)]
    assert bench.con.execute("SELECT profile_digest IS NOT NULL FROM land_candidate").fetchone() == (1,)
    assert bench.con.execute("SELECT profile_digest,phase FROM checks_attempt").fetchone() == (None, "concluded")


def test_a_failed_required_check_fails_the_candidate_with_its_reason(bench: Bench) -> None:
    bench.environment.process.script = [Command(), Command(), Command(rc=1)]
    assert bench() == Verdict("failed", "test:failed")


@pytest.mark.parametrize(("seen", "word"), [("alive", "checks:running"), ("unknown", "checks:unknown")])
def test_a_surviving_check_of_a_killed_land_process_is_reconciled_first(bench: Bench, seen: str, word: str) -> None:
    """`kill -9` of the land: its check may still run; nothing is read, reset or run until it is gone."""
    bench.result(1, 0, "check", None, pid=900)
    bench.environment.seen[900] = "alive" if seen == "alive" else "unknown"
    assert bench() == AttemptResult("unavailable", word)
    assert bench.environment.events == ["seen 900"] and bench.head() == bench.d


def test_an_interrupted_candidate_block_repeats_whole(bench: Bench) -> None:
    """Ctrl-C stopped the check's tree: the rerun marks it `interrupted` and runs the block again."""
    bench.result(1, 0, "check", "passed")
    bench.result(1, 1, "test", None, pid=901)
    assert bench() == Verdict("passed")
    assert [row[1:] for row in bench.results()] == [(1, "check", "passed"), (1, "test", "interrupted"), (2, "check", "passed"),
                                                    (2, "test", "passed")]


def test_a_completed_candidate_block_concludes_as_it_stands_and_past_the_deadline_nothing_runs(bench: Bench) -> None:
    bench.result(1, 0, "check", "passed")
    bench.result(1, 1, "test", "passed")
    assert bench() == Verdict("passed") and bench.environment.events == [] and bench.head() == bench.d
    bench.now = 300
    assert bench() == Verdict("failed", "expired")


def test_the_reconcile_alone_marks_a_gone_unfinished_result_interrupted(bench: Bench) -> None:
    """A claim lost at the first renewal: only the reconcile runs before the conclusion."""
    bench.result(1, 0, "check", None, pid=902)
    assert reconcile(bench.checking(), bench.target()) is None
    assert bench.results() == [("candidate", 1, "check", "interrupted")] and bench.head() == bench.d
