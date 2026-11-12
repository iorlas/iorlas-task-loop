"""`tl step next`: one scheduling round over the existing operations, stateless and idempotent.

Settle each existing attempt of the backlog by its `Next` word (relaunch an admitted attempt whose entry is not running,
a checks attempt with the checks launcher; verify, repeat; hold a round-taken task that stopped (`Next: hold`, through
`hold.hold_task`; an `on_hold` one costs nothing); report the rest: a failed checks attempt is never re-run), advance each
claimed task whose step is done (`Next: advance`) to its next step, oldest release first (a round-taken task whose advance
is refused `claim_lost` or `branch_moved` is held), then admit eligible ready tasks in priority order into the slots left
free, storing the round's label on each fresh attempt (an `on_hold` task whose hold removed this very label is eligible
again: `hold_status.reingests`), then publish the verified, released, unpublished results read at the start (a
round-taken `branch_moved` is held), then remove `held` from held tasks taken again (`hold.clear_holds`). It adds no
state, lock, Git write, tracker write or process of its own beyond the hold operation's: its only other output is one
append-only round-log line per move, never read back. No per-task hold word stops admission. Nothing merges or lands.

Claimed work goes before new work (.16 3.6): the advance takes free slots before admission. The label is ingestion's only:
admission's ready read carries it; an advance checks no label, takes no claim, and reads the tracker once per task (still
in progress for the factory's actor). Advance and admission read the tracker only when factory.db has an adopted slot
without a reservation row. Repeated rounds
(`rounds`) pass the previous round's `Round.written` keys as `quiet` (an identical move is not written again; the skip
lines of an admission that did not read the ready rows this round stay quiet too) and a `stopping` port asked before each
move (the graceful stop: no further move, `stopped=interrupted`).
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final

from taskloop.attempt_reads import StoreUnavailable
from taskloop.attempt_result import succeeded
from taskloop.attempt_status import AttemptView, Listed, StatusPorts, list_attempts
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey
from taskloop.hold import HoldPorts, clear_holds, hold_task
from taskloop.hold_status import reingests
from taskloop.operations import (
    UNKNOWN_KINDS,
    Failed,
    Move,
    Publish,
    PublishedTask,
    Quiet,
    Release,
    Round,
    Started,
    StartPorts,
    StartRequest,
    VerifiedTask,
    Verify,
    launched,
    minutes_refused,
    publish_task,
    relaunch_checks,
    start,
    verify_task,
)
from taskloop.publish import publish_word
from taskloop.round_log import INTERRUPTED
from taskloop.round_trail import Trail
from taskloop.selection import order
from taskloop.slot_release import NotReleased, release_word
from taskloop.task import TaskInspectionError
from taskloop.tracker import ACTOR, ReadyRows, TaskRow, ancestry, leaked_claim, ready_rows

# A refusal that stops admission for the round: no slot is free, or the round's own inputs or the store are wrong. Any
# other refusal (a claim elsewhere, a branch rule, a race that found an attempt another start made) is about one task.
STOPS: Final = frozenset({
    "no_free_slot", "checkout", "choices", "deadline", "expired", "constraint", "schema", "database", "input", "task",
})
# The advance's own stop: only words about the round's inputs, store or slots. `task`, `input`, `checkout` and
# `constraint` come from one claimed task's stored facts (its tracker root, its repository, its row) and are its skip.
ADVANCE_STOPS: Final = frozenset({"no_free_slot", "choices", "deadline", "expired", "database", "schema"})
# The advance's and the publication's refusals that hold a round-taken task (tl-8bh9.14.9 section 3) instead of a skip.
HOLDS: Final = frozenset({"claim_lost", "branch_moved"})
# re-running is safe; a single task's unsettled must not stop admission or back off the loop
STOPPING_UNKNOWN: Final = frozenset(UNKNOWN_KINDS) - {"unsettled"}


def never() -> bool:
    """The one-shot round's `stopping` port: nothing asks it to stop (Python's own Ctrl-C applies)."""
    return False


@dataclass(frozen=True)
class NextRequest:
    """`quiet`: the previous round's `Round.written` keys, not written to the round log again (None: every move is)."""

    backlog: str
    tracker_root: str
    checkout: Path
    label: str
    model: str
    effort: str
    minutes: int
    quiet: Quiet | None = None


@dataclass(frozen=True)
class RoundPorts:
    """Every port is an existing one, plus the hold's (`holding`: its store, the tracker's hold writes, the abandon's
    release ports, the clock, the evidence reader), the tracker's ready read, the round log (one line per move) and
    `stopping`, asked before each move."""

    reads: StatusPorts
    starting: StartPorts
    verifier: Verify
    releaser: Release
    publisher: Publish
    holding: HoldPorts
    ready: ReadyRows
    log: Callable[[str], None]
    stopping: Callable[[], bool] = never


