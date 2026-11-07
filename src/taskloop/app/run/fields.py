"""What an engine remembers across the steps of one run: the plain fields, with their meaning. The Engine adds its parts to them."""
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, ClassVar

from taskloop.adapters import beadtools, ident, treehash
from taskloop.adapters.check_probe import PathProbe
from taskloop.adapters.threadflag import ThreadFlag
from taskloop.app.checks.checklog import CheckLog
from taskloop.app.checks.runner import Checker
from taskloop.app.land.state import LandState
from taskloop.app.look.state import LookState
from taskloop.app.pipeline.budget import Budget
from taskloop.app.pipeline.steps import Steps
from taskloop.app.plan.state import PlanState
from taskloop.app.review.state import ReviewLive
from taskloop.app.run.context import RunContext
from taskloop.app.run.state import Checkpoints, StateAttrs
from taskloop.app.workers.calls import Calls
from taskloop.app.write.state import WriteState
from taskloop.contracts import fence
from taskloop.contracts.argv import text_of
from taskloop.contracts.checkpoint import Checkpoint, RunState
from taskloop.contracts.checks import CheckRun
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.delegate import Permanence
from taskloop.contracts.delegateport import Refusal, Resolved
from taskloop.contracts.env import Env
from taskloop.contracts.gitport import Git
from taskloop.contracts.identity import Identity
from taskloop.contracts.ids import BeadId, TreeSha
from taskloop.contracts.kinds import Kind
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import Clock
from taskloop.contracts.procport import Spawner
from taskloop.contracts.review import Unfiled
from taskloop.contracts.run import Reexec
from taskloop.contracts.wire import Open
from taskloop.domain import outcome as oc
from taskloop.domain.lanes.pause_reasons import Producer
from taskloop.stores.bundle import Stores
from taskloop.stores.runlog import RunLog


