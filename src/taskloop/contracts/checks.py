"""The records of a check round: the planned Check, its CheckResult, the round's CheckRun (the file engine-checks.rN.json and the
`Checks` row of the run log are the same record), the cache of green results and the history of how long a command takes."""
from collections.abc import Iterator
from enum import StrEnum
from typing import ClassVar, Literal, override

from pydantic import Field

from taskloop.contracts.enums import CheckStatus
from taskloop.contracts.wire import Rec

Group = Literal["static", "tests", "acceptance"]
Verdict = Literal["passed", "failed", "skipped"]


class CheckFaultKind(StrEnum):
    STALE_BASE = "stale_base"  # the configured check needs something the tree lacks: older than the base's .task-loop.json
    KILLED = "killed"  # a signal ended the check, not its verdict


class Check(Rec):
    """One check of a round: a repo check (engine.checks) or a command of the plan (a stage's check, a case)."""

    id: str
    cmd: str
    group: Group = "tests"
    when: list[str] = Field(default_factory=list)
    retry: int = 0
    wall_min: float = 60.0
    cache: bool = True
    inputs: list[str] = Field(default_factory=list)
    inputs_only: bool = False
    exclude: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    repo: bool = False
    writer: bool | None = None  # True: the writer may run it, whatever it cost; False: never; None: by its duration
    writer_max_s: float | None = None  # its own cut for "too slow for the writer", else the engine's
    tail_log: str = ""  # a log of the tree whose compile errors join a red check's output when it shows none (project files not made)
    fix: str = ""  # a command (text) run before the round on the worktree: it rewrites what the check would only complain of
    container: bool = False  # run in a container on a copy of the worktree when docker is reachable (the host otherwise)


class CheckResult(Rec):
    id: str
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
    note: str = ""  # why a cached result stands
    base_red: bool = False  # red on the untouched base too: not the writer's
    producer: str = ""  # a skip because the check it reads did not run: that check's id
    sig: str = ""  # what a red's output says, timings aside: two reds with one sig failed the same way

    @classmethod
    def skipped(cls, check: Check, why: str, producer: str = "") -> "CheckResult":
        """The result of a check that did not run, and why."""
        return cls(id=check.id, cmd=check.cmd, group=check.group, exit=None, status="skipped", why=why, producer=producer)

    @classmethod
    def failed_run(cls, cmd: str, tail: str, group: str = "gate", log: str = "") -> "CheckResult":
        """A red run of a command that is not a check of a round (the gate, a rebase), to be shown like one."""
        return cls(id=cmd, cmd=cmd, group=group, exit=1, status="failed", tail=tail, log=log)

    @property
    def word(self) -> CheckStatus:
        """The one word the log shows: cached, timeout, passed, failed or skipped."""
        if self.cached:
            return CheckStatus.CACHED
        if self.exit == 124:
            return CheckStatus.TIMEOUT
        return CheckStatus(self.status)

    @property
    def red(self) -> bool:
        return self.exit not in (0, None)


class CheckRun(Rec):
    """Every result of one round, in the order the checks were decided."""

    V: ClassVar[int] = 1
    round: int
    tree: str = ""
    results: list[CheckResult] = Field(default_factory=list)
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


class CacheHit(Rec):
    result: CheckResult
    round: int = 0
    log_abs: str = ""  # the saved output of the run the result came from


class CheckCacheEntry(Rec):
    """check-cache/<bead>.json: green results of the latest tree (by command) and of every check's inputs (by their hash)."""

    V: ClassVar[int] = 1
    key: str = ""  # "<tree> <base sha>" the `whole` entries are facts about
    whole: dict[str, CacheHit] = Field(default_factory=dict)
    inputs: dict[str, CacheHit] = Field(default_factory=dict)
    base_red: dict[str, bool] = Field(default_factory=dict)  # "<base sha> <command>" -> red on that base


class Durations(Rec):
    """check-durations/<repo>.json: the seconds of the last runs of each command, newest last."""

    V: ClassVar[int] = 1
    runs: dict[str, list[float]] = Field(default_factory=dict)
