"""What an engine remembers across the steps of one run: the plain fields, with their meaning. The Engine adds its parts to them."""
from pathlib import Path
from typing import Any

from taskloop.adapters import beadtools, ident
from taskloop.app.run.state import Checkpoints, StateAttrs
from taskloop.contracts import fence
from taskloop.contracts.checkpoint import Checkpoint, RunState
from taskloop.contracts.ids import BeadId
from taskloop.contracts.kinds import Kind


class RunFields(StateAttrs):
    def __init__(self, bead: BeadId, wt: str, cfg: Any, dry_run: bool, verbose: bool, store: Any, route: Any, git: Any,
                 fresh: bool, claim: fence.Claim | None = None) -> None:
        self.bead, self.cfg, self.dry, self.verbose = bead, cfg, dry_run, verbose
        self.claim = claim or fence.offline(bead)  # the run's right to act on its bead (app/track/fence.py); offline: nothing to check
        self.dead: Checkpoint | None = None  # a run died inside its close: its checkpoint, to finish that close (app/run/ended.py)
        self.fenced = ""  # why this run was fenced out (its bead or slot taken again), once it was
        self.wt: Any = wt
        self.store, self.router, self.repo = store or beadtools.bd_store(), route, git
        self.stats: dict[str, int] = {"writes": 0, "rounds": 0, "reviews": 0, "replans": 0, "nodes": 0, "tests_added": 0,
                                      "tests_removed": 0, "tokens_in": 0, "tokens_cached": 0, "tokens_out": 0}
        self.session, self.fresh = ident.session_id(), fresh
        self.leftovers: list[Any] = []
        self.bead_parent = ""  # tl-bxk.10.23
        self.look_filed = False
        self.filed: list[Any] = []
        self.unfiled: list[Any] = []  # follow-ups bd refused (the ReviewState keeps both)
        self.look_retried: set[Any] = set()
        self.shots_skipped: set[Any] = set()
        self.unverified: list[Any] = []  # tl-bxk.10.28: items that land for the owner
        self.link_ok: set[str] = set()  # tl-bxk.7: links opened from this host
        self.link_bad: dict[str, Any] = {}
        self.link_fn: Any = None  # a test's check
        self.link_tries: dict[str, int] = {}
        self.amended = False  # a plan was amended or replanned: its first stage does not start at the task's base
        self.strays: list[Any] = []  # unaccepted untracked files moved to evidence/strays before the land gate (tl-bxk.10.24)
        self.cap_granted = False
        self.old_plan, self.amend_text, self.amend_why = None, "", ""  # set where a checkpoint's plan is kept to be amended
        self.unchecked: list[Any] = []  # what the last review of this run says nobody checked (each review re-judges it)
        self.answered: Any = None  # the owner ask this run starts from, once answered
        self.verify_answer = ""  # the owner's answer to a verify ask, when it asks for more than a yes
        self.stuck_why = ""
        self.resolved: Any = None  # the delegate install in use (delegate_link.resolve) and its contract.json
        self.refusal: Any = None
        self.route = ""
        self.contract: Any = None
        self.probe: Any = None  # the network probe (a test's); None: delegate's `route.py net`
        self.net_up_times: list[float] = []  # when a network stop came while the probe said up (three in five minutes pause the run)
        self.at_stage = 0  # the stage a call belongs to, for its key
        self.pause_role, self.pause_lane = "", ""  # the role and lane a paused run waits for: the loop wakes the bead when it is usable
        self.budget_warned: set[float] = set()
        self.plan_assumed = False  # tl-ntp: the planner was sent back once to plan on assumptions
        self.plan_decided = False  # the planner was sent back once with the requirement that answers its question
        self.land_fields()

    def land_fields(self) -> None:
        self.verified: list[Any] = []  # the verifier's answer per unchecked item at land: in the trace and on the bead
        self.write_rounds: list[Any] = []  # per write round: resumed, input tokens, turns, prompt chars, context k, why fresh
        self.last_summary = ""  # the last write's summary: a fresh writer is told it
        self.state, self.checkpoints = RunState(), Checkpoints(self)  # what survives a park (contracts/checkpoint.py), and its one writer
        self.plan_summary, self.bead_title = "", ""
        self.reflection: Any = None
        self.left_dirty, self.branch, self.task_branch = False, "", ""
        self.gate_log: Path | None = None
        self.salvage_tail, self.rebase_orig = "", ""
        self.rebase_pre: list[Any] = []
        self.shot_cache: dict[str, Any] | None = None
        self.salvaged = False  # a resume conflict was fixed in place, not by starting again (tl-7y6.2.19)
        self.lane_notes: list[Any] = []  # steps that ran on the writer's own family, with delegate's warning
        self.taste: list[Any] = []  # [{id, title}] taste items for the owner-look bead
        self.scope = ""  # the bead's acceptance text: an unchecked item outside it is a follow-up, not a gap (tl-bxk.13.5)
        self.sessions: list[Any] = []  # every AI call of this run: the trace a later reflection reads (traces.jsonl)
        self.why, self.asked = "", False  # what result() tells the loop
        self.kind = Kind.FAULT_ENGINE  # the run's outcome.Kind, after the close's escalation
        self.fp, self.storm = "", ""  # its fingerprint, a storm banner
        self.disp: Any = None
        self.retry_after = 0.0  # a pause for a lane: when delegate says it is back (epoch; 0 = unknown)
        self.landed_sha = ""  # set the moment the push goes through: whatever stops the run after it, the bead landed
        self.last_run: Any = None  # the CheckRun of the last stage round: the engine's evidence for the verifier (tl-bxk.10.25)
        self.prev_ck, self.ck_run, self.resumed, self.run_logged = "", "", False, False
        self.killed = False  # the last sh() was stopped by the engine
        self.wall_hit = False  # ...at its wall limit
