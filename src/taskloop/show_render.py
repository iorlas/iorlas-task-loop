"""The `tl step show` lines of one view: an agent attempt's, or (tl-8bh9.14.6 section 9) a checks attempt's with its
`Check:` lines and (tl-8bh9.14.8 section 14) its latest land candidate's `Land` lines, then a hold's `Hold` lines
(tl-8bh9.14.9 section 10). Fixed words around the status
values; nothing here decides, reads or writes (`step_render` places them). Every stored text a `Land` line shows (the
validation's reason, the slot) is printed as one printable line (`land_summary.one_line`). A process is shown by its pid
only: its stored start is a clock-tick token that proves identity (JSON keeps it), not a time a person reads."""

from datetime import UTC, datetime
from pathlib import Path

from taskloop.attempt_result import succeeded
from taskloop.attempt_status import AttemptView, SetupShown, Shown
from taskloop.attempt_types import ATTEMPTS
from taskloop.check_status import ChecksView
from taskloop.check_store import Required, ResultRow
from taskloop.checks import differs
from taskloop.hold_guide import hold_lines
from taskloop.land_close import NOT_SYNCED
from taskloop.land_status import LandView
from taskloop.land_summary import one_line


def _when(at: float) -> str:
    return f"{datetime.fromtimestamp(at, UTC):%Y-%m-%d %H:%M:%S} UTC"


def _common(each: AttemptView) -> tuple[list[str], str, list[str]]:
    """The earlier attempts, the entry's registration and the release, as both views show them."""
    earlier = [f"Earlier: {attempt_id} " + (why if why in ("abandoned", "advanced", "re-run") else f"repeated ({why})")
               for attempt_id, why in each.earlier]
    entry = "" if each.entry_process is None else f" (pid {each.entry_process[0]})"  # its start token is identity, not a time
    ended = each.release
    released = [] if ended is None else [
        f"Released: {_when(ended.released_at)}, slot parked at {ended.head}; claim {ended.claim}{'; abandoned' if ended.abandoned else ''}"
    ]
    return earlier, entry, released


def last_command(each: AttemptView) -> str | None:
    """The time since the agent's latest command (display only; None when the agent cannot be running)."""
    found = each.last_command
    return None if found is None else found if isinstance(found, str) else f"{found} s ago"


def _agent_lines(each: AttemptView) -> list[str]:
    earlier, entry, released = _common(each)
    # the stored registration only: the agent may have exited long ago, so it is never shown as running
    worker = "none" if each.worker is None else f"last known pid {each.worker[0]}, process group {each.worker[1]} (not checked)"
    repeats = "" if each.previous_attempt_id is None else f"; repeats {each.previous_attempt_id}, {each.repeat_reason}"
    found = each.published
    published = [] if found is None else [f"Published: task/{each.task_id} at {found.commit} on origin, {_when(found.published_at)}"]
    return [
        f"Task: {each.task_id} (backlog {each.backlog})", f"Step: {each.step}",
        f"Attempt: {each.attempt_id} ({each.number} of at most {ATTEMPTS}{repeats})", *earlier,
        f"Slot: {each.slot}", f"Phase: {each.phase}",
        f"Entry: {each.entry}{entry}", f"Worker: {worker}",
        *([] if last_command(each) is None else [f"Last command: {last_command(each)}"]),
        f"Result: {each.result.status} {each.result.reason}".rstrip(),
        f"Succeeded: {'yes' if succeeded(each.result) else 'no'}", f"Deadline passed: {'yes' if each.deadline_passed else 'no'}",
        *released, *published,
    ]


def setup_line(found: SetupShown | None) -> str:
    """The latest setup run's conclusion from factory.db (`unfinished` while it has none) and its log's path."""
    if found is None:
        return "Setup: none"
    row, whose = found.row, "" if found.attempt_id is None else f" (attempt {found.attempt_id}'s, which this repeat keeps)"
    return f"Setup: run {row.run} {row.conclusion or 'unfinished'} at {row.commit}{whose}; log {found.log}"


def check_line(row: ResultRow, log: Path | None, required: Required, prefix: str = "Check") -> str:
    """One latest-block result: its conclusion, exit and whole seconds, the process group of a command not proven gone,
    its log, and whether `main` requires it (a required one whose argv at X differs from the one stored from `main` says
    so)."""
    if row.conclusion == "undefined":
        return f"{prefix}: {row.name} undefined (required by main, not defined at X)"
    state = "unfinished" if row.conclusion is None else row.conclusion
    state += "" if row.rc is None else f", exit {row.rc}"
    state += "" if row.ended_at is None else f", {round(row.ended_at - row.started_at)} s"
    state += f", process group {row.process.pgid}" if row.process is not None and row.unsettled else ""  # to verify before a stop
    mark = " (not required)" if row.name not in dict(required) else " (argv differs from main)" if differs(required, row) else ""
    return f"{prefix}: {row.name} {state}{'' if log is None else f'; log {log}'}{mark}"


