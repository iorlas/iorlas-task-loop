"""A CheckHost without an Engine (app/checks/host.py): what the check runner reads of its caller, built from the parts the checks stage and
the store layer own. A checks test on this host reaches the checks stage, not app/run/engine.py (docs/design/stage-test-hosts.md).
tests/checks/test_check_host_contract.py runs the same probes against this and a real Engine, so the two cannot drift."""
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import support.paths  # noqa: F401
from support.cfgs import cfg_with
from support.facts import fake_facts
from support.memstores import fake_stores
from support.who import who
from support.world import MARKERS, SlotWorld
from taskloop.app.checks.runner import Checker
from taskloop.app.land.checkout import Checkout
from taskloop.app.run import bead_env
from taskloop.app.run.shell import Shell
from taskloop.stores.bundle import Stores
from tlkernel import wire
from tlkernel.checks import CheckRun
from tlkernel.config import EngineConfig
from tlkernel.paths import ConfigDir
from tlkernel.plancheck import StageData
from tlkernel.ports import Clock
from tlkernel.waitenums import WaitWhat


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

    def __init__(self, wt: Path, cfg: EngineConfig, home: ConfigDir, bead: str = "t-1", stores: Stores | None = None,
                 nth: int = 0, clock: Clock | None = None) -> None:
        # the run's facts and ports come from one place (support/facts.py, docs/design/facts.md): this host is the checks' view of them
        run_id = f"FAKERUN{nth:04d}"
        self.facts, self.ports = fake_facts(Path(home.root), bead, cfg, wt=wt, home=home, run_id=run_id, stores=stores, clock=clock)
        f, p = self.facts, self.ports
        self.bead, self.wt, self.cfg, self.home, self.run_id, self.run_dir = f.bead, f.wt, f.cfg, f.home, f.run_id, f.run_dir
        self.env, self.spawner, self.git, self.stores, self.clock = p.env, p.spawner, p.git, p.stores, p.clock
        self.log, self.steps, self.checklog = p.log, p.steps, p.checklog
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
           stop: threading.Event | None = None, *, network: bool = False) -> tuple[int, str]:
        return self.shell.run(cmd, timeout, check, save, env, pin, what, cwd, stop, network=network)

    def run_checks(self, st: StageData, name: str, acceptance_first: bool = False, groups: Sequence[str] | None = None,
                   conflict_fix: Sequence[str] | None = None, **meta: Any) -> CheckRun:
        return self.checker.run(st["checks"], name, markers=self.MARKERS, acceptance_first=acceptance_first, groups=groups,
                                conflict_fix=conflict_fix, **meta)

    def blocked_for(self, why: str, kind: str) -> Exception:
        return RuntimeError(why)

    def blocked_stuck(self, why: str, what: str, rounds: int, signature: str) -> Exception:
        return RuntimeError(why)

    def halt_point(self, when: bool = True, wait: float = 0) -> None:
        return None

    def warn(self, text: str) -> None:
        self.log.warn(text)

    def detail(self, lines: list[str]) -> None:
        return None

    def records(self, *kinds: str) -> list[dict[str, Any]]:
        """The run's log records as wire dicts (what tltestkit.logs.records reads from a file), of `kinds` only when given."""
        seen = self.stores.run_log(self.run_id).read_from()
        return [row for row in (wire.dump(i.rec) for i in seen.items) if not kinds or row["kind"] in kinds]


class CheckHostCase(SlotWorld):
    """A checks test: the slot's world and a FakeCheckHost over it. `checks_engine(**cfg)` keeps the name of the EngineTest helper."""

    def checks_engine(self, attrs: Mapping[str, Any] | None = None, *, clock: Clock | None = None, **cfg: Any) -> FakeCheckHost:
        """Every host of one test shares its stores (the check cache, the run logs), as the engines of one test share a home."""
        stores = self.__dict__.setdefault("_check_stores", fake_stores())
        n = self.__dict__["_check_hosts"] = self.__dict__.get("_check_hosts", -1) + 1
        host = FakeCheckHost(self.wt, cfg_with(EngineConfig(), **cfg), who().config, stores=stores, nth=n, clock=clock)
        for k, v in (attrs or {}).items():
            setattr(host, k, v)
        return host
