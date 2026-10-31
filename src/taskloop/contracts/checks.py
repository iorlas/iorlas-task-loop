"""The records of a check round: the planned Check, its CheckResult, the round's CheckRun (the file engine-checks.rN.json and the
`Checks` row of the run log are the same record), the cache of green results and the history of how long a command takes."""
from collections.abc import Iterator
from enum import StrEnum
from typing import ClassVar, Literal, assert_never, final, override

import msgspec

from taskloop.contracts.enums import CheckStatus
from taskloop.contracts.ids import CheckId, TreeSha
from taskloop.contracts.row import Row
from taskloop.contracts.runkey import BaseSha, RunKey
from taskloop.contracts.wire import Rec

Group = Literal["static", "tests", "acceptance"]
Tag = Literal["diff", "unity", "build"]  # diff: the engine's own; unity: queues for a slot; build: a conflict fix keeps it
Verdict = Literal["passed", "failed", "skipped", "unverified"]


class RoundVerdict(StrEnum):
    """How a check round came out: the one union every reader matches (assert_never), never a word compared by hand."""
    RED = "red"
    UNVERIFIED = "unverified"
    GREEN = "green"


def round_verdict_of(word: str) -> RoundVerdict | None:
    """The verdict a check node stored, or None when the node did not end as a round (a stop, a pause)."""
    try:
        return RoundVerdict(word)
    except ValueError:
        return None


UNVERIFIED_EXIT = 86  # exit code of a check that could not verify (a missing tool, host or resource): never a pass


def verdict_of(rc: int) -> Verdict:
    """The verdict of a check that ran and exited with rc (a skipped check never ran)."""
    return "passed" if rc == 0 else "unverified" if rc == UNVERIFIED_EXIT else "failed"


class Phase(StrEnum):
    """Where a repo check runs: the round after each write (STAGE) or land's gate (GATE). The wall limit follows the phase."""

    STAGE = "stage"
    GATE = "gate"


class CheckFaultKind(StrEnum):
    STALE_BASE = "stale_base"  # the configured check needs something the tree lacks: older than the base's .task-loop.json
    KILLED = "killed"  # a signal ended the check, not its verdict


@final
class Check(Rec):
    """One check of a round: a repo check (engine.checks) or a command of the plan (a stage's check, a case)."""

    id: CheckId
    cmd: str
    group: Group = "tests"
    when: list[str] = msgspec.field(default_factory=list)
    retry: int = 0
    wall_min: float = 60.0
    cache: bool = True
    inputs: list[str] = msgspec.field(default_factory=list)
    inputs_only: bool = False
    exclude: list[str] = msgspec.field(default_factory=list)
    selected: list[str] = msgspec.field(default_factory=list)  # the tests the command resolved to run (empty: all); part of the result key
    env: dict[str, str] = msgspec.field(default_factory=dict)
    repo: bool = False
    writer: bool | None = None  # True: the writer may run it, whatever it cost; False: never; None: by its duration
    writer_max_s: float | None = None  # its own cut for "too slow for the writer", else the engine's
    tail_log: str = ""  # a log of the tree whose compile errors join a red check's output when it shows none (project files not made)
    keep: list[str] = msgspec.field(default_factory=list)  # globs in the tree of files copied into the run folder after each attempt
    fix: str = ""  # a command (text) run before the round on the worktree: it rewrites what the check would only complain of
    container: bool = False  # run in a container on a copy of the worktree when docker is reachable (the host otherwise)
    reads: list[CheckId] = msgspec.field(default_factory=list)  # registered checks whose log and exit code it reads: it runs after them
    tags: list[Tag] = msgspec.field(default_factory=list)
    needs: list[str] = msgspec.field(default_factory=list)  # resources it holds a machine-wide lease on while it runs
    lane: str = ""  # its lane: the checks of one run in order, the lanes in parallel


