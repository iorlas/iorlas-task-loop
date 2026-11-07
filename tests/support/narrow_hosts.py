"""Small typed hosts and helpers shared by pipeline, run, checks and land tests."""
import contextlib
import threading
from collections.abc import Callable, Generator, Mapping
from pathlib import Path

import support.paths  # noqa: F401
from support import homes
from support.fake_beads import FakeBeads
from support.fakegit import ScriptedGit
from support.memstores import fake_stores
from support.who import who
from taskloop.adapters import beadtools
from taskloop.stores.bundle import Stores
from taskloop.stores.runlog import RunLog
from tlkernel import fence
from tlkernel import runoutcome as oc
from tlkernel.askspec import AskSpec
from tlkernel.checkpoint import Checkpoint, CloseIntent, Notes
from tlkernel.checks import CheckRun
from tlkernel.config import EngineConfig
from tlkernel.delegate import Permanence
from tlkernel.enums import Outcome
from tlkernel.gitport import Git
from tlkernel.ids import BeadId
from tlkernel.kinds import Kind
from tlkernel.pausereasons import Producer
from tlkernel.plancheck import PlanCheck, StageData
from tlkernel.ports import Clock
from tlkernel.run import RunFinish
from tlpipeline.api import Budget, CloseParts, Closer, Steps
from tlpipeline.testing import FakeAskRules, FakeParkBook
from tltestkit.fake_clock import FakeClock


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
        self.run_id = "run"
        self.halted: list[str] = []

    @property
    def waited(self) -> float:
        return self.budget.waited

    @contextlib.contextmanager
    def os_lock(
        self,
        path: Path | str,
        holder: str,
        waiting: Callable[[str], None] | None = None,
        timeout: float | None = None,
        check: Callable[[], None] | None = None,
    ) -> Generator[Path | str]:
        yield path

    def halt_point(self, when: bool = True, wait: float = 0) -> None:
        self.halted.append("halt")



ShFn = Callable[..., tuple[int, str]]



class Stopped(Exception):
    """What a fake's blocked_for hands back: the reason and the kind the land stopped with."""

    def __init__(self, why: str, kind: str) -> None:
        super().__init__(why)
        self.why, self.kind = why, kind



def stopped(why: str, kind: str) -> Exception:
    return Stopped(why, kind)



class Outcomes:
    """steps.outcome, recorded."""

    def __init__(self) -> None:
        self.outcomes: list[tuple[str, str]] = []

    def outcome(self, outcome: str, detail: str = "") -> None:
        self.outcomes.append((outcome, detail))



class Moves:
    """steps.move, recorded."""

    def __init__(self) -> None:
        self.moves: list[tuple[str, str, str]] = []

    def move(self, to: str, cause: str, detail: str = "") -> None:
        self.moves.append((to, cause, detail))



class OutcomesMoves(Outcomes, Moves):
    def __init__(self) -> None:
        Outcomes.__init__(self)
        Moves.__init__(self)



class Begins:
    """steps.begin, recorded."""

    def __init__(self) -> None:
        self.begun: list[str] = []

    def begin(self, step: str, text: str, **meta: object) -> int:
        self.begun.append(text)
        return len(self.begun)



class Fetches:
    """checkout.fetch, answered from `reply`."""

    def __init__(self, reply: tuple[int, str] = (0, ""), on_fetch: Callable[[], None] | None = None) -> None:
        self.reply, self.on_fetch = reply, on_fetch

    def fetch(self, check: bool = False) -> tuple[int, str]:
        if self.on_fetch:
            self.on_fetch()
        return self.reply



class Stages:
    """checkout.stage_all, counted."""

    def __init__(self) -> None:
        self.staged = 0

    def stage_all(self, check: bool = False, everything: bool = False) -> int:
        self.staged += 1
        return 0



class Strays:
    def quarantine_strays(self) -> list[str]:
        return []



class Keys:
    """The checkpoint's ledger of applied effects, and the saves the land makes."""

    def __init__(self) -> None:
        self.keys: set[str] = set()
        self.saved: list[dict[str, object]] = []

    def save(self, *, step: str = "", stage: int = 0, rounds: int = 0, n: int = 0, feedback: str = "") -> None:
        self.saved.append({"step": step, "stage": stage})

    def applied(self) -> frozenset[str]:
        return frozenset(self.keys)

    def mark_applied(self, key: str) -> None:
        self.keys.add(key)



class Net:
    def __init__(self, up: bool | None = True) -> None:
        self.up = up

    def net_up(self) -> bool | None:
        return self.up

    def await_net(self, up: bool | None, max_s: float) -> tuple[float, bool]:
        return 0.0, True



class Worker:
    def __init__(self, up: bool | None = True) -> None:
        self.net = Net(up)

    @property
    def acts(self) -> Net:
        return self.net



class Locks:
    """waits.locked: the lock is entered and left in `events`; `held` while it is."""

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.held = False

    @contextlib.contextmanager
    def locked(self, what: str, path: Path | str, holder: str | None = None) -> Generator[Path | str]:
        self.events.append("enter")
        self.held = True
        try:
            yield path
        finally:
            self.held = False
            self.events.append("exit")



@contextlib.contextmanager
def deferred() -> Generator[list[bool]]:
    yield []



class NoCases:
    def case_checks(self) -> list[PlanCheck]:
        return []



class Checks:
    """stage_checks.stoppable: answers `run`, and says it ran."""

    def __init__(self, events: list[str], run: CheckRun | None = None) -> None:
        self.events, self.run = events, run or CheckRun(round=1, results=[])

    def stoppable(self, st: StageData, name: str) -> CheckRun:
        self.events.append("checks")
        return self.run



