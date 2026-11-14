"""The fixed words a person reads about a hold (tl-8bh9.14.9 sections 7.1, 10 and 12): `tl step show`'s `Hold:` lines,
the guides of `Next: hold` and `Next: on_hold`, and the action each abandon refusal asks of the person. Text only; the
status read decides the words (`hold_status`), the hold operation acts (`hold`)."""

from datetime import UTC, datetime
from typing import Final

from taskloop.attempt_status import AttemptView
from taskloop.hold_cause import cause, next_step
from taskloop.hold_store import HoldRow
from taskloop.printable import one_line
from taskloop.round_guide import automatic_guide

OPEN: Final = ("The factory holds this task for a person but has not finished the hold. The next round records it, "
               "moves its labels, abandons the attempt and writes one comment on the task. The round's "
               "hold pending <step> <word> line names the reason it must wait. Once that cause is resolved, "
               "the next round returns the claim and finishes the hold.")
HOLD: Final = OPEN
LEAD: Final = "Held: the factory abandoned the attempt and waits for a person (the hold's comment on the task says why)."
ON_HOLD: Final = (LEAD + " To answer, edit the task's description or acceptance criteria (the agent reads those, not comments), then "
                  "add back the label the task was taken under (`bd label add <task> <label>`): the next round under that "
                  "label starts it again at plan on task/<task> as it is. To give up, `bd close <task>`.")
LABELS: Final = {"moved": "`{label}` removed, `held` added", "absent": "`held` added (`{label}` was not on the task)",
                 "not_ours": "no label changed (another actor holds the task)", "closed": "nothing written (the task is closed)",
                 "missing": "nothing written (no such task)", "superseded": "superseded (the task was taken again first)"}


def _when(at: float) -> str:
    return f"{datetime.fromtimestamp(at, UTC):%Y-%m-%d %H:%M:%S} UTC"


def _tracker(row: HoldRow) -> str:
    if row.labels is None:
        return "Hold tracker: labels not yet, not commented"
    written = LABELS[row.labels].format(label=one_line(row.label, 200))
    said = "commented" if row.commented_at is not None else "no comment" if row.labels in ("closed", "missing") else "not commented yet"
    return f"Hold tracker: {written}, {said}{'' if row.cleared_at is None else ', `held` cleared'}"


def hold_lines(view: AttemptView) -> list[str]:
    """`Hold:`, `Hold tracker:` and `Hold claim:` of a recorded hold; `Hold: due` of one the next round records."""
    row = view.hold
    if row is None:
        return [] if view.hold_due is None else [f"Hold: due {one_line(view.hold_due)} (the next round holds it)"]
    ended = view.release if view.checks is None else None
    claim = ("returned" if ended is not None and ended.claim == "unclaimed" else
             "not held (it was no longer the factory's)" if ended is not None and ended.claim == "not_held" else
             "kept: the abandon has not finished")
    return [f"Hold: {one_line(row.reason)} at {_when(row.held_at)} (cause {row.cause_id})", _tracker(row), f"Hold claim: {claim}"]


def pending_guide(word: str) -> str:
    """What keeps a round's pending hold open (`pending <step> <refusal>`) and the action, for that refusal only."""
    refusal = word.rsplit(" ", 1)[-1]
    return f"`{refusal}`: {automatic_guide(refusal)}"


def hold_guide(view: AttemptView) -> str:
    """The guide of `Next: hold` or `Next: on_hold`, with the stored label and the reason's own line once recorded."""
    if view.next == "hold":
        return HOLD
    row = view.hold
    if row is None:
        return ON_HOLD
    if row.labels in ("closed", "missing"):
        return "Held: the task is closed or gone in the tracker; nothing to answer."
    task, label = view.task_id, one_line(row.label, 200)
    found, ours = cause(row.reason), row.labels != "not_ours"
    edit = "edit the task's description or acceptance criteria (the agent reads those, not comments)"
    again = f"the next round under that label starts it again at plan on task/{task} as it is"
    back = (f"add back the label the task was taken under (`bd label add {task} {label}`): {again}" if ours
            else f"start it by hand (`tl step start {task}`): rounds do not take it again")
    what = "" if found is None else " " + found.what
    answer = f"{LEAD}{what} {next_step(found, back, edit)} To give up, `bd close {task}`."
    if row.reason == "branch_moved":
        answer += (f" First restore task/{task} to contain the verified commit, or rename it aside (`old/<id>-` and the first 12 "
                   "characters of its tip).")
    if row.reason == "claim_lost":
        answer += " Someone else changed this task's claim while the factory worked on it."
    return answer
