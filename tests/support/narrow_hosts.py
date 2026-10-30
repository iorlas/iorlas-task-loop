"""Small typed fakes of what a slice reads of the engine (app/run/waits.py WaitsHost, app/land/outbound.py OutboundHost): a class that
has just those members, so the type checker proves the fake is enough and a slice that reads one more member breaks the test's types."""
import contextlib
import threading
from collections.abc import Callable, Generator, Mapping, Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

import support.paths  # noqa: F401
from support import homes
from support.fake_beads import FakeBeads
from support.fake_clock import FakeClock
from support.fakegit import FakeGit, ScriptedGit
from support.who import who
from taskloop.app.land.commit import Commit
from taskloop.app.land.fix_outside import FixOutside
from taskloop.app.land.gate import Gate, GateChecker
from taskloop.app.land.land_rebase import LandRebase
from taskloop.app.land.landed import Landed
from taskloop.app.land.lander import GateStep, Lander, LandParts
from taskloop.app.land.push import Pusher
from taskloop.app.land.recheck import Recheck
from taskloop.app.land.sync import Sync
from taskloop.app.run.budget import Budget
from taskloop.app.run.closer import CloseParts, Closer
from taskloop.app.run.steps import Steps
from taskloop.contracts import fence
from taskloop.contracts.checkpoint import Checkpoint, EndRec, Notes
from taskloop.contracts.checks import Check, CheckRun
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.enums import Outcome
from taskloop.contracts.ids import BeadId
from taskloop.contracts.kinds import Kind
from taskloop.contracts.plancheck import PlanCheck, PlanData, StageData
from taskloop.contracts.ports import Beads, Clock, DoltPush, Git
from taskloop.domain import outcome as oc
from taskloop.domain.asks.spec import AskSpec
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
        self.wt = "."
        self.dry = dry
        self.lines: list[str] = []  # what the log said
        self.log = RunLog(fake_stores().run_log("run"), echo=self.lines.append)
        self.clock = FakeClock()
        self.result = result
        self.ran: list[Sequence[str]] = []
        self.git: Git = ScriptedGit()

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


# ---- the land: one small fake per step (app/land/*.py), each with just the members that step's host Protocol lists ----

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


class Looks:
    def copy_looks(self) -> object:
        return None


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


class FakeCommitHost:
    """CommitHost."""

    def __init__(self, git: Git, sh: ShFn) -> None:
        self.bead = BeadId("t-1")
        self.git, self.sh = git, sh
        self.wt = "/wt"
        self.pictures = Looks()
        self.checkout = Stages()
        self.newfiles = Strays()

    def blocked_for(self, why: str, kind: str) -> Exception:
        return stopped(why, kind)


class FakeLandedHost:
    """LandedHost."""

    def __init__(self, git: Git, sh: ShFn, dry: bool = False, fetch: Fetches | None = None) -> None:
        self.landed_sha = ""
        self.bead = BeadId("t-1")
        self.cfg = EngineConfig(base="origin/main")
        self.dry = dry
        self.git, self.sh = git, sh
        self.wt = "/wt"
        self.checkout = fetch or Fetches()
        self.steps = Outcomes()
        self.warnings: list[str] = []

    def warn(self, text: str) -> None:
        self.warnings.append(text)


class FakeLandRebaseHost:
    """LandRebaseHost."""

    def __init__(self, git: Git, sh: ShFn) -> None:
        self.cfg = EngineConfig(base="origin/main")
        self.git, self.sh = git, sh
        self.wt = "/wt"
        self.steps = Outcomes()

    def blocked_for(self, why: str, kind: str) -> Exception:
        return stopped(why, kind)


class FakePushHost:
    """PushHost: a bd that is never asked (the claim is offline), a network that is `up`, a land command."""

    def __init__(self, git: Git, sh: ShFn, up: bool | None = True, cfg: EngineConfig | None = None) -> None:
        self.landed_sha = ""
        self.cfg = cfg or EngineConfig(base="origin/main", land=["git", "push", "-q", "origin", "HEAD:main"])
        self.git, self.sh = git, sh
        self.wt = "/wt"
        self.store: Beads = FakeBeads()
        self.claim = fence.offline(BeadId("t-1"))
        self.steps = OutcomesMoves()
        self.worker = Worker(up)
        self.warnings: list[str] = []

    def warn(self, text: str) -> None:
        self.warnings.append(text)

    def stop_deferred(self) -> AbstractContextManager[list[bool]]:
        return deferred()

    def blocked_for(self, why: str, kind: str) -> Exception:
        return stopped(why, kind)