def _word(result: Started | Failed) -> str:
    return result.status if isinstance(result, Started) else result.word


def _request(request: NextRequest, task_id: str) -> StartRequest:
    """The start of one task under the round's choices and label (stored only by a fresh admission)."""
    return StartRequest(task_id, request.backlog, request.tracker_root, request.checkout, request.model, request.effort, request.minutes,
                        request.label)


def run_round(ports: RoundPorts, request: NextRequest) -> Round | Failed:
    """One round: settle, advance, admit, publish, clear. A whole-round refusal (empty label, unreadable store) is
    `Failed`."""
    label = request.label.strip()
    if not label:
        return Failed("refused", "label", "An approval label is required (`--label auto`); a round never takes every ready task")
    refused = minutes_refused(request.minutes)
    if refused is not None:
        return refused
    request = replace(request, label=label)
    listed = list_attempts(ports.reads)
    if isinstance(listed, Failed):
        return listed
    current = _backlog(listed, request.backlog)
    trail = Trail(ports.log, ports.reads.clock, request.backlog, request.quiet)
    for each in current:
        if ports.stopping():
            return trail.close(INTERRUPTED)
        _settle(ports, request, each, trail)
    stopped = _advance(ports, request, tuple(each for each in current if each.next == "advance"), trail)
    stopped = stopped or _admit(ports, request, current, trail)
    if stopped != INTERRUPTED:
        stopped = _publish(ports, request.backlog, (each for each in current if each.next == "publish"), trail) or stopped
    if stopped != INTERRUPTED and not ports.stopping():
        _cleared(ports.holding, trail)
    return trail.close(INTERRUPTED if ports.stopping() else stopped)


def _backlog(listed: Listed, backlog: str) -> tuple[AttemptView, ...]:
    return tuple(each for each in listed.attempts if each.backlog == backlog)


def _settle(ports: RoundPorts, request: NextRequest, each: AttemptView, trail: Trail) -> None:
    """One existing attempt by its `Next` word: an abandoned one is never re-admitted; `advance` waits for the advance
    phase, `publish` for the last one; `hold` is the hold operation (due, or not finished), `on_hold` nothing at all."""
    task, attempt, step = each.task_id, each.attempt_id, each.step
    abandoned = each.release is not None and each.release.abandoned
    match each.next:
        case "start" if abandoned:
            return
        case "start" | "repeat":
            result = _resume(ports.starting, request.backlog, request.minutes, each)
            if isinstance(result, Failed) and result.reason == "abandoned":
                trail.add(Move(task, "skip", "abandoned", attempt, step=step))
            else:
                action = "relaunch" if each.next == "start" else "repeat"
                found = result.attempt_id if isinstance(result, Started) else attempt
                trail.add(Move(task, action, _word(result), found, _detail(result), step))  # a repeat stays in its step
        case "verify":
            trail.add(_verified(ports, request.backlog, each))
        case "hold":
            trail.add(_held(ports.holding, each))
        case "release" if each.checks is not None and each.checks.row.released_at is None:  # its entry is gone (`checks_next`)
            trail.add(_checks_released(ports, each, each.checks.row.key))
        case "wait" | "land":  # `land`: passed checks, one line while unchanged: the person's sign to run `tl step land`
            trail.add(Move(task, "report", "running" if each.next == "wait" else "land", attempt, step=step))
        case "publish" | "advance" | "landed" | "on_hold":  # only the person's `tl step land` lands (`rounds-never-land`)
            return
        case "done" if succeeded(each.result):
            return
        case "done":  # a checks attempt's reason is already `failed:<reason>` (`check report failed:test:failed`)
            word = each.result.reason if each.checks is not None else f"failed:{each.result.reason}"
            trail.add(Move(task, "report", word, attempt, step=step))
        case _:
            trail.add(Move(task, "report", each.next, attempt, step=step))