class Fixes:
    def __init__(self, events: list[str]) -> None:
        self.events, self.kinds = events, list[str]()

    def fix(self, kind: str, tail: str, resume: bool = False) -> str:
        self.events.append("fix:" + kind)
        self.kinds.append(kind)
        return "accept"



class Said:
    """comment and warn, recorded (a host that has both)."""

    def __init__(self) -> None:
        self.comments: list[str] = []
        self.warnings: list[str] = []

    def comment(self, text: str) -> None:
        self.comments.append(text)

    def warn(self, text: str) -> None:
        self.warnings.append(text)



class FakeSettleHost(Said):
    """SettleHost: bd in memory, an offline claim, no plan summary."""

    def __init__(self, disp: oc.Disposition | None = None) -> None:
        super().__init__()
        self.bead = BeadId("t-1")
        self.claim = fence.offline(BeadId("t-1"))
        self.who = who()
        self.home = homes.cfg()
        self.store = FakeBeads()
        self.cfg = EngineConfig(base="origin/main")
        self.plan_summary = ""
        self.log_path = Path("t-1-20261030-120000.jsonl")
        self.run_id = "t-1-20261030-120000"
        self.disp = disp



class Leaves:
    """tree.leave_slot, recorded."""

    def __init__(self) -> None:
        self.left: list[tuple[str, str]] = []

    def leave_slot(self, outcome: str, branch: str) -> None:
        self.left.append((outcome, branch))



class FakeReleaseSlotHost:
    """ReleaseSlotHost."""

    def __init__(self) -> None:
        self.claim = fence.offline(BeadId("t-1"))
        self.store = FakeBeads()
        self.tree = Leaves()
        self.git: Git = ScriptedGit()
        self.log = RunLog(fake_stores().run_log("run"))
        self.who = who()
        self.home = self.who.config
        self.wt = "/wt"



class Asks:
    def raise_ask(self, spec: AskSpec, why: str, kind: Kind) -> object:
        return None



class CloseRecords:
    def finish(self, done: oc.RunOutcome, stats: str = "",
               record: Callable[[RunFinish, str], None] | None = None) -> oc.RunOutcome:
        return done

    def log_run(self) -> None:
        pass

    def file_trace(self, record: RunFinish) -> None:
        pass



class FakeCloseHost(Said):
    """Close flow roles: the Closer's own flow, over an in-memory log. `dry` keeps the checkpoint out of it."""

    def __init__(self, dry: bool = True, disp: oc.Disposition | None = None) -> None:
        super().__init__()
        self.disp = disp
        self.kind = Kind.DONE
        self.fp = ""
        self.asked = False
        self.dead: Checkpoint | None = None
        self.bead = BeadId("t-1")
        self.plan_summary = ""
        self.stores: Stores = fake_stores()
        self.log = RunLog(self.stores.run_log("run"))
        self.stats = {"rounds": 0}
        self.leftovers: list[Mapping[str, str]] = []
        self.sessions: list[Mapping[str, str]] = []
        self.dry = dry
        self.claim = fence.offline(BeadId("t-1"))
        self.run_id = "t-1-r1"
        self.checkpoints = CloseKeys()
        self.records = CloseRecords()
        self.ask_flow = Asks()
        self.cost = 0.0
        self.t0 = 0.0
        self.halt = threading.Event()
        self.home = homes.cfg()
        self.store = FakeBeads()
        self.clock = FakeClock()
        self.retry_after = 0.0
        self.pause_reason = ""
        self.pause_producer: Producer = "engine"
        self.pause_permanence: Permanence | None = None
        self.why = ""
        self.crash_fingerprint = ""
        self.crash_site = ""

    @property
    def git(self) -> Git:
        return ScriptedGit()

    @property
    def wt(self) -> str:
        return "/wt"

    def said(self) -> list[object]:
        return [row.rec for row in self.stores.run_log("run").read_from(0).items]



class CloseKeys(Keys):
    def keep_end(self, intent: CloseIntent) -> None:
        pass

    def drop_unless_fenced(self) -> None:
        pass



class SpyDecide:
    def run(self, o: oc.RunOutcome) -> Kind:
        return o.kind



class SpyBranch:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def run(self, outcome: Outcome, why: str) -> None:
        self.calls.append(f"branch {outcome}")



class SpySlot:
    def __init__(self) -> None:
        self.left: list[tuple[str, Outcome]] = []

    def run(self, branch: str, outcome: Outcome) -> None:
        self.left.append((branch, outcome))



class SpyRecord:
    def run(self, record: RunFinish, stats: str) -> None:
        pass



class SpyNotes:
    def run(self, outcome: Outcome) -> Notes:
        return Notes(filed=0, unfiled=0)



class SpyReflect:
    def comment(self, outcome: Outcome, why: str, stats: str, noted: Notes | None) -> None:
        pass



class SpySettle:
    def run(self, done: oc.RunOutcome, stats: str) -> None:
        pass



class CloseKit:
    """A Closer over a FakeCloseHost whose steps are spies (the steps themselves are tested over their own hosts)."""

    def __init__(self, dry: bool = True) -> None:
        self.host = FakeCloseHost(dry)
        self.slot = SpySlot()
        self.calls: list[str] = []
        self.closer = Closer(
            self.host, self.host, self.host,
            CloseParts(
                decide=SpyDecide(),
                branch=SpyBranch(self.calls),
                slot=self.slot,
                record=SpyRecord(),
                notes=SpyNotes(),
                reflect=SpyReflect(),
                settle=SpySettle(),
            ), FakeAskRules(), FakeParkBook(),
            beadtools.peek)
