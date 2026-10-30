"""Checkpoint: where a run stopped, so the next run on the same bead resumes there (checkpoints/<bead>.json, v3).

Two parts. `RunState` is everything the run carries across a park, one typed value; adding a field is one edit here (the
engine reads and writes it through `engine.state`, `dump()` is the payload). `Checkpoint` is that state plus where the run
stood: branch, head, step and the stage counters. The big nested parts the planner and the writer own (`plan`, `snap`,
`handoff`) stay open dicts until their own records land. Review and verify state is ONE field, `review`, a `ReviewState`
this module never opens. An old checkpoint (another `v`) reads as absent: nothing is migrated.
"""

from typing import Any, ClassVar, final

import msgspec

from taskloop.contracts import wire
from taskloop.contracts.plancheck import PlanData
from taskloop.contracts.review import ReviewState
from taskloop.contracts.run import Round
from taskloop.contracts.wire import Open, Rec


@final
class Handoff(Rec, frozen=False):
    """What the rounds did and what a review already noted (nothing yet): the next writer is told of it."""

    rounds: list[Round] = msgspec.field(default_factory=list)
    seen_lows: list[str] = msgspec.field(default_factory=list)


@final
class WriterSession(Rec, frozen=False):
    """The writer's thread: its delegate session, how much context it holds (k tokens, None = unknown), the brief and plan hashes it has
    seen, and whether the last stage's note reached it."""

    delegate: str | None = None
    ctx: float | None = None
    seen: list[str] = msgspec.field(default_factory=list)
    last_stage: bool = False


@final
class BriefSnap(Rec):
    """What a later amend diffs against: the bead's text fields, issue type, dependencies (id:type) and the people's comments, as the
    planner saw them."""

    fields: dict[str, str]
    issue_type: str
    deps: list[str]
    comments: list[str]


@final
class Defect(Rec):
    """A finding of the look judge (or a render error) on the pictures of a stage."""

    item: str
    why: str
    where: str = ""


@final
class PlanStep(Rec):
    """One entry of the plan log: a plan, an amend or a rebase reset, and whether it counts toward the plan cap."""

    mode: str
    why: str
    counted: bool = True


@final
class RunState(Rec, frozen=False):
    """What a run carries across a park. The only place these attributes are declared."""

    plan_data: PlanData | None = None
    brief_hash: str = ""
    snap: BriefSnap | None = None
    planner_ref: str = ""
    planned: int = 0
    replans: int = 0
    fixes: int = 0
    extra: int = 0
    rebase_resets: int = 0
    plan_log: list[PlanStep] = msgspec.field(default_factory=list)
    done: list[str] = msgspec.field(default_factory=list)
    accepted: list[int] = msgspec.field(default_factory=list)
    accepted_new: list[str] = msgspec.field(default_factory=list)
    denials: list[str] = msgspec.field(default_factory=list)
    writer: WriterSession = msgspec.field(default_factory=WriterSession)
    writer_family: str | None = None
    writer_fallback: bool = False
    fallback_lane: str = ""
    writer_said: str = ""
    look_paths: list[str] = msgspec.field(default_factory=list)
    look_notes: list[str] = msgspec.field(default_factory=list)
    look_unjudged: dict[str, str] = msgspec.field(default_factory=dict)
    look_done: int = 0
    look_prev: list[Defect] = msgspec.field(default_factory=list)
    rendered_names: list[str] = msgspec.field(default_factory=list)  # sorted: the pictures rendered so far
    last_reqs: list[Open] = msgspec.field(default_factory=list)
    render_stale: bool = False
    handoff: Handoff = msgspec.field(default_factory=Handoff)
    stage_tree: str = ""
    pending_land_validation: str = ""
    review: ReviewState = msgspec.field(default_factory=ReviewState)

    def start_again(self) -> RunState:
        """The state of a task that starts again on the base: nothing of the old attempt, but what belongs to the bead (the follow-ups
        filed or refused, the owner's extra amends, the rebase resets, the brief as it is now, the planner thread)."""
        keep = ("extra", "rebase_resets", "brief_hash", "snap", "planner_ref", "pending_land_validation")
        return RunState(**{k: getattr(self, k) for k in keep})

    def dump(self) -> dict[str, Any]:
        """The payload that survives a park: every field, nothing else."""
        return wire.dump(self)

    @classmethod
    def from_dump(cls, data: dict[str, Any]) -> RunState:
        return wire.load(cls, data)


@final
class EndRec(Rec):
    """The final outcome of a run (after POLICY and any escalation), kept before the close's first effect, with what the effects read of
    the decision: a restart rebuilds the same plan from it. `spec` is the ask (domain/asks/spec.AskSpec) as JSON text."""

    run: str  # the run that closed (its id is in every key; the checkpoint's own `run` is the run that saved it)
    kind: str
    fingerprint: str
    detail: str
    sha: str = ""
    spec: str = ""  # the ask as JSON text ("" for no ask)
    fp: str = ""  # the fault's fingerprint before any escalation (the trace and the report carry it)
    comment: bool = True  # False: the same fault was said within the hour
    escalated: bool = False
    leftovers: list[dict[str, str]] = msgspec.field(default_factory=list)  # the follow-ups FileNotes files (they live in memory only)


@final
class Notes(Rec):
    """What the FileNotes effect did: the follow-ups filed and the ones bd refused (Reflect says these counts)."""

    filed: int
    unfiled: int


@final
class Checkpoint(Rec):
    V: ClassVar[int] = 3
    bead: str
    run: str
    t: float
    branch: str = ""
    head: str = ""
    closed: bool = False
    step: str = ""
    stage: int = 0
    rounds: int = 0
    n: int = 0
    feedback: str = ""
    gate_tail: str = ""
    applied: list[str] = msgspec.field(default_factory=list)  # keys of the close effects already applied (domain/effects.key_of)
    ended: EndRec | None = None  # the close's outcome, stored before its first effect: a restart finishes the close from it
    notes: Notes | None = None  # the FileNotes result
    state: RunState = msgspec.field(default_factory=RunState)
