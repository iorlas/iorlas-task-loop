"""The hold operation (tl-8bh9.14.9 sections 5 and 7.3): `hold_task`, the one application operation that holds a
round-taken task, and `clear_holds`, which removes `held` once a held task was taken again. The round calls both (H3);
`tl step next` is a round and may run beside `tl step rounds`, so every step is fenced and a rerun or a concurrent caller
does only what is missing.

`hold_task`, in order: the record (`HoldStore.insert`, fenced on A and its cause being current; a lost race is
`refused:changed`); the label step (right before it A must still be the task's current attempt; one tracker read and the
writes of 5.2, then `HoldStore.labelled`, fenced again); the abandon through `operations.release_task(abandon=True)`
(never a copy of it); then, once the abandon's outcome is known, the one comment under the lease (`HoldStore.commenting`):
written when the claim was returned, or when the abandon was refused for a reason only the person clears (section 12);
never after a transient refusal, which the next round retries. A closed or missing task is written nothing. Every bd
call is `TrackerHolds`' (one try, capped); a tracker failure leaves the hold pending for the next round.

Before the label step and the abandon, the cause is fenced again on the task's status read now (`_caused`): A current,
the stored cause still the task's current view (a checks cause its latest checks attempt) and still a hold cause. A
hold whose cause is gone (the person restarted the work after it was recorded) never abandons it: it is retired
(`held` removed if it added it, then the row deleted, `refused:retired`)."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Final, Literal, Protocol

from taskloop.attempt_reads import AttemptRow, StoreRefused, StoreUnavailable
from taskloop.attempt_status import AttemptView, agent_attempt
from taskloop.attempt_store import AttemptStore
from taskloop.evidence_files import EvidenceFiles
from taskloop.hold_facts import Pending, facts, outcome, refusal
from taskloop.hold_status import cause
from taskloop.hold_store import HoldInsert, HoldRow, HoldStore
from taskloop.hold_text import Kept, Returned, comment
from taskloop.operations import ChecksReleasing, Clock, Failed, Release, release_task
from taskloop.tracker import ACTOR
from taskloop.tracker_client import TrackerHolds

type Missing = Literal["", "labels", "abandon", "comment", "retire"]
type Status = Callable[[str, str], AttemptView | None]  # (backlog, task): its current view read now, before any hold word
type Claim = Literal["ours", "not_ours", "unknown"]
COMMENTING: Final = ("moved", "absent", "not_ours")  # the label words after which the hold writes its one comment
ROUND_CAUSES: Final = frozenset({"claim_lost", "branch_moved"})  # the advance's and publication's refusals (no status word)
ROUND_WORDS: Final = frozenset({"advance", "publish"})  # the view's word while such a cause still stands


@dataclass(frozen=True)
class HoldPorts:
    """The hold's store and reads, the tracker's hold writes, the abandon's release ports (as `tl step release
    --abandon` uses them), the clock, the evidence reader and the task's status read now (`attempt_status.current_view`)."""

    store: HoldStore
    reader: AttemptStore
    tracker: TrackerHolds
    releaser: Release
    checks: ChecksReleasing
    clock: Clock
    files: EvidenceFiles
    status: Status


@dataclass(frozen=True)
class HoldMove:
    """What one `hold_task` call did: `held` (this call finished the hold), `pending` (`missing` names the first step
    still to do, `refusal` the word that keeps it: `held:slot_dirty`, `unsettled:worker_alive`, `unavailable:tracker`,
    ...), or `refused` (`refusal`: `refused:changed` when A or its cause is no longer current, `refused:unlabelled` for a
    task started by hand, `refused:no_cause`). `attempt_id` is the hold's agent attempt A; `detail` is diagnostic only."""

    task_id: str
    attempt_id: str
    step: str
    reason: str
    word: Literal["held", "pending", "refused"]
    missing: Missing = ""
    refusal: str = ""
    detail: str = ""


class Move(Protocol):
    def __call__(self, word: Literal["held", "pending", "refused"], missing: Missing = "", refused: str = "", detail: str = "",
                 ) -> HoldMove: ...


@dataclass(frozen=True)
class Cleared:
    """One `clear_holds` result: `cleared` (`held` removed, or owned by the task's new hold), or the refusal word that
    leaves it for the next round (`unavailable:tracker`, `unavailable:store`, `refused:changed`, or `pending:held_again`:
    the task's new hold has not finished its label step; `detail` names that hold's attempt)."""

    task_id: str
    attempt_id: str
    word: str
    detail: str = ""


def hold_task(ports: HoldPorts, view: AttemptView, reason: str | None = None) -> HoldMove:
    """Hold the view's task for `reason` (default: the view's due cause; a recorded hold keeps its own), or finish a hold
    already recorded. `view` is the round's status view of the task's current attempt (a checks view's cause is its
    checks attempt; A is the implement attempt it follows)."""
    agent = agent_attempt(view)
    why = reason or view.hold_due or ""

    def move(word: Literal["held", "pending", "refused"], missing: Missing = "", refused: str = "", detail: str = "") -> HoldMove:
        return HoldMove(view.task_id, agent, view.step, why, word, missing, refused, detail)

    row: HoldRow | None = None
    try:
        row = ports.store.of_attempts((agent,)).get(agent)
        if row is None:
            if not why:
                return move("refused", refused="refused:no_cause")
            row = ports.store.insert(HoldInsert(agent, view.attempt_id, why, ports.clock()))
        why = row.reason
        if not _caused(ports, row):
            return _retired(ports, row, move)
        claim: Claim = "unknown"  # whose claim the label step read; not known when it ran in an earlier call
        if row.labels is None:
            labelled = _labels(ports, view, row)
            if isinstance(labelled, tuple):
                return move("refused" if labelled[0] == "refused:changed" else "pending", "labels", *labelled)
            row, claim = labelled.row, labelled.claim
        return _abandoned(ports, view, row, move, claim)
    except StoreRefused as error:
        return move("refused", refused=f"refused:{error.reason}")
    except StoreUnavailable as error:
        return move("pending", "labels" if row is None or row.labels is None else "abandon", "unavailable:store", str(error))


def _caused(ports: HoldPorts, row: HoldRow) -> bool:
    """The re-fence of an unfinished hold's cause on the task's status read now: True while an abandon of A (the hold's,
    or a person's) is under way, or while the current view is still the stored cause (A, or a checks cause as A's latest
    checks attempt) and still a hold cause (`hold_status.cause`; an advance's or publication's refusal: the view still
    `advance` or `publish`). A not current is left to the label and abandon fences (`refused:changed`)."""
    fresh = ports.status(row.backlog, row.task_id)
    if fresh is None or agent_attempt(fresh) != row.attempt_id or (fresh.release is not None and fresh.release.abandoned):
        return True
    if fresh.attempt_id != row.cause_id:
        return False
    return fresh.next in ROUND_WORDS if row.reason in ROUND_CAUSES else cause(fresh) is not None


def _retired(ports: HoldPorts, row: HoldRow, move: Move) -> HoldMove:
    """A hold whose cause is gone: `held` removed first when its label step added it (a failure: pending, retried), then
    the row deleted, so the restarted work goes on and a later stop can be held afresh. The approval label is not added
    back: a claimed task advances without it (D3)."""
    if row.labels in ("moved", "absent"):
        answer = ports.tracker.clear(row.tracker_root, row.task_id)
        if answer.word == "unavailable":
            return move("pending", "retire", "unavailable:tracker", answer.detail)
    ports.store.retire(row.attempt_id, row.rev)
    return move("refused", refused="refused:retired", detail="The hold's cause is gone: the work was restarted after it was recorded")


@dataclass(frozen=True)
class _Labelled:
    row: HoldRow
    claim: Claim


def _labels(ports: HoldPorts, view: AttemptView, row: HoldRow) -> _Labelled | tuple[str, str]:
    """5.1 step 3: A still the task's current attempt, then the tracker's label step and its word recorded (fenced on A
    still current), with whose claim it read (`ours` only for the factory's assignee); a stale fence or a tracker failure
    writes nothing and is retried: (word, detail)."""
    current = ports.reader.attempt_of(view.backlog, view.task_id)
    if current is None or current[0].attempt_id != row.attempt_id:
        return "refused:changed", "Another attempt of the task is current"
    answer = ports.tracker.labels(row.tracker_root, row.task_id, row.label)
    match answer.word:
        case "moved" | "absent" | "not_ours" | "closed" | "missing":
            claim: Claim = "ours" if answer.word in ("moved", "absent") and answer.detail == ACTOR else "not_ours"
            return _Labelled(ports.store.labelled(row.attempt_id, row.rev, answer.word, ports.clock()), claim)
        case "precondition":
            return "unavailable:tracker", "precondition: the task's assignee changed after it was read"
        case "bad_label":
            return "refused:bad_label", f"The stored label {row.label!r} cannot be passed to bd"
        case "unavailable":
            return "unavailable:tracker", answer.detail


def _abandoned(ports: HoldPorts, view: AttemptView, row: HoldRow, move: Move, claim: Claim) -> HoldMove:
    """5.1 steps 4 and 5: the abandon as `tl step release --abandon` runs it, then the comment (once) by its outcome: the
    claim returned, or kept by a refusal only the person clears; none after a transient refusal. The abandon acts on the
    task's current attempt, so A must still be it (a stale round snapshot, the task taken again meanwhile: `changed`)."""
    current = ports.reader.attempt_of(view.backlog, view.task_id)
    if current is None or current[0].attempt_id != row.attempt_id:
        return move("refused", "abandon", "refused:changed", "Another attempt of the task is current")
    released = release_task(ports.reader, ports.releaser, ports.checks, view.backlog, view.task_id, abandon=True)
    word, detail = (refusal(released), released.detail) if isinstance(released, Failed) else ("", "")
    agent = _agent_row(ports.reader, view, row.attempt_id)
    found = outcome(ports.reader, agent, released)
    found = replace(found, claim=claim) if isinstance(found, Kept) else found
    if isinstance(found, Pending):
        return move("pending", "abandon", found.word, detail)
    if row.labels in COMMENTING and row.commented_at is None:
        leftovers = view.leftovers if view.checks is None and view.attempt_id == row.attempt_id else ()
        written = _comment(ports, row, agent, found, leftovers)
        if isinstance(written, str):
            return move("pending", "comment", written) if isinstance(found, Returned) else move("pending", "abandon", word, written)
        row = written
    if isinstance(found, Kept):
        return move("pending", "abandon", word, detail)
    return move("held")


def _comment(ports: HoldPorts, row: HoldRow, agent: AttemptRow, found: Returned | Kept, leftovers: tuple[str, ...]) -> HoldRow | str:
    """The one comment under the lease: a lost lease (another caller's, live) writes nothing (`refused:leased`); a
    posted comment (or a task deleted meanwhile, which can take none) is recorded; a tracker failure keeps the lease,
    retaken once it is older than `COMMENT_LEASE`."""
    leased = ports.store.commenting(row.attempt_id, row.rev, ports.clock())
    labels = None if leased is None else leased.labels
    if leased is None or labels not in COMMENTING:
        return "refused:leased"
    text = comment(facts(ports.files, ports.reader, leased, labels, agent, leftovers), found)
    answer = ports.tracker.comment(leased.tracker_root, leased.task_id, text)
    if answer.word == "unavailable":  # one capped try failed: the lease is given back, so the next round retries at once
        ports.store.uncommenting(leased.attempt_id, leased.rev)
        return "unavailable:tracker"
    return ports.store.commented(leased.attempt_id, leased.rev, ports.clock())


def _agent_row(reader: AttemptStore, view: AttemptView, attempt_id: str) -> AttemptRow:
    """A's own row (its key, X, label and registered agent); StoreRefused `changed` when it is no longer stored."""
    found = next((each for each in reader.attempts(view.backlog, view.task_id) if each.key.attempt_id == attempt_id), None)
    if found is None:
        raise StoreRefused("changed")
    return found


def clear_holds(store: HoldStore, tracker: TrackerHolds, clock: Clock, backlog: str) -> tuple[Cleared, ...]:
    """Section 7.3, each round after publication: every hold whose task was taken again and whose `held` may still be
    on the task. Right before each tracker call the task's current hold is read again (a round and `tl step next` may
    hold the task again meanwhile): one that moved the labels (`moved`, `absent`) owns `held`, so only `cleared_at` is
    set (no tracker call); one whose label step has not finished leaves the row for a later round (it may yet end
    `not_ours`, which writes no label); with none, or one that wrote no label, `held` is removed with no read first (an
    absent label is no failure), then `cleared_at` (a hold whose label step never finished becomes `superseded` in the
    same write). Only the holds of `backlog` (the round's own). A failure is retried next round."""
    try:
        found = store.uncleared(backlog)
    except StoreUnavailable as error:
        return (Cleared("", "", "unavailable:store", str(error)),)
    done: list[Cleared] = []
    for each in found:
        row = each.row
        try:
            newer = store.current_hold(row.attempt_id)
        except StoreUnavailable as error:
            done.append(Cleared(row.task_id, row.attempt_id, "unavailable:store", str(error)))
            continue
        if newer is not None and newer.labels is None:
            done.append(Cleared(row.task_id, row.attempt_id, "pending:held_again", newer.attempt_id))
            continue
        if newer is None or newer.labels not in ("moved", "absent"):
            answer = tracker.clear(row.tracker_root, row.task_id)
            if answer.word == "unavailable":
                done.append(Cleared(row.task_id, row.attempt_id, "unavailable:tracker", answer.detail))
                continue
        try:
            store.cleared(row.attempt_id, row.rev, clock())
        except StoreRefused as error:
            done.append(Cleared(row.task_id, row.attempt_id, f"refused:{error.reason}"))
            continue
        except StoreUnavailable as error:
            done.append(Cleared(row.task_id, row.attempt_id, "unavailable:store", str(error)))
            continue
        done.append(Cleared(row.task_id, row.attempt_id, "cleared"))
    return tuple(done)
