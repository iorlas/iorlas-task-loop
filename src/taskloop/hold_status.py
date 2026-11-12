"""A hold in a task's status (tl-8bh9.14.9 sections 3, 7.2 and 10): which conditions hold a round-taken task (`cause`),
the `Next` word a hold gives (`hold_next`), when it is finished (`finished`), and whether a round under a label takes an
`on_hold` task again (`reingests`). Pure: values in, values out; `attempt_status` places the words, `hold` acts on them.

The hold row decides the word after every other rule, except `unknown`: `hold` while the hold is not finished (the round
finishes it, or a slot or process keeps the claim), `on_hold` once it is (waiting for the person). A labelled view with a
cause and no row yet is `hold` too (due): the next round records it."""

from typing import Final, Literal, Protocol

from taskloop.attempt_reads import ReleaseRow
from taskloop.attempt_result import succeeded
from taskloop.attempt_types import AttemptResult
from taskloop.hold_store import HoldRow

type HoldNext = Literal["hold", "on_hold"]
# The `Next` words a hold never comes from (section 3): transient or progressing, the person's land, `stuck:hung` (D7).
STUCK_NOT_HELD: Final = "stuck:hung"
MAIN_MOVED_RUNS: Final = 3  # checks attempts that may fail so in a row before the task is held (a pusher faster than the checks)
MAIN_MOVED: Final = "failed:main_moved"  # a checks attempt's reason: `main` moved while it ran (a land, a hand push)
FAILED: Final = frozenset({"done", "release"})  # a collected result, not succeeded: `failed:<reason>`
# The label words after which no comment is written (nothing was written to the task, or it was taken again first).
UNCOMMENTED: Final = frozenset({"closed", "missing", "superseded"})
RETURNED: Final = frozenset({"unclaimed", "not_held"})  # an abandon's claim once it is no longer the factory's to return
ANSWERED: Final = frozenset({"moved", "absent"})  # the hold removed (or found absent) the label: adding it back answers


class Viewed(Protocol):
    """What the cause rule reads of a status view (`attempt_status.AttemptView`)."""

    @property
    def next(self) -> str: ...
    @property
    def result(self) -> AttemptResult: ...
    @property
    def leftovers(self) -> tuple[str, ...]: ...
    @property
    def release(self) -> ReleaseRow | None: ...
    @property
    def label(self) -> str | None: ...
    @property
    def number(self) -> int: ...


def cause(view: Viewed) -> str | None:
    """Section 3's rule over the view's own `Next` word: the reason word a round-taken task is held for, or None. Never
    for a task started by hand (`label` None) nor for one whose abandon was started (by a person or a hold). A failed
    result is `failed:<result reason>` (a checks attempt's reason already reads `failed:<reason>`); `repeats_exhausted`
    names the repeat reason; every `stuck:*` word but `stuck:hung` is its own reason. The advance's and the
    publication's refusals (`claim_lost`, `branch_moved`) are the round's to pass: no status shows them."""
    if view.label is None or (view.release is not None and view.release.abandoned):
        return None
    word = view.next
    if view.result.reason == MAIN_MOVED and view.number < MAIN_MOVED_RUNS:  # not the task's fault: the round runs them again
        return None
    if word in FAILED and view.result.status == "collected" and not succeeded(view.result):
        reason = view.result.reason
        return reason if reason.startswith("failed:") else f"failed:{reason}"
    if word == "repeats_exhausted":
        return f"repeats_exhausted:{view.leftovers[0]}" if view.leftovers else word
    return word if word.startswith("stuck:") and word != STUCK_NOT_HELD else None


def finished(row: HoldRow, release: ReleaseRow | None) -> bool:
    """Section 5.1: the label step done, the agent attempt's abandon recorded with its claim no longer the factory's, and
    its comment written (none for a closed, missing or superseded task). `release` is the hold's agent attempt's own."""
    if row.labels is None or release is None or release.claim not in RETURNED:
        return False
    return row.commented_at is not None or row.labels in UNCOMMENTED


def hold_next(row: HoldRow, release: ReleaseRow | None) -> HoldNext:
    return "on_hold" if finished(row, release) else "hold"


def reingests(word: str, row: HoldRow | None, label: str) -> bool:
    """Section 7.2: an `on_hold` task is taken again by a round under `label` only when its hold removed (or found absent)
    the very label the task was taken under and that label is the round's: a later ready read with it is the person's
    answer. Any other abandon (another labels word, a hand abandon, another round label) keeps the `abandoned` skip."""
    return word == "on_hold" and row is not None and row.labels in ANSWERED and row.label == label