class RunFields(StateAttrs):
    killed = ThreadFlag()  # the last sh() of the calling thread was stopped by the engine
    wall_hit = ThreadFlag()  # ...at its wall limit
    tree_memo: tuple[treehash.State, TreeSha] | None = None  # (git status, file stats) -> tree hash, of the last tree_hash()
    stop_pending = False  # run_bead sets it when a SIGTERM came during the claim
    live_n = 0  # the number of delegate calls with a live file so far
    live_now = ""  # the live file of the newest delegate call (the stuck tick reads when it was last written)
    _probe: PathProbe | None = None
    MARKERS_ARGV: ClassVar[list[str]] = ["python3", str(ident.PLUGIN_ROOT / "src" / "taskloop" / "adapters" / "markers.py")]
    MARKERS = text_of(MARKERS_ARGV)

    # Set by Engine.__init__ from the edge (env, spawner, who, git, clock, stores) and from the run's layout and context.
    env: Env
    spawner: Spawner
    who: Identity
    home: ConfigDir
    git: Git
    clock: Clock
    stores: Stores
    reexec: Reexec | None
    log_path: Path
    err_path: Path
    run_dir: Path
    live_dir: Path
    run_id: str
    task_dir: Path
    brief_file: Path
    evidence_dir: Path
    exec_fn: Callable[..., object] | None  # a test's exec, newer-install lookup and run-task argv
    newer_fn: Callable[..., object] | None
    argv: list[str] | None
    moved: bool
    ctx: RunContext
    log: RunLog
    steps: Steps
    budget: Budget
    calls: Calls
    checklog: CheckLog
    checker: Checker

    def __init__(self, bead: BeadId, wt: str, cfg: EngineConfig, dry_run: bool, verbose: bool, store: Any, route: Any,
                 fresh: bool, claim: fence.Claim | None, who: Identity) -> None:
        self.bead, self.cfg, self.dry, self.verbose = bead, cfg, dry_run, verbose
        self.claim = claim or fence.offline(bead)  # the run's right to act on its bead (app/track/fence.py); offline: nothing to check
        self.dead: Checkpoint | None = None  # a run died inside its close: its checkpoint, to finish that close (app/pipeline/ended.py)
        self.fenced = ""  # why this run was fenced out (its bead or slot taken again), once it was
        self.wt: str = wt
        self.store, self.router = store or beadtools.bd_store(who.actor), route
        self.stats: dict[str, int] = {"writes": 0, "rounds": 0, "reviews": 0, "replans": 0, "nodes": 0, "tests_added": 0,
                                      "tests_removed": 0, "tokens_in": 0, "tokens_cached": 0, "tokens_out": 0}
        self.session, self.fresh = who.session, fresh
        self.bead_parent = ""  # tl-bxk.10.23
        self.review = ReviewLive()  # the review stage's state: the unchecked and unverified lists, the verifier's answers, the links tried
        self.filed: list[str] = []
        self.unfiled: list[Unfiled] = []  # follow-ups bd refused (the ReviewState keeps both)
        self.amended = False  # a plan was amended or replanned: its first stage does not start at the task's base
        self.old_plan, self.amend_text, self.amend_why = None, "", ""  # set where a checkpoint's plan is kept to be amended
        self.answered: Any = None  # the owner ask this run starts from, once answered
        self.verify_answer = ""  # the owner's answer to a verify ask, when it asks for more than a yes
        self.stuck_why = ""
        self.resolved: Resolved | None = None  # the delegate install in use (delegate_link.resolve) and its contract.json
        self.refusal: Refusal | None = None
        self.route = ""
        self.contract: Open | None = None
        self.probe: Any = None  # the network probe (a test's); None: delegate's `route.py net`
        self.net_up_times: list[float] = []  # when a network stop came while the probe said up (three in five minutes pause the run)
        self.at_stage = 0  # the stage a call belongs to, for its key
        self.pause_role, self.pause_lane = "", ""  # the role and lane a paused run waits for: the loop wakes the bead when it is usable
        self.pause_reason = ""  # typed delegate reason; otherwise the close uses the engine outcome kind
        self.pause_producer: Producer = "engine"
        self.pause_permanence: Permanence | None = None
        self.budget_warned: set[float] = set()
        self.plan_state = PlanState()  # the plan stage's flags: the send-backs used, the cap raised
        self.land_fields()

    def land_fields(self) -> None:
        self.state, self.checkpoints = RunState(), Checkpoints(self)  # what survives a park (contracts/checkpoint.py), and its one writer
        self.look = LookState(lambda: self.state)  # the look stage's state (its checkpointed part views `self.state`)
        self.write = WriteState()  # the write stage's own state (write_rounds, last_summary, lane_notes, strays): not checkpointed
        self.plan_summary, self.bead_title = "", ""
        self.reflection: Mapping[str, object] | None = None
        self.left_dirty, self.branch, self.task_branch = False, "", ""
        self.land_state = LandState()  # the land's and the resume rebase's unsaved state
        self.artifact_repo = ""  # the repo's store key (adapters.check_files.repo_key), taken at the first registered render
        self.taste: list[Open] = []  # [{id, title}] taste items for the owner-look bead
        self.scope = ""  # the bead's acceptance text: an unchecked item outside it is a follow-up, not a gap (tl-bxk.13.5)
        self.sessions: list[Open] = []  # every AI call of this run: the trace a later reflection reads (traces.jsonl)
        self.why, self.asked = "", False  # what result() tells the loop
        self.kind = Kind.FAULT_ENGINE  # the run's outcome.Kind, after the close's escalation
        self.fp, self.storm = "", ""  # its fingerprint, a storm banner
        self.crash_fingerprint, self.crash_site = "", ""
        self.disp: oc.Disposition | None = None
        self.last_flag = ""  # same_family | degraded | ...: what the last worker call reported (worker_call sets it)
        self.retry_after = 0.0  # a pause for a lane: when delegate says it is back (epoch; 0 = unknown)
        self.landed_sha = ""  # set the moment the push goes through: whatever stops the run after it, the bead landed
        self.last_run: CheckRun | None = None  # the CheckRun of the last stage round: the engine's evidence for the verifier (tl-bxk.10.25)
        self.prev_ck, self.ck_run, self.resumed, self.run_logged = "", "", False, False
        self.killed = False
        self.wall_hit = False