@final
class CheckResult(Rec):
    id: CheckId
    cmd: str
    group: str
    exit: int | None  # None: it did not run
    status: Verdict
    tries: int = 1
    tail: str = ""
    secs: float = 0.0
    log: str = ""  # relative to the run folder; empty when this run wrote none (skipped, cached, reused)
    wall_hit: bool = False  # stopped by the engine at the check's wall limit
    wall_min: float = 0.0  # the limit it ran under (minutes); 0: not recorded
    cached: bool = False
    reused: bool = False
    why: str = ""  # a skip's reason
    planned: bool = False  # skipped only because the diff did not touch `when`; satisfied after a clean round
    note: str = ""  # why a cached result stands
    base_red: bool = False  # red on the untouched base too: not the writer's
    producer: str = ""  # a skip because the check it reads did not run: that check's id
    tags: list[Tag] = msgspec.field(default_factory=list)
    waited: float = 0.0  # seconds it queued for the leases of its `needs` before it ran (not part of secs)
    deferred: list[str] = msgspec.field(default_factory=list)  # the resources this host lacks: it did not run (exit UNVERIFIED_EXIT)
    inputs_changed: bool = False  # deferred: the diff touches what it reads, so the land may not go on past it
    lane: str = ""  # the lane it ran in
    at: float = 0.0  # seconds after its block began that it started (lane timing; with `secs` and `waited`: where its lane's time went)
    cancelled: bool = False  # not run, or stopped, because another lane went red first: not a verdict on this check
    sig: str = ""  # what a red's output says, timings aside: two reds with one sig failed the same way

    @classmethod
    def skipped(cls, check: Check, why: str, producer: str = "") -> CheckResult:
        """The result of a check that did not run, and why."""
        return cls(id=check.id, cmd=check.cmd, group=check.group, exit=None, status="skipped", why=why, producer=producer,
                   tags=list(check.tags), lane=check.lane)

    @classmethod
    def cancelled_by(cls, check: Check, red: str, log: str = "", at: float = 0.0, secs: float = 0.0) -> CheckResult:
        """A check another lane's red stopped (or kept from starting): skipped, never a verdict; `log` holds what it printed before."""
        return cls.skipped(check, f"cancelled: {red} failed first").replace(cancelled=True, log=log, at=at, secs=secs)

    @classmethod
    def failed_run(cls, cmd: str, tail: str, group: str = "gate", log: str = "") -> CheckResult:
        """A red run of a command that is not a check of a round (the gate, a rebase), to be shown like one."""
        return cls(id=CheckId(cmd), cmd=cmd, group=group, exit=1, status="failed", tail=tail, log=log)

    @property
    def word(self) -> CheckStatus:
        """The one word the log shows: cached, timeout, passed, failed, skipped or unverified."""
        if self.cached:
            return CheckStatus.CACHED
        if self.exit == 124:
            return CheckStatus.TIMEOUT
        match self.status:
            case "passed":
                return CheckStatus.PASSED
            case "failed":
                return CheckStatus.FAILED
            case "skipped":
                return CheckStatus.SKIPPED
            case "unverified":
                return CheckStatus.UNVERIFIED
            case never:
                assert_never(never)

    @property
    def red(self) -> bool:
        return self.exit not in (0, None)


@final
class CheckRun(Rec):
    """Every result of one round, in the order the checks were decided."""

    V: ClassVar[int] = 1
    round: int
    tree: TreeSha = TreeSha("")
    results: list[CheckResult] = msgspec.field(default_factory=list)
    hits: int = 0
    misses: int = 0

    @property
    def failed(self) -> list[CheckResult]:
        """The checks that are the writer's to fix: red here, and not red on the untouched base too."""
        return [c for c in self.results if c.status == "failed" and not c.base_red]

    @property
    def base_red(self) -> list[CheckResult]:
        return [c for c in self.results if c.base_red]

    @property
    def passed(self) -> list[CheckResult]:
        return [c for c in self.results if c.status == "passed"]

    @property
    def unverified(self) -> list[CheckResult]:
        """The checks that could not verify: not passed, and nothing for the writer to fix."""
        return [c for c in self.results if c.status == "unverified"]

    @property
    def verdict(self) -> RoundVerdict:
        """The round's one outcome: red (a check failed), else unverified (one could not verify), else green."""
        return RoundVerdict.RED if self.failed else RoundVerdict.UNVERIFIED if self.unverified else RoundVerdict.GREEN

    @override
    def __iter__(self) -> Iterator[CheckResult]:  # pyrefly: ignore[bad-override]  a run iterates its results
        return iter(self.results)

    def __len__(self) -> int:
        return len(self.results)

    def __getitem__(self, i: int) -> CheckResult:
        return self.results[i]

    def signature(self) -> str:
        """What the round's reds say, whatever the round number: the red checks and their last output line."""
        return "|".join(sorted(f"{c.id}:{c.exit}:{c.sig}" for c in self.failed))


@final
class PassRecord(Rec):
    """results/<repo>/<check>/<key digest>.json: one remembered pass or planned skip and the key it holds for. `tree` and `base` are the
    tree and base it was last true for (a key without them is true for any). run_id, host, ts: who made it; `origin`: the run that
    first made the result when this record is a reuse on a newer tree or base. log_abs: the saved output (may be gone: it expires)."""

    V: ClassVar[int] = 1
    key: RunKey
    result: CheckResult
    tree: TreeSha
    base: BaseSha
    run_id: str = ""
    host: str = ""
    ts: float = 0.0
    origin: str = ""
    round: int = 0
    log_abs: str = ""


@final
class BaseRedRecord(Rec):
    """results/<repo>/base-red/<key digest>.json: whether a check was red on the untouched base (`key.base`)."""

    V: ClassVar[int] = 1
    key: RunKey
    red: bool
    run_id: str = ""
    host: str = ""
    ts: float = 0.0


@final
class Duration(Row, tag="duration"):
    """One passed run of a command, as a row: `step` is the normalised command, `exec_seconds` what it took, and the head says which
    run, bead, tree and base it was."""

    outcome: str = "passed"


@final
class Durations(Rec):
    """check-durations/<repo>.json: the rows of the last runs of each command (step), newest last."""

    V: ClassVar[int] = 2
    rows: list[Duration] = msgspec.field(default_factory=list)
