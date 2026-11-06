"""A CheckHost without an Engine (app/checks/host.py): what the check runner reads of its caller, built from the parts the checks stage and
the store layer own. A checks test on this host reaches the checks stage, not app/run/engine.py (docs/design/stage-test-hosts.md).
tests/checks/test_check_host_contract.py runs the same probes against this and a real Engine, so the two cannot drift."""
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import support.paths  # noqa: F401
from support.cfgs import cfg_with
from support.fake_clock import FakeClock
from support.memstores import fake_stores
from support.spawn import port_git, real_spawner
from support.who import who
from support.world import MARKERS, SlotWorld
from taskloop.app.checks.checklog import CheckLog
from taskloop.app.checks.runner import Checker
from taskloop.app.land.checkout import Checkout
from taskloop.app.run import bead_env
from taskloop.app.run.shell import Shell
from taskloop.app.run.steps import Steps
from taskloop.contracts import wire
from taskloop.contracts.checks import CheckRun
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.enums import WaitWhat
from taskloop.contracts.env import snapshot
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.plancheck import StageData
from taskloop.stores.runlog import RunLog


class RecordedWaits:
    """WaitsView: the waits a check reported, kept in a list."""

    def __init__(self) -> None:
        self.seen: list[tuple[str, float]] = []

    def note_slot_waits(self, text: str, wall: float) -> None:
        self.seen.append((text, wall))

    def start(self, what: WaitWhat, holder: str = "", until: float | None = None, lane: str = "", check: str = "") -> str:
        return f"w{len(self.seen)}"

    def add(self, secs: float, what: WaitWhat, wid: str | None = None, lane: str = "", check: str = "") -> None:
        self.seen.append((what.value, secs))


class FakeCheckHost:
    MARKERS = MARKERS

    def __init__(self, wt: Path, cfg: EngineConfig, home: ConfigDir, bead: str = "t-1") -> None:
        self.bead, self.wt, self.cfg, self.home = bead, str(wt), cfg, home
        self.run_id = "FAKERUN0000"
        self.run_dir = Path(home.root) / "runs" / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.env = snapshot()
        self.spawner, self.git = real_spawner(), port_git()
        self.stores = fake_stores()
        self.clock = FakeClock()
        self.log = RunLog(self.stores.run_log(self.run_id), clock=self.clock.now, run_id=self.run_id, bead=bead, host="host")
        self.steps = Steps(self.log, self.clock.now)
        self.checklog = CheckLog(self.log)
        self.waits = RecordedWaits()
        self.halt = threading.Event()
        self.killed = False
        self.wall_hit = False
        self.tree_memo = None
        self.accepted_new: list[str] = []
        self.plan_data = None
        self.checkout = Checkout(self)
        self.tree_writer = self.checkout
        self.shell = Shell(self)
        self.checker = Checker(self, lambda secs: None)
        self.bead_env: Mapping[str, str] = bead_env.bead_env(self)

    def sh(self, cmd: Sequence[str], timeout: float = 3600, check: bool = False, save: Path | None = None,
           env: Mapping[str, str] | None = None, pin: bool = False, what: str = "command", cwd: Path | None = None,
           stop: threading.Event | None = None) -> tuple[int, str]:
        return self.shell.run(cmd, timeout, check, save, env, pin, what, cwd, stop)

    def run_checks(self, st: StageData, name: str, acceptance_first: bool = False, groups: Sequence[str] | None = None,
                   conflict_fix: Sequence[str] | None = None, **meta: Any) -> CheckRun:
        return self.checker.run(st["checks"], name, markers=self.MARKERS, acceptance_first=acceptance_first, groups=groups,
                                conflict_fix=conflict_fix, **meta)

    def blocked_for(self, why: str, kind: str) -> Exception:
        return RuntimeError(why)

    def halt_point(self, when: bool = True, wait: float = 0) -> None:
        return None

    def warn(self, text: str) -> None:
        self.log.warn(text)

    def detail(self, lines: list[str]) -> None:
        return None

    def records(self, *kinds: str) -> list[dict[str, Any]]:
        """The run's log records as wire dicts (what support.logs.records reads from a file), of `kinds` only when given."""
        seen = self.stores.run_log(self.run_id).read_from()
        return [row for row in (wire.dump(i.rec) for i in seen.items) if not kinds or row["kind"] in kinds]


class CheckHostCase(SlotWorld):
    """A checks test: the slot's world and a FakeCheckHost over it. `checks_engine(**cfg)` keeps the name of the EngineTest helper."""

    def checks_engine(self, attrs: Mapping[str, Any] | None = None, **cfg: Any) -> FakeCheckHost:
        host = FakeCheckHost(self.wt, cfg_with(EngineConfig(), **cfg), who().config)
        for k, v in (attrs or {}).items():
            setattr(host, k, v)
        return host