def _resume(ports: StartPorts, backlog: str, minutes: int, each: AttemptView) -> Started | Failed:
    """The snapshot's own attempt only, never an admission: relaunch its entry (`start`) or repeat its step (`repeat`).
    An attempt abandoned or released since the snapshot is `refused:abandoned`/`released`; another current attempt is
    `refused:changed`; the launcher's and the repeat's own fences decide the rest. A checks attempt goes to the checks
    launcher (`relaunch_checks`), fenced on its own store; it is never re-run here."""
    if each.checks is not None:
        return relaunch_checks(ports, backlog, each.task_id, each.attempt_id, minutes)
    try:
        found = ports.reader.attempt_of(backlog, each.task_id)
        ended = None if found is None else ports.reader.release_of(found[0])
    except StoreUnavailable as error:
        return Failed("unavailable", "store", str(error))
    if found is None or found[0].attempt_id != each.attempt_id:
        return Failed("refused", "changed", "Another attempt is current since this round read the store")
    if ended is not None:
        return Failed("refused", "abandoned" if ended.abandoned else "released")
    key, _phase, entry = found
    if each.next == "repeat":
        return ports.repeat.repeat(backlog, each.task_id, key, entry, minutes)
    return launched(ports.launcher.launch(backlog, each.task_id, minutes), backlog, each.task_id, key, existing=True)


def _held(ports: HoldPorts, each: AttemptView, reason: str | None = None) -> Move:
    """`hold.hold_task` for the view's task as one move of its agent attempt: `held <reason>` when this call finished the
    hold, `pending <missing step> <refusal>` (the refusal in the word, so the quiet key changes with it and an unchanged
    pending hold is written once), `refused <refusal>` (a lost race: the task changed since the round read it)."""
    found = hold_task(ports, each, reason)
    match found.word:
        case "held":
            word = f"held {found.reason}"
        case "pending":
            word = f"pending {found.missing} {found.refusal}"
        case "refused":
            word = f"refused {found.refusal}"
    return Move(found.task_id, "hold", word, found.attempt_id, found.detail, found.step)


def _cleared(ports: HoldPorts, trail: Trail) -> None:
    """Section 7.3 after publication: `hold cleared` once `held` is off a task taken again (or owned by its new hold);
    `hold clearing <word>` while a tracker or store failure or an unfinished new hold leaves it to a later round (quiet
    while unchanged). A failed read of the holds names no task: no line, the next round reads them again."""
    for each in clear_holds(ports.store, ports.tracker, ports.clock, trail.backlog):
        if each.task_id:
            word = each.word if each.word == "cleared" else f"clearing {each.word}"
            trail.add(Move(each.task_id, "hold", word, each.attempt_id, each.detail))


def _checks_released(ports: RoundPorts, each: AttemptView, key: AttemptKey) -> Move:
    """A concluded checks attempt still holding its slot, its entry gone (it died after concluding, or its release was
    held and the cause may have cleared): the settled release, whose stop proof holds while a command of it runs."""
    released = ports.starting.checks.release.release(key, False)
    detail = released.detail if isinstance(released, NotReleased) else ""
    return Move(each.task_id, "release", release_word(released), each.attempt_id, detail, each.step)


def _detail(result: Started | Failed) -> str:
    return result.detail if isinstance(result, Failed) else ""


def _verified(ports: RoundPorts, backlog: str, each: AttemptView) -> Move:
    """`tl step verify` as built: the verdict, then the settled release and the publication of a verified result."""
    verified = verify_task(ports.reads.store, ports.verifier, ports.releaser, ports.publisher, backlog, each.task_id)
    if isinstance(verified, VerifiedTask):
        word = f"{verified.status} release={verified.release} branch={verified.published}"
        return Move(each.task_id, "verify", word, each.attempt_id, step=each.step)
    return Move(each.task_id, "verify", verified.word, each.attempt_id, verified.detail, each.step)


def _full(store: AttemptStore) -> bool:
    """The free-slot read: True when every adopted slot in factory.db (any repo) has a reservation row, so no slot can be
    free and the tracker is not read. A failed read falls through: admission meets the store itself."""
    try:
        return store.slot_use().free == 0
    except StoreUnavailable:
        return False


def _stops(result: Failed, stops: frozenset[str] = STOPS) -> bool:
    """A stop: an unknown, or a refusal of the round's own inputs, the store or the slots (`stops`)."""
    return result.kind in STOPPING_UNKNOWN or (result.kind == "refused" and result.reason in stops)


