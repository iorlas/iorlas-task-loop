"""Land-step fake hosts and a Lander composed over those hosts."""
import tempfile
import weakref
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

import support.paths  # noqa: F401
from support.fake_beads import FakeBeads
from support.fakegit import FakeGit, ScriptedGit
from support.memstores import fake_stores
from support.narrow_hosts import (
    Begins,
    Checks,
    Fetches,
    Fixes,
    Keys,
    Locks,
    Moves,
    NoCases,
    Outcomes,
    OutcomesMoves,
    ShFn,
    Stages,
    Strays,
    Worker,
    deferred,
    stopped,
)
from taskloop.app.land.fix import FixOutside
from taskloop.app.land.gate import Gate, GateChecker, GateCheckout
from taskloop.app.land.host import LandState
from taskloop.app.land.lander import GateStep, Lander, LandParts
from taskloop.app.land.push import Landed, Pusher
from taskloop.app.land.rebase import Commit, LandRebase, Recheck
from taskloop.app.land.record import Sync
from taskloop.stores.bundle import Stores
from taskloop.stores.runlog import RunLog
from tlkernel import fence
from tlkernel.askspec import AskSpec
from tlkernel.bead import Bead
from tlkernel.beadsport import Beads, DoltPush
from tlkernel.checks import Check, CheckRun
from tlkernel.config import EngineConfig
from tlkernel.gitport import Git
from tlkernel.ids import BeadId, TreeSha
from tlkernel.plancheck import PlanData
from tlpipeline.api import Steps
from tltestkit.fake_clock import FakeClock


class FakeOutboundHost:
    """OutboundHost: bd answers `dolt_push` from `result`; commands and notes are recorded."""

    def __init__(self, dry: bool = False, result: tuple[int, str] = (0, "")) -> None:
        self.bead = BeadId("t-1")
        self.cfg = EngineConfig(land=["git", "push", "origin", "HEAD:main"])
        self.wt = "."
        self.tmp = tempfile.TemporaryDirectory()
        weakref.finalize(self, self.tmp.cleanup)
        self.run_dir = Path(self.tmp.name)
        self.dry = dry
        self.lines: list[str] = []  # what the log said
        self.clock = FakeClock()
        self.log = RunLog(fake_stores().run_log("run"), echo=self.lines.append, clock=self.clock.now)
        self.steps = Steps(self.log, self.clock.now)
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

    def sh(
        self,
        cmd: Sequence[str],
        timeout: float = 3600,
        check: bool = False,
        save: Path | None = None,
        env: Mapping[str, str] | None = None,
        pin: bool = False,
        what: str = "command",
        cwd: Path | None = None,
    ) -> tuple[int, str]:
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



class FakeCommitHost:
    """CommitHost."""

    def __init__(self, git: Git, sh: ShFn) -> None:
        self.bead = BeadId("t-1")
        self.git, self.sh = git, sh
        self.wt = "/wt"
        self.checkout = Stages()
        self.newfiles = Strays()

    def blocked_for(self, why: str, kind: str) -> Exception:
        return stopped(why, kind)



class FakeLandedHost:
    """LandedHost."""

    def __init__(self, git: Git, sh: ShFn, dry: bool = False, fetch: Fetches | None = None) -> None:
        self.landed_sha = ""
        self.land_state = LandState()
        self.bead = BeadId("t-1")
        self.cfg = EngineConfig(base="origin/main", land=[])
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
        self.land_state, self.task_branch = LandState(), ""
        self.cfg = cfg or EngineConfig(base="origin/main", land=["git", "push", "-q", "origin", "HEAD:main"])
        self.git, self.sh = git, sh
        self.wt = "/wt"
        self.tmp = tempfile.TemporaryDirectory()
        weakref.finalize(self, self.tmp.cleanup)
        self.run_dir = Path(self.tmp.name)
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
        self.log_path = Path("/runs/t-1-r1.jsonl")
        self.run_id = "t-1-r1"
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

    def run_items(self, items: Sequence[Check], everything: bool = False, learn: bool = False, show_clean: bool = False,
                  clean: bool = False) -> CheckRun:
        raise AssertionError("the repo has no gate")

    def gate_green(self, clean: bool = False) -> bool:
        return False



class GateTree:
    """A clean fake checkout: its worktree tree is HEAD's tree."""

    def __init__(self, git: Git, wt: str) -> None:
        self.git, self.wt = git, wt

    def tree_hash(self) -> TreeSha:
        return TreeSha(self.git.rev_parse(self.wt, "HEAD^{tree}"))



class FakeGateHost:
    """GateHost: `checker` answers the gate (none by default: the repo has no gate step)."""

    def __init__(self, git: Git, cfg: EngineConfig, log: RunLog, checker: GateChecker | None = None) -> None:
        self.land_state = LandState()
        self.cfg, self.log, self.git = cfg, log, git
        self.wt = "/wt"
        self.checkout: GateCheckout = GateTree(git, self.wt)
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
        self.bead = BeadId("t-1")
        self.store = FakeBeads()
        self.store.beads[self.bead] = Bead(id=self.bead, title="t", status="open")
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

    def blocked_for(self, why: str, kind: str, *, spec: AskSpec | None = None) -> Exception:
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
            gate=gate or Gate(FakeGateHost(git_fn, self.cfg, self.land.log, checker)),
            commit=Commit(FakeCommitHost(git_fn, sh_fn)),
            landed=Landed(self.landing),
            rebase=LandRebase(self.rebasing),
            recheck=Recheck(self.rechecking),
            push=self.pusher,
            fix=FixOutside(self.fixing),
            sync=Sync(self.syncing, self.bd),
            out=NoWip(),
        )
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

