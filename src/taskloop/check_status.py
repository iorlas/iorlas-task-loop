"""How the step commands follow a task into its check step (tl-8bh9.14.6 sections 9 and 10): the latest checks attempt of a
done implement attempt, what `tl step start` does with it (`route`), and its view's words (`checks_next`, `checks_result`,
`checks_release`). Reads and values only; `attempt_status` swaps the view, `operations` routes start and release."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from stream_proc import OwnedProcess

from taskloop.attempt_reads import ReleaseRow
from taskloop.attempt_types import AttemptResult
from taskloop.check_store import ChecksRow, CheckStore, ResultRow
from taskloop.setup_store import ProcessSeen

type Route = Literal["advance", "launch", "rerun", "answer", "abandoned"]
type ChecksNext = Literal["start", "wait", "release", "done", "unknown", "stuck:hung", "stuck:checks_refused"]
REFUSED_STUCK: Final = 2  # counted relaunches in a row (section 6.1) after which rounds stop relaunching a checks attempt
HALF_DONE: Final = ("The task's abandon is half done: its checks attempt is abandoned, the claim still kept. Run `tl step "
                    "release --abandon` again to return it.")


@dataclass(frozen=True)
class ChecksView:
    """The latest checks attempt of the view's done implement attempt, whose fields the view then shows (section 9), with
    the latest block's results and (`tl step show` only) each result's log path, by position."""

    row: ChecksRow
    results: tuple[ResultRow, ...]
    logs: tuple[Path | None, ...] = ()  # None for an `undefined` result: no command, no log


def latest(store: CheckStore, after: str) -> ChecksRow | None:
    """The implement attempt `after`'s latest checks attempt (its highest number); None when it has none."""
    rows = store.of_attempt(after)
    return rows[-1] if rows else None


def route(row: ChecksRow | None) -> Route:
    """`tl step start` on a task whose implement attempt is done: none yet `advance`s to number 1; an `admitted` one is
    launched with the checks launcher; one released by an abandon (the task's abandon half done) is never launched; a
    concluded `failed` and released one is re-run (number + 1); any other (passed, or not released yet) is answered."""
    if row is None:
        return "advance"
    if row.abandoned:
        return "abandoned"
    if row.released_at is None and row.phase == "admitted":
        return "launch"
    return "rerun" if row.released_at is not None and row.conclusion == "failed" else "answer"


def checks_result(row: ChecksRow) -> AttemptResult:
    """`collected passed`, `collected failed:<reason>`, or `pending admitted` (`attempt_result.succeeded` accepts `passed`)."""
    if row.conclusion is None:
        return AttemptResult("pending", row.phase)
    return AttemptResult("collected", "passed" if row.conclusion == "passed" else f"failed:{row.reason}")


def checks_release(row: ChecksRow, claim: str) -> ReleaseRow | None:
    """How the checks attempt ended its reservation: its own release and abandon flag, the implement attempt's claim."""
    if row.released_at is None or row.parked is None:
        return None
    return ReleaseRow(row.parked, row.released_at, claim, checks_abandoned=row.abandoned)


def checks_next(row: ChecksRow, entry: str, expired: bool, commands: ProcessSeen = "gone") -> ChecksNext:
    """Section 9's table: released is `done` (`release` when by an abandon: the claim is still to be returned); an entry
    not observable is `unknown`; a running entry `wait`s (`stuck:hung` past the deadline while still `admitted`; once
    concluded it is releasing its slot); concluded and still held is `release`; otherwise a relaunch (`start`, which past
    the deadline concludes `expired`), unless `REFUSED_STUCK` counted refusals in a row stop the rounds
    (`stuck:checks_refused`). `commands`: the latest setup run's and the latest block's unsettled commands as the entry's
    reconcile sees them (`commands_seen`): while one outlives its dead entry the relaunch would only count `checks:running`,
    so it `wait`s (`stuck:hung` past the deadline: nothing enforces its timeout now); unknown is `unknown`."""
    if row.released_at is not None:
        return "release" if row.abandoned else "done"
    if entry == "unknown":
        return "unknown"
    if entry == "running":  # a concluded entry still running is releasing its slot, whatever the deadline
        return "stuck:hung" if expired and row.phase == "admitted" else "wait"
    if row.phase == "concluded":
        return "release"
    return "stuck:checks_refused" if row.refusals >= REFUSED_STUCK else _relaunch(commands, expired)


def _relaunch(commands: ProcessSeen, expired: bool) -> ChecksNext:
    """An admitted attempt with no running entry: relaunched unless one of its commands still runs, or cannot be seen."""
    if commands == "unknown":
        return "unknown"
    return ("stuck:hung" if expired else "wait") if commands == "alive" else "start"


def commands_seen(
    seen: Callable[[OwnedProcess], ProcessSeen], setup: OwnedProcess | None, results: tuple[ResultRow, ...]
) -> ProcessSeen:
    """The setup run's unsettled command and every unsettled result's registered command, by the entry's own rule
    (`owned_processes.setup_seen`: another boot is gone): any alive is `alive`, else any unknown is `unknown`."""
    found = {seen(process) for process in (setup, *(row.process for row in results if row.unsettled)) if process is not None}
    return "alive" if "alive" in found else "unknown" if "unknown" in found else "gone"