def _checks_lines(each: AttemptView, checks: ChecksView, setup: str) -> list[str]:
    earlier, entry, released = _common(each)
    row = checks.row
    moved = row.target_seen is not None or row.reason == "main_moved"
    logs: tuple[Path | None, ...] = checks.logs or (None,) * len(checks.results)
    return [
        f"Task: {each.task_id} (backlog {each.backlog})", f"Step: {each.step}", f"Attempt: {each.attempt_id} (run {each.number})",
        *earlier, f"Slot: {each.slot}", f"Phase: {each.phase}", f"Entry: {each.entry}{entry}", f"Commit: {row.commit}",
        f"Required: {', '.join(name for name, _ in row.required)} (main at {row.target})",
        *([f"Main: moved from {row.target} to {row.target_seen or 'nothing (deleted)'}"] if moved else []),
        f"Profile: {row.profile_digest} at X" if row.profile_digest else "Profile: not read yet",
        *([f"Refused: {row.refusal} ({row.refusals} in a row)"] if row.refusals else []), setup,
        *([check_line(result, log, checks.row.required) for result, log in zip(checks.results, logs, strict=True)] or ["Check: none yet"]),
        f"Result: {each.result.status} {each.result.reason}", f"Succeeded: {'yes' if succeeded(each.result) else 'no'}", *released,
    ]


def _candidate(land: LandView, checked: Required) -> list[str]:
    """The candidate, the required names at O against the checks attempt's (`checked`), and its slot and land process."""
    row = land.row
    how = ("no change: main already holds X's changes" if row.validation == "no_change" else
           "same tree as X, no checks" if row.validation == "same_tree" else
           f"{'same tree as X' if row.tree_same else 'merged onto a moved main'}, checks run again")
    names = [name for name, _ in row.required]
    before = [name for name, _ in checked]
    same = "same as the checks" if set(names) == set(before) else f"the checks required {', '.join(before)}"
    lines = [f"Land: candidate {row.number} ({row.key.attempt_id}) onto origin main at {row.origin}: {row.commit}; {how}",
             f"Land required: {', '.join(names)} (origin main at {row.origin}; {same})"]
    if row.slot is not None:
        where = "held" if row.released_at is None else f"released {_when(row.released_at)}, parked at {row.parked}"
        lines.append(f"Land slot: {one_line(row.slot, 40)}, {where}")
    if row.entry is not None and land.process != "none":
        lines.append(f"Land process: {land.process} (pid {row.entry[0]})")
    return lines


def land_lines(land: LandView, checked: Required) -> list[str]:
    """Section 14's lines: the candidate, its block's `Land check:` lines, its result, why it was superseded, the delivery
    and the close (then the tracker sync line). `checked`: the checks attempt's required names."""
    row = land.row
    logs: tuple[Path | None, ...] = land.logs or (None,) * len(land.results)
    result = (f"failed {one_line(row.reason or '', 200)}" if row.validation == "failed" else row.validation or "pending")
    lines = [*_candidate(land, checked), *(check_line(each, log, row.required, "Land check")
                                           for each, log in zip(land.results, logs, strict=True))]
    lines += [f"Land result: {result}"]
    lines += [] if row.superseded is None else [f"Land superseded: {row.superseded}"]
    if row.delivery == "pushed" and row.delivered_at is not None:
        lines.append(f"Pushed: origin main at {row.remote_head}, {_when(row.delivered_at)}")
    elif row.delivery == "no_change" and row.delivered_at is not None:
        lines.append(f"Delivered: no change, origin main at {row.origin} already held it, {_when(row.delivered_at)}")
    if row.close is not None and row.closed_at is not None:
        lines += [f"Closed: {_when(row.closed_at)} ({row.close})", NOT_SYNCED]
    return lines


def show_lines(result: Shown) -> list[str]:
    """The view's lines up to its setup run (an agent attempt) or its result and release (a checks attempt), then its
    land's."""
    each = result.view
    if each.checks is None:
        failed = result.failed
        held = [] if failed is None else [check_line(row, log, failed.row.required, "Failed check")
                                          for row, log in zip(failed.results, failed.logs, strict=True)]
        return [*_agent_lines(each), setup_line(result.setup), *held, *hold_lines(each)]
    land = [] if each.land is None else land_lines(each.land, each.checks.row.required)
    return [*_checks_lines(each, each.checks, setup_line(result.setup)), *land, *hold_lines(each)]