def _advance(ports: RoundPorts, request: NextRequest, waiting: tuple[AttemptView, ...], trail: Trail) -> str:
    """The snapshot's done attempts whose step has a following one (`Next: advance`), oldest settled release first (.15
    Q3): each one's next step admitted into a free slot (one tracker read; no claim, no label) and launched, before any
    new task. An unknown or a round-wide refusal (`ADVANCE_STOPS`) ends both phases (`no_free_slot` unwritten, as
    admission's); any other refusal is about one task (`claim_lost`, `not_advanceable`, `branch_moved`, `abandoned`,
    `changed`, `task`, `checkout`, `input`, `constraint`): a `skip` of the done attempt, tried again next round, its
    unchanged line kept out of the log by `quiet`; `claim_lost` and `branch_moved` of a round-taken task (a label on its
    attempt) hold it instead. With every slot reserved: no tracker call."""
    if not waiting:
        return ""
    if _full(ports.reads.store):
        return "no_free_slot"
    for each in sorted(waiting, key=lambda view: (view.release.released_at if view.release else 0.0, view.task_id)):
        if ports.stopping():
            return INTERRUPTED
        result = start(ports.starting, _request(request, each.task_id), advancing=each.attempt_id)
        if isinstance(result, Started):
            trail.add(Move(each.task_id, "advance", result.status, result.attempt_id, step=result.step or ""))
            continue
        if result.reason == "no_free_slot":
            trail.unusable(each.task_id, result)
            return result.reason
        stop = _stops(result, ADVANCE_STOPS)
        if not stop and not result.admitted and result.kind == "refused" and result.reason in HOLDS and each.label is not None:
            trail.add(_held(ports.holding, each, result.reason))
        elif stop or result.admitted:  # an unknown, a stop, or the next step admitted but not launched (the next round relaunches)
            trail.add(Move(each.task_id, "advance", result.word, each.attempt_id, result.detail, each.step))
        else:
            trail.add(Move(each.task_id, "skip", result.reason, each.attempt_id, result.detail, each.step))
        if stop:
            return result.word
    return ""


def _admit(ports: RoundPorts, request: NextRequest, current: tuple[AttemptView, ...], trail: Trail) -> str:
    """Eligible ready tasks in priority order, one start each, until a slot or the round's inputs run out; the word that
    stopped admission early ("" when the candidates ran out). With every slot reserved: `no_free_slot`, no tracker call."""
    if ports.stopping():
        return INTERRUPTED
    if _full(ports.reads.store):
        return "no_free_slot"
    try:
        rows = ready_rows(ports.ready, request.label, ports.reads.clock())
    except TaskInspectionError as error:
        return "refused:tracker" if error.kind == "malformed" else "unavailable:tracker"
    # abandoned once its claim is no longer kept: a half-done checks abandon (claim still kept) is `attempted`; a finished
    # hold that removed this round's label is left out: the label in this ready read is the person's answer (7.2)
    again = frozenset(each.task_id for each in current if reingests(each.next, each.hold, request.label))
    attempts = {each.task_id: each.release is not None and each.release.claim != "kept" for each in current if each.task_id not in again}
    ordered, skipped = order(rows, ancestry(ports.ready, rows), attempts, ACTOR, again)
    trail.ranked = True
    ids = {each.task_id: (each.attempt_id, each.step) for each in current}
    for task_id, reason in skipped:
        attempt, step = ids.get(task_id, ("", ""))
        trail.add(Move(task_id, "skip", reason, attempt, step=step))  # attempted/abandoned: the attempt that holds it
    return _start_each(ports, request, ordered, trail)


def _start_each(ports: RoundPorts, request: NextRequest, ordered: tuple[TaskRow, ...], trail: Trail) -> str:
    for row in ordered:
        if ports.stopping():
            return INTERRUPTED
        result = start(ports.starting, _request(request, row.task_id))
        if isinstance(result, Started):
            trail.add(Move(row.task_id, "start", result.status, result.attempt_id, step=result.step or ""))
            continue
        stop = _stops(result)
        if result.reason != "no_free_slot":
            trail.add(Move(row.task_id, "start", _word(result), detail=result.detail))
        else:
            trail.unusable(row.task_id, result)
        if result.claim_leaked:
            trail.add(Move(row.task_id, "report", "claim_leaked", detail=leaked_claim(row.task_id)))
        if stop:
            return "no_free_slot" if result.reason == "no_free_slot" else _word(result)
    return ""


def _publish(ports: RoundPorts, backlog: str, verified: Iterable[AttemptView], trail: Trail) -> str:
    """The verified, released, unpublished results read before settling: pushed again every round until one succeeds. One
    whose entry still runs is left to that entry, which publishes right after its release; `interrupted` on a stop. A
    round-taken task refused `branch_moved` is held instead of being pushed again every round."""
    for each in verified:
        if ports.stopping():
            return INTERRUPTED
        if each.entry == "running":
            continue
        found = publish_task(ports.reads.store, ports.publisher, backlog, each.task_id)
        if isinstance(found, PublishedTask):
            trail.add(Move(each.task_id, "publish", publish_word(found.result), found.attempt_id, step=each.step))
        elif found.kind == "refused" and found.reason == "branch_moved" and each.label is not None:
            trail.add(_held(ports.holding, each, "branch_moved"))
        else:
            trail.add(Move(each.task_id, "publish", found.word, each.attempt_id, found.detail, each.step))
    return ""
