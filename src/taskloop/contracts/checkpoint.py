"""Checkpoint: where a run stopped, so the next run on the same bead resumes there (checkpoints/<bead>.json, v2).

The shape is the fields the engine saves today (33 real files read). The big nested parts the planner and the writer own
(`plan`, `snap`, `handoff`, `look_unjudged`) stay open dicts until their own records land; the small repeated parts are typed.
"""
from dataclasses import field
from typing import Any, ClassVar

from taskloop.contracts.codec import record


@record
class Unchecked:
    what: str
    kind: str = ""
    source: str = ""
    why: str = ""
    proof_round: bool = False


@record
class Unverified:
    what: str
    kind: str = ""
    why: str = ""
    source: str = ""


@record
class PlanLogLine:
    mode: str
    counted: bool = True
    why: str = ""


@record
class LookVerdict:
    item: str
    verdict: str = ""
    where: str = ""
    why: str = ""


@record
class RenderArg:
    name: str
    value: str


@record
class RenderReq:
    method: str
    names: list[str] = field(default_factory=list)
    args: list[RenderArg] = field(default_factory=list)


@record
class Unfiled:
    """A follow-up bd refused: kept here so none is lost or counted as filed."""

    title: str
    why: str


@record
class Checkpoint:
    V: ClassVar[int] = 2
    bead: str
    run: str
    t: float
    branch: str = ""
    step: str = ""
    stage: int = 0
    rounds: int = 0
    n: int = 0
    head: str = ""
    closed: bool = False
    brief_hash: str = ""
    plan: dict[str, Any] | None = None
    plan_log: list[PlanLogLine] = field(default_factory=list)
    planner_ref: str = ""
    planned: int = 0
    replans: int = 0
    fixes: int = 0
    extra: int = 0
    rebase_resets: int = 0
    snap: dict[str, Any] | None = None
    done: list[str] = field(default_factory=list)
    accepted: list[int] = field(default_factory=list)
    accepted_new: list[str] = field(default_factory=list)
    denials: list[str] = field(default_factory=list)
    writer: str = ""
    writer_family: str = ""
    writer_fallback: bool = False
    fallback_lane: str = ""
    writer_ctx: int | None = None
    writer_seen: list[str] | None = None
    writer_said: str = ""
    unchecked: list[Unchecked] = field(default_factory=list)
    unverified: list[Unverified] = field(default_factory=list)
    filed: list[str] = field(default_factory=list)
    unfiled: list[Unfiled] = field(default_factory=list)
    look_paths: list[str] = field(default_factory=list)
    look_notes: list[str] = field(default_factory=list)
    look_unjudged: dict[str, Any] = field(default_factory=dict)
    look_done: int = 0
    look_prev: list[LookVerdict] = field(default_factory=list)
    rendered: list[str] = field(default_factory=list)
    last_reqs: list[RenderReq] = field(default_factory=list)
    render_stale: bool = False
    handoff: dict[str, Any] | None = None
    stage_tree: str = ""
    feedback: str = ""
    pending_land_validation: str = ""
