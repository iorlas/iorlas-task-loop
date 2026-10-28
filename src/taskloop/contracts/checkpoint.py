"""Checkpoint: where a run stopped, so the next run on the same bead resumes there (checkpoints/<bead>.json, v3).

Two parts. `RunState` is everything the run carries across a park, one typed value; adding a field is one edit here (the
engine reads and writes it through `engine.state`, `dump()` is the payload). `Checkpoint` is that state plus where the run
stood: branch, head, step and the stage counters. The big nested parts the planner and the writer own (`plan`, `snap`,
`handoff`) stay open dicts until their own records land. Review and verify state is ONE field, `review`, a `ReviewState`
this module never opens. An old checkpoint (another `v`) reads as absent: nothing is migrated.
"""

from dataclasses import dataclass, field
from typing import Any, ClassVar

from taskloop.contracts import codec
from taskloop.contracts.codec import record
from taskloop.contracts.review import ReviewState, Unfiled


def fresh_handoff() -> dict[str, Any]:
    """What the rounds did and what a review already noted: nothing yet."""
    rounds: list[dict[str, Any]] = []
    lows: list[str] = []
    return {"rounds": rounds, "seen_lows": lows}


@dataclass(kw_only=True)
class RunState:
    """What a run carries across a park. The only place these attributes are declared."""

    plan_data: dict[str, Any] | None = None
    brief_hash: str = ""
    snap: dict[str, Any] = field(default_factory=dict)
    planner_ref: str = ""
    planned: int = 0
    replans: int = 0
    fixes: int = 0
    extra: int = 0
    rebase_resets: int = 0
    plan_log: list[dict[str, Any]] = field(default_factory=list)
    done: list[str] = field(default_factory=list)
    accepted: list[int] = field(default_factory=list)
    accepted_new: list[str] = field(default_factory=list)
    denials: list[str] = field(default_factory=list)
    writer: dict[str, Any] = field(default_factory=dict)
    writer_family: str | None = None
    writer_fallback: bool = False
    fallback_lane: str = ""
    writer_said: str = ""
    filed: list[str] = field(default_factory=list)
    unfiled: list[Unfiled] = field(default_factory=list)
    look_paths: list[str] = field(default_factory=list)
    look_notes: list[str] = field(default_factory=list)
    look_unjudged: dict[str, Any] = field(default_factory=dict)
    look_done: int = 0
    look_prev: list[Any] = field(default_factory=list)
    rendered_names: set[str] = field(default_factory=set)
    last_reqs: list[Any] = field(default_factory=list)
    render_stale: bool = False
    handoff: dict[str, Any] = field(default_factory=fresh_handoff)
    stage_tree: str = ""
    pending_land_validation: str = ""
    review: ReviewState = field(default_factory=ReviewState)

    def dump(self) -> dict[str, Any]:
        """The payload that survives a park: every field, nothing else."""
        return codec.to_json(self)

    @classmethod
    def from_dump(cls, data: dict[str, Any]) -> "RunState":
        return codec.from_json(cls, data)


@record
class Checkpoint:
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
    state: RunState = field(default_factory=RunState)
