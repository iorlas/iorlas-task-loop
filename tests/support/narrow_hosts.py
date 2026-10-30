"""Small typed fakes of what a slice reads of the engine (app/run/waits.py WaitsHost, app/land/outbound.py OutboundHost): a class that
has just those members, so the type checker proves the fake is enough and a slice that reads one more member breaks the test's types."""
import contextlib
from collections.abc import Callable, Generator, Mapping, Sequence
from pathlib import Path

import support.paths  # noqa: F401
from support.fake_clock import FakeClock
from taskloop.app.run.budget import Budget
from taskloop.app.run.steps import Steps
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.ids import BeadId
from taskloop.contracts.ports import Clock, DoltPush
from taskloop.stores.bundle import Stores
from taskloop.stores.memory import fake_stores
from taskloop.stores.runlog import RunLog


class FakeWaitsHost:
    """WaitsHost: a log in memory, a clock that stands still, a real budget and step book over them, and a lock that never waits."""

    def __init__(self, bead: str = "t-1", bead_token_cap: int = 0) -> None:
        self.bead = BeadId(bead)
        self.cfg = EngineConfig(bead_token_cap=bead_token_cap)
        self.stores: Stores = fake_stores()
        self.log = RunLog(self.stores.run_log("run"))
        self.fake_clock = FakeClock()
        self.clock: Clock = self.fake_clock
        self.budget = Budget(self.cfg, self.clock.now)
        self.steps = Steps(self.log, self.clock.now)
        self.stats = {"tokens_in": 0, "tokens_out": 0}
        self.log_path = Path("run.jsonl")
        self.waited = 0.0
        self.halted: list[str] = []

    @contextlib.contextmanager
    def os_lock(self, path: Path | str, holder: str, waiting: Callable[[str], None] | None = None, timeout: float | None = None,
                check: Callable[[], None] | None = None) -> Generator[Path | str]:
        yield path

    def halt_point(self, when: bool = True, wait: float = 0) -> None:
        self.halted.append("halt")


class FakeOutboundHost:
    """OutboundHost: bd answers `dolt_push` from `result`; commands and notes are recorded."""

    def __init__(self, dry: bool = False, result: tuple[int, str] = (0, "")) -> None:
        self.bead = BeadId("t-1")
        self.cfg = EngineConfig(land=["git", "push", "origin", "HEAD:main"])
        self.wt: str | Path = "."
        self.dry = dry
        self.lines: list[str] = []  # what the log said
        self.log = RunLog(fake_stores().run_log("run"), echo=self.lines.append)
        self.clock = FakeClock()
        self.result = result
        self.ran: list[Sequence[str]] = []

    @property
    def store(self) -> FakeBd:
        return FakeBd(self.result)

    @property
    def checkout(self) -> FakeCheckout:
        return FakeCheckout()

    @property
    def tree(self) -> FakeTree:
        return FakeTree()

    def sh(self, cmd: Sequence[str], timeout: float = 3600, check: bool = False, save: Path | None = None,
           env: Mapping[str, str] | None = None, pin: bool = False, what: str = "command", cwd: Path | None = None) -> tuple[int, str]:
        self.ran.append(cmd)
        return 0, ""

    def blocked_for(self, why: str, kind: str) -> Exception:
        return RuntimeError(f"{kind}: {why}")


class FakeCheckout:
    def stage_all(self, check: bool = False, everything: bool = False) -> int:
        return 0


class FakeTree:
    def wip(self, why: str, everything: bool = True) -> bool:
        return False


class FakeBd:
    def __init__(self, result: tuple[int, str]) -> None:
        self.result = result

    def dolt_push(self) -> DoltPush:
        return DoltPush(*self.result)