class FakeRecheckHost:
    """RecheckHost: no plan, no cases; the checks answer `run`."""

    def __init__(self, events: list[str], run: CheckRun | None = None, plan: PlanData | None = None) -> None:
        self.pending_land_validation = ""
        self.plan_data = plan
        self.run_dir = Path("run")
        self.cases = NoCases()
        self.stage_checks = Checks(events, run)
        self.checkpoints = Keys()
        self.steps = Begins()

    def stop_deferred(self) -> AbstractContextManager[list[bool]]:
        return deferred()

    def blocked_for(self, why: str, kind: str) -> Exception:
        return stopped(why, kind)

    def move_host(self, needs: list[str], why: str) -> Exception:
        self.moved = [*getattr(self, "moved", []), *needs]
        return stopped(why, "PAUSE_MOVED")


class Fixes:
    def __init__(self, events: list[str]) -> None:
        self.events, self.kinds = events, list[str]()

    def fix(self, kind: str, tail: str, resume: bool = False) -> str:
        self.events.append("fix:" + kind)
        self.kinds.append(kind)
        return "accept"


class FakeFixOutsideHost:
    """FixOutsideHost: every fix is accepted."""

    def __init__(self, git: Git, sh: ShFn, events: list[str], rounds: int = 2) -> None:
        self.pending_land_validation = ""
        self.fixes = 0
        self.stuck_why = ""
        self.cfg = EngineConfig(max_fix_rounds=rounds)
        self.steps = Moves()
        self.fixer = Fixes(events)
        self.plan_data: PlanData | None = None
        self.checkpoints = Keys()
        self.checkout = Stages()
        self.git, self.sh = git, sh
        self.wt = "/wt"

    def blocked_for(self, why: str, kind: str) -> Exception:
        return stopped(why, kind)


class FakeSyncHost:
    """SyncHost: what the land recorded goes to `events`."""

    def __init__(self, events: list[str], dry: bool = False) -> None:
        self.bead = BeadId("t-1")
        self.dry = dry
        self.log_path = Path("/runs/t-1-r1.jsonl")
        self.checkpoints = Keys()
        self.events = events

    def record_land(self, sha: str) -> None:
        self.events.append("record " + sha)


class BdOut:
    """The after-the-land bd sync: fails while `fail`."""

    def __init__(self, events: list[str]) -> None:
        self.events, self.fail = events, False

    def bd_sync(self, sha: str) -> None:
        if self.fail:
            raise stopped("no route to the remote", "FAULT_LAND")
        self.events.append("sync")


class Gating:
    """The gate's checker when the repo has no gate step."""

    def run_items(self, items: Sequence[Check], everything: bool = False, learn: bool = False, show_clean: bool = False) -> CheckRun:
        raise AssertionError("the repo has no gate")

    def gate_green(self) -> bool:
        return False


class FakeGateHost:
    """GateHost: `checker` answers the gate (none by default: the repo has no gate step)."""

    def __init__(self, git: Git, cfg: EngineConfig, log: RunLog, checker: GateChecker | None = None) -> None:
        self.gate_log: Path | None = None
        self.cfg, self.log, self.git = cfg, log, git
        self.wt = "/wt"
        self.run_dir = Path("run")
        self.steps = Outcomes()
        self.checker: GateChecker = checker or Gating()

    def halt_point(self, when: bool = True, wait: float = 0) -> None:
        pass

    def blocked_for(self, why: str, kind: str) -> Exception:
        return stopped(why, kind)

    def move_host(self, needs: list[str], why: str) -> Exception:
        self.moved = [*getattr(self, "moved", []), *needs]
        return stopped(why, "PAUSE_MOVED")


class NoRun:
    def read(self) -> CheckRun | None:
        return None


class FakeLandHost:
    """LandHost: the Lander's own flow. `emitted()` is what its log said."""

    def __init__(
        self,
        git: Git,
        events: list[str],
        cfg: EngineConfig,
        fetch: Fetches | None = None,
        last_run: CheckRun | None = None,
        dry: bool = False,
    ) -> None:
        self.pending_land_validation = ""
        self.task_branch = ""
        self.cfg = cfg
        self.dry = dry
        self.stores: Stores = fake_stores()
        self.log = RunLog(self.stores.run_log("run"))
        self.last_run = last_run
        self.run_dir = Path("run")
        self.steps = Begins()
        self.checkout = fetch or Fetches()
        self.newfiles = Strays()
        self.waits = Locks(events)
        self.worker = Worker(True)
        self.git = git
        self.wt = "/wt"

    def land_lock_path(self) -> Path:
        return Path("lock")

    def blocked_for(self, why: str, kind: str) -> Exception:
        return stopped(why, kind)

    def move_host(self, needs: list[str], why: str) -> Exception:
        return stopped(why, "PAUSE_MOVED")

    def emitted(self) -> list[object]:
        return [row.rec for row in self.stores.run_log("run").read_from(0).items]


