"""The fixed words a person reads about a hold (tl-8bh9.14.9 sections 7.1, 10 and 12): `tl step show`'s `Hold:` lines,
the guides of `Next: hold` and `Next: on_hold`, and the action each abandon refusal asks of the person. Text only; the
status read decides the words (`hold_status`), the hold operation acts (`hold`)."""

from datetime import UTC, datetime
from typing import Final

from taskloop.attempt_status import AttemptView
from taskloop.hold_store import HoldRow
from taskloop.hold_text import part

# Section 12: what keeps a hold open, by the abandon's refusal word, and what the person does. A transient word needs nothing.
KEPT_ACTIONS: Final = {
    "held:slot_dirty": "the slot has files left by the attempt: save what you need, then empty its changes (`git -C <slot> "
    "status`; restore tracked files, remove untracked ones). The factory never removes work.",
    "held:slot_branch": "the slot was switched to another branch: `tl step show` names where the factory left it; put it back.",
    "held:slot_redirected": "the slot's `.git` pointer changed: restore it, or remove the slot and `tl slot adopt` again.",
    "held:slot_unborn": "the slot's HEAD has no commit: restore it, or remove the slot and `tl slot adopt` again.",
    "unsettled:worker_alive": "the agent (or its group) outlived its entry: wait, or stop that process by its pid (never by "
    "name).",
    "unsettled:setup_running": "a setup command still runs: wait, or stop it by its pid.",
    "unsettled:check_running": "a check's command still runs: wait, or stop it by its pid.",
    "refused:landing": "a land of this task holds its slot: finish or withdraw it (`tl step land`).",
    "refused:landed": "a land of this task is, or may be, on origin's main: finish it (`tl step land`).",
}
OPEN: Final = ("The factory holds this task for a person but has not finished the hold: the next round (or `tl step next` "
               "now) records it, moves the labels, abandons the attempt and writes one comment on the task. The round's "
               "`hold pending <step>` line in rounds.log names what keeps it open; ")
TRANSIENT: Final = ("`held:slot_busy`, `unsettled:worker_unknown`, `unavailable:*` need nothing: the next round tries again.")
HOLD: Final = OPEN + "; ".join(f"`{word}`: {action}" for word, action in KEPT_ACTIONS.items()) + "; " + TRANSIENT + (
    " Once that is cleared, the next round returns the claim and finishes the hold.")
ON_HOLD: Final = ("Held: the factory abandoned the attempt and waits for a person (the hold's comment on the task says why). "
                  "To answer, edit the task's description or acceptance criteria (the agent reads those, not comments), then "
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
    written = LABELS[row.labels].format(label=part(row.label, 200))
    said = "commented" if row.commented_at is not None else "no comment" if row.labels in ("closed", "missing") else "not commented yet"
    return f"Hold tracker: {written}, {said}{'' if row.cleared_at is None else ', `held` cleared'}"


def hold_lines(view: AttemptView) -> list[str]:
    """`Hold:`, `Hold tracker:` and `Hold claim:` of a recorded hold; `Hold: due` of one the next round records."""
    row = view.hold
    if row is None:
        return [] if view.hold_due is None else [f"Hold: due {part(view.hold_due)} (the next round holds it)"]
    ended = view.release if view.checks is None else None
    claim = ("returned" if ended is not None and ended.claim == "unclaimed" else
             "not held (it was no longer the factory's)" if ended is not None and ended.claim == "not_held" else
             "kept: the abandon has not finished")
    return [f"Hold: {part(row.reason)} at {_when(row.held_at)} (cause {row.cause_id})", _tracker(row), f"Hold claim: {claim}"]


def hold_guide(view: AttemptView) -> str:
    """The guide of `Next: hold` or `Next: on_hold`, with the stored label and the reason's own line once recorded."""
    if view.next == "hold":
        return HOLD
    row = view.hold
    if row is None:
        return ON_HOLD
    if row.labels in ("closed", "missing"):
        return "Held: the task is closed or gone in the tracker; nothing to answer."
    task, label = view.task_id, part(row.label, 200)
    if row.labels == "not_ours":
        answer = (f"Held while another actor holds the task: rounds do not take it again. To answer, edit its description or "
                  f"acceptance criteria, then `tl step start {task}`.")
    else:
        answer = ON_HOLD.replace("<task>", task).replace("<label>", label)
    if row.reason == "branch_moved":
        answer += f" First restore task/{task} to contain the verified commit, or delete it locally and on origin."
    if row.reason == "claim_lost":
        answer += " Someone else changed this task's claim while the factory worked on it."
    return answer
