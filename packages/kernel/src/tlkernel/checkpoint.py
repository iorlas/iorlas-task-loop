"""Checkpoint: where a run stopped, so the next run on the same bead resumes there (checkpoints/<bead>.json, v4).

Two parts. `RunState` is everything the run carries across a park, one typed value; adding a field is one edit here (the
engine reads and writes it through `engine.state`, `dump()` is the payload). `Checkpoint` is that state plus where the run
stood: branch, head, step and the stage counters. The big nested parts the planner and the writer own (`plan`, `snap`,
`handoff`) stay open dicts until their own records land. Review and verify state is ONE field, `review`, a `ReviewState`
this module never opens. A checkpoint of another `v` is refused (Refused): nothing is migrated.
"""

from typing import Any, ClassVar, Literal, final

import msgspec

from tlkernel import wire
from tlkernel.answers import WriteAnswerLook
from tlkernel.delegate import Permanence
from tlkernel.plancheck import PlanData
from tlkernel.review import ReviewState
from tlkernel.run import Round
from tlkernel.wire import Open, Rec


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
# Tolerant of unknown keys while checkpoints written before the retired writer_said, look_paths and look_prev (tl-jvpm.26) are on disk.
class RunState(Rec, frozen=False, forbid_unknown_fields=False):
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
    look_notes: list[str] = msgspec.field(default_factory=list)
    look_unjudged: dict[str, str] = msgspec.field(default_factory=dict)
    look_done: int = 0
    rendered_names: list[str] = msgspec.field(default_factory=list)  # sorted: the pictures rendered so far
    last_reqs: list[Open] = msgspec.field(default_factory=list)
    render_stale: bool = False
    handoff: Handoff = msgspec.field(default_factory=Handoff)
    stage_tree: str = ""
    pending_land_validation: str = ""
    leftovers: list[dict[str, str]] = msgspec.field(default_factory=list)
    followup_ids: dict[str, str] = msgspec.field(default_factory=dict)
    review: ReviewState = msgspec.field(default_factory=ReviewState)

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
    leftovers: list[dict[str, str]] = msgspec.field(default_factory=list)  # the close's snapshot; RunState owns the queue


Producer = Literal["delegate", "engine"]


@final
class PauseFacts(Rec):
    """The pause facts the close needs after the engine that knew them died."""

    reason: str = ""
    producer: Producer = "engine"
    permanence: Permanence | None = None
    retry_after: float = 0.0
    crash_fingerprint: str = ""
    crash_site: str = ""


@final
class CloseIntent(Rec):
    """The outcome and facts kept before the close's first effect."""

    outcome: EndRec
    pause: PauseFacts
    stats: str = ""
    plan_summary: str = ""
    asked: bool = False


@final
class Notes(Rec):
    """What the FileNotes effect did: the follow-ups filed and the ones bd refused (Reflect says these counts)."""

    filed: int
    unfiled: int


@final
class StageProgress(Rec):
    """A separated write/check/review round, carried by the existing checkpoint."""

    write: WriteAnswerLook | None = None
    red: int = 0
    red_now: list[str] = msgspec.field(default_factory=list)
    failed: list[str] | None = None
    acceptance_only: bool = False
    acceptance_first: bool = False
    shots_fixed: bool = False
    show_fixed: bool = False


@final
class Checkpoint(Rec):
    V: ClassVar[int] = 4
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
    ended: CloseIntent | None = None  # the close's outcome, stored before its first effect: a restart finishes the close from it
    notes: Notes | None = None  # the FileNotes result
    state: RunState = msgspec.field(default_factory=RunState)
    progress: StageProgress | None = None
