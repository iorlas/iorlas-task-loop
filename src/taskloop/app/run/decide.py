"""resume_decision: what a run does with the checkpoint it finds, as a pure function of the checkpoint and the world.

`resume`: go on at the saved stage (same writer thread, no planner). `land`: every stage was accepted, land. `amend`: the
bead (or the branch) changed, plan the rest and keep the accepted stages. `replan`: a land failed after the stages; plan the
fix. `fresh`: nothing usable, plan from the base. The caller gathers the world (git, the bead, the owner's answer) and applies
the decision; nothing here reads or writes anything.
"""

from dataclasses import dataclass
from typing import Literal

from taskloop.contracts.checkpoint import Checkpoint

OUTSIDE = "the branch changed outside the engine"
CONFIRMED = "the owner confirmed the verify ask"
Kind = Literal["resume", "amend", "replan", "fresh", "land"]


@dataclass(frozen=True)
class World:
    """What the decision reads besides the checkpoint."""

    fresh: bool = False  # --fresh: start again, the checkpoint is dropped
    branch: str = ""  # HEAD's branch now
    head: str = ""
    parent: str = ""  # HEAD~1, when asked for
    left_dirty: bool = False  # reset() made a wip commit on top of the branch's head
    brief_hash: str = ""
    answered: bool = False  # an owner's answer starts this run
    answer_given: bool = False  # ...and it carries an answer (a filed answer changes what the plan reads, whatever the bead)
    answer_external_fact: bool = False  # the answer is to a verify ask
    answer_confirms: bool = False
    answer_words: str = ""
    answer_id: str = ""
    answer_action: str = ""
    brief_diff: str | None = None  # what the plan reads changed, as text; "" = nothing; None = no snapshot to compare
    brief_diff_quiet: str | None = None  # the same, ignoring comments
    missing_stage: int | None = None  # an accepted stage whose evidence file is gone: it runs again


@dataclass(frozen=True)
class Decision:
    kind: Kind
    why: str = ""
    drop: bool = False  # the checkpoint is not kept
    stage: int = 0
    continues: bool = False  # resume: the saved round counters go on
    amend_why: str = ""
    amend_text: str = ""
    verify_answer: str = ""
    redo_from: int | None = None


def stage_count(ck: Checkpoint) -> int:
    return len((ck.state.plan_data or {}).get("stages") or [])


def usable(ck: Checkpoint, w: World) -> bool:
    return bool(ck.state.plan_data) and ck.branch == w.branch


def ours(ck: Checkpoint, w: World) -> bool:
    """HEAD is where the engine left it (or one wip commit above it): not a commit or an edit from outside."""
    return w.head == ck.head or (w.left_dirty and not ck.closed and w.parent == ck.head)


def bead_changed(ck: Checkpoint, w: World) -> Decision | None:
    """The bead's text or the owner's answer moved since the checkpoint: an amend, or None when nothing the plan reads changed."""
    if ck.state.brief_hash == w.brief_hash and not w.answer_given:
        return None
    diff = w.brief_diff
    if diff and not w.answered and not w.brief_diff_quiet:
        diff = ""  # a comment alone is context for the next writer, not an amend
    if w.answer_given and not w.answer_words and ck.state.brief_hash == w.brief_hash:
        diff = ""  # "Run again" changes nothing the plan reads
    if diff == "":
        return None
    who = f"the owner answered ask {w.answer_id}" if w.answered else "an edit with no ask"
    text = diff or "The bead changed since the old plan (the checkpoint holds no copy of the old text): read the task above."
    return Decision("amend", "bead changed", amend_why="bead changed: " + who, amend_text=text)


def after_stages(ck: Checkpoint, w: World) -> Decision | None:
    """A land that failed after every stage was accepted, or a verify ask answered: the cases that ask for a plan or a land."""
    if ck.step == "gate-red":
        return Decision("replan", "the gate was red at land", amend_why="gate red at land")
    if ck.step == "land-verify-red":
        return Decision("replan", "retry validation failed", amend_why="retry validation fix failed at land")
    changed = ck.state.brief_hash != w.brief_hash or w.answer_given
    if changed and ck.step == "land" and w.answered and w.answer_external_fact:
        if w.answer_given and w.answer_confirms:
            return Decision("land", CONFIRMED, stage=stage_count(ck))
        return Decision(
            "amend",
            "answered with more than a yes",
            amend_why="",
            verify_answer=w.answer_words or "(no comment: the owner edited the bead)",
        )
    return None


def resume_decision(ck: Checkpoint | None, w: World) -> Decision:
    if ck is None or w.fresh or not usable(ck, w):
        return Decision("fresh", "no checkpoint" if ck is None else "--fresh" if w.fresh else "not this branch's", drop=ck is not None)
    if not ours(ck, w):
        return Decision("amend", OUTSIDE, amend_why="branch changed outside the engine")
    early = after_stages(ck, w) or bead_changed(ck, w)
    if early is not None:
        return early
    n = stage_count(ck)
    if w.missing_stage is not None:
        return Decision("resume", "a promised file is missing", stage=w.missing_stage, redo_from=w.missing_stage)
    if ck.step == "land" or ck.stage >= n:
        return Decision("land", "every stage was accepted", stage=n)
    return Decision("resume", "mid-stage", stage=ck.stage, continues=True)
