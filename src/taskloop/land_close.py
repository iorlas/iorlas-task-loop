"""The land's close (tl-8bh9.14.8 section 8): after the delivery, the task is closed in the person's local tracker and the
close recorded once on the delivered candidate (`land_store.record_close`, fenced delivered and not yet closed).

The order is the delivery contract's: push (or the no-change disposition) first, then `bd close` through the tracker port
as `taskloop` (`tracker_client`: one read, closed is `already_closed`; else `Bd.close(..., if_assignee="taskloop")`). The
land neither claims nor unclaims: the close ends the claim. Each external effect is observed before it is repeated: a
crash between the push and the close, or between the close and its record, leaves the candidate delivered and not
closed, and the rerun goes straight here (no fetch, squash, check or push); the tracker read then finds the task closed
and records `already_closed`. A refused close leaves the task open and claimed: `unavailable tracker` (rerun) or `refused
claim_lost` (close it by hand with `bd close`; a rerun records it). Tracker sync stays the person's (O4): the factory never
runs `bd dolt push` or any remote tracker operation; every land answer says so (`NOT_SYNCED`).
"""

from collections.abc import Callable
from typing import Final

from taskloop.attempt_reads import StoreRefused, StoreUnavailable
from taskloop.land_store import Close, LandRow, LandStore
from taskloop.operations import Failed
from taskloop.printable import one_line
from taskloop.tracker_client import CloseAnswer

NOT_SYNCED: Final = "Tracker: closed locally, not synced (bd dolt push shares it)"


def reason(row: LandRow) -> str:
    """The close reason: the landed S and the checked X, or the no-change disposition's O."""
    if row.delivery == "no_change":
        return f"Already on main at {row.origin}"
    return f"Landed {row.commit} on main (task/{row.task_id} at {row.checked})"


def _on_main(row: LandRow) -> str:
    if row.delivery == "no_change":
        return f"origin's main at {row.origin} already holds {row.task_id}'s changes"
    return f"S ({row.commit}) is on origin's main"


def _recorded(lands: LandStore, now: float, row: LandRow, close: Close) -> LandRow | Failed:
    """The close recorded once; found recorded by a concurrent land is the same answer."""
    try:
        lands.record_close(row.key, close, now)
    except StoreRefused:
        again = lands.row(row.key)
        if again is not None and again.close is not None:
            return again
        return Failed("unavailable", "changed", f"{_on_main(row)} and the task is closed; the candidate changed meanwhile: rerun "
                      "to record it.")
    except StoreUnavailable:
        return Failed("unavailable", "store", f"{_on_main(row)} and the task is closed; nothing was recorded: rerun to record it.")
    return lands.row(row.key) or row


def _by_hand(task: str, holder: str | None) -> str:
    """How the person closes the task by hand, from the assignee the close read (bd refuses a close by an actor other
    than the assignee unless forced: measured)."""
    if holder is None:
        return f"another actor took it meanwhile: inspect it (`bd show {task}`), then close it by hand (`bd close {task} --force` " \
            "while another actor holds it)"
    if not holder:
        return f"it is unassigned (its claim lapsed): close it by hand with `bd close {task}`"
    return f"it is assigned to {one_line(holder, 80)}: close it by hand with `bd close {task} --force` (bd refuses a close by an " \
        "actor other than the assignee)"


def _refused(row: LandRow, answer: CloseAnswer) -> Failed:
    """A close that did not happen: the task stays open (and claimed, unless another actor holds it). Each refusal names
    what the person does; only `unavailable` is a plain rerun."""
    task, on_main, rerun = row.task_id, _on_main(row), "a rerun of `tl step land` then records it `already_closed`"
    if answer.word == "claim_lost":
        return Failed("refused", "claim_lost", f"{on_main}, but {_by_hand(task, answer.assignee)}; {rerun}.")
    if answer.word == "blocked":
        return Failed("refused", "blocked", f"{on_main}, but bd refuses to close {task} ({one_line(answer.detail, 300)}): close or "
                      f"unblock what it names, or close it by hand with `bd close {task} --force`; a rerun of `tl step land` then "
                      "closes or records it.")
    if answer.word == "missing":
        return Failed("refused", "task", f"{on_main}, but the tracker has no task {task}: inspect the tracker; a rerun of `tl step "
                      "land` closes it once it is found.")
    return Failed("unavailable", "tracker", f"{on_main}; the tracker could not close {task} ({answer.detail or 'no answer'}): "
                  "rerun `tl step land` to close it (nothing else is repeated).")


def closed(lands: LandStore, close: Callable[[str, str, str], CloseAnswer], now: Callable[[], float], row: LandRow) -> LandRow | Failed:
    """The delivered candidate's task closed in the tracker and the close recorded (a close recorded by a concurrent land
    is that answer)."""
    answer = close(row.tracker_root, row.task_id, reason(row))
    match answer.word:
        case "closed" | "already_closed" as word:
            return _recorded(lands, now(), row, word)
        case _:
            return _refused(row, answer)