class LandKit:
    """A Lander composed of real steps, each over its own small fake host (the hosts are fields, to look into)."""

    def __init__(
        self,
        git_fn: Git,
        sh_fn: ShFn,
        cfg: EngineConfig | None = None,
        gate: GateStep | None = None,
        up: bool | None = True,
        fetch: Fetches | None = None,
        last_run: CheckRun | None = None,
        dry: bool = False,
        run: CheckRun | None = None,
        locks: Locks | None = None,
        checker: GateChecker | None = None,
        events: list[str] | None = None,
    ) -> None:
        self.events: list[str] = [] if events is None else events
        self.cfg = cfg or EngineConfig(base="origin/main", land_optimistic_tries=2, land=["git", "push", "-q", "origin", "HEAD:main"])
        self.land = FakeLandHost(git_fn, self.events, self.cfg, fetch, last_run, dry)
        if locks:
            self.land.waits = locks
        self.pushing = FakePushHost(git_fn, sh_fn, up, self.cfg)
        self.landing = FakeLandedHost(git_fn, sh_fn, dry, fetch)
        self.rebasing = FakeLandRebaseHost(git_fn, sh_fn)
        self.rechecking = FakeRecheckHost(self.events, run)
        self.fixing = FakeFixOutsideHost(git_fn, sh_fn, self.events)
        self.syncing = FakeSyncHost(self.events, dry)
        self.bd = BdOut(self.events)
        self.pusher = Pusher(self.pushing, NoLfs())
        parts = LandParts(
            gate=gate or Gate(FakeGateHost(git_fn, self.cfg, self.land.log, checker)), commit=Commit(FakeCommitHost(git_fn, sh_fn)),
            landed=Landed(self.landing), rebase=LandRebase(self.rebasing), recheck=Recheck(self.rechecking),
            push=self.pusher, fix=FixOutside(self.fixing), sync=Sync(self.syncing, self.bd), out=NoWip())
        self.lander = Lander(self.land, parts)


class NoLfs:
    def lfs_push(self) -> tuple[int, str]:
        return 0, ""


class NoWip:
    def wip_push(self, stage: int) -> None:
        pass


def table_kit(table: FakeGit, **kw: Any) -> LandKit:
    """A LandKit whose git and shell answer from a FakeGit table."""
    return LandKit(table, table.sh, **kw)


# ---- the close: one small fake per step (app/run/closer_*.py) ----

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


class Asks:
    def raise_ask(self, spec: AskSpec, why: str, kind: Kind) -> object:
        return None


class FakeCloseHost(Said):
    """CloseHost: the Closer's own flow, over an in-memory log. `dry` keeps the checkpoint out of it."""

    def __init__(self, dry: bool = True, disp: oc.Disposition | None = None) -> None:
        super().__init__()
        self.disp = disp
        self.kind = Kind.DONE
        self.fp = ""
        self.asked = False
        self.dead: Checkpoint | None = None
        self.bead = BeadId("t-1")
        self.stores: Stores = fake_stores()
        self.log = RunLog(self.stores.run_log("run"))
        self.stats = {"rounds": 0}
        self.leftovers: list[Mapping[str, str]] = []
        self.dry = dry
        self.claim = fence.offline(BeadId("t-1"))
        self.log_path = Path("/runs/t-1-r1.jsonl")
        self.checkpoints = CloseKeys()
        self.ask_flow = Asks()
        self.cost = 0.0
        self.t0 = 0.0
        self.halt = threading.Event()

    @property
    def git(self) -> Git:
        return ScriptedGit()

    @property
    def wt(self) -> str:
        return "/wt"

    def said(self) -> list[object]:
        return [row.rec for row in self.stores.run_log("run").read_from(0).items]


class CloseKeys(Keys):
    def keep_end(self, end: EndRec) -> None:
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
    def run(self, done: oc.RunOutcome, stats: str) -> None:
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
        self.closer = Closer(self.host, CloseParts(decide=SpyDecide(), branch=SpyBranch(self.calls), slot=self.slot, record=SpyRecord(),
                                                   notes=SpyNotes(), reflect=SpyReflect(), settle=SpySettle()))
