"""The `tl step show` lines of one view: an agent attempt's, or (tl-8bh9.14.6 section 9) a checks attempt's with its
`Check:` lines. Fixed words around the status values; nothing here decides, reads or writes (`step_render` places them)."""

from datetime import UTC, datetime
from pathlib import Path

from taskloop.attempt import succeeded
from taskloop.attempt_status import AttemptView, SetupShown, Shown
from taskloop.attempt_types import ATTEMPTS
from taskloop.check_status import ChecksView
from taskloop.check_store import ResultRow
from taskloop.checks import differs


def _when(at: float) -> str:
    return f"{datetime.fromtimestamp(at, UTC):%Y-%m-%d %H:%M:%S} UTC"


def _common(each: AttemptView) -> tuple[list[str], str, list[str]]:
    """The earlier attempts, the entry's registration and the release, as both views show them."""
    earlier = [f"Earlier: {attempt_id} " + (why if why in ("abandoned", "advanced", "re-run") else f"repeated ({why})")
               for attempt_id, why in each.earlier]
    entry = "" if each.entry_process is None else f" (pid {each.entry_process[0]}, started {each.entry_process[1]})"
    ended = each.release
    released = [] if ended is None else [
        f"Released: {_when(ended.released_at)}, slot parked at {ended.head}; claim {ended.claim}{'; abandoned' if ended.abandoned else ''}"
    ]
    return earlier, entry, released


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
        f"Entry: {each.entry}{entry}", f"Worker: {worker}", f"Result: {each.result.status} {each.result.reason}".rstrip(),
        f"Succeeded: {'yes' if succeeded(each.result) else 'no'}", f"Deadline passed: {'yes' if each.deadline_passed else 'no'}",
        *released, *published,
    ]


def setup_line(found: SetupShown | None) -> str:
    """The latest setup run's conclusion from factory.db (`unfinished` while it has none) and its log's path."""
    if found is None:
        return "Setup: none"
    row, whose = found.row, "" if found.attempt_id is None else f" (attempt {found.attempt_id}'s, which this repeat keeps)"
    return f"Setup: run {row.run} {row.conclusion or 'unfinished'} at {row.commit}{whose}; log {found.log}"


def check_line(row: ResultRow, log: Path | None, checks: ChecksView) -> str:
    """One latest-block result: its conclusion, exit and whole seconds, the process group of a command not proven gone,
    its log, and whether `main` requires it (a required one whose argv at X differs from the one stored from `main` says
    so)."""
    if row.conclusion == "undefined":
        return f"Check: {row.name} undefined (required by main, not defined at X)"
    state = "unfinished" if row.conclusion is None else row.conclusion
    state += "" if row.rc is None else f", exit {row.rc}"
    state += "" if row.ended_at is None else f", {round(row.ended_at - row.started_at)} s"
    state += f", process group {row.process.pgid}" if row.process is not None and row.unsettled else ""  # to verify before a stop
    required = checks.row.required
    mark = " (not required)" if row.name not in dict(required) else " (argv differs from main)" if differs(required, row) else ""
    return f"Check: {row.name} {state}{'' if log is None else f'; log {log}'}{mark}"


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
        *([check_line(result, log, checks) for result, log in zip(checks.results, logs, strict=True)] or ["Check: none yet"]),
        f"Result: {each.result.status} {each.result.reason}", f"Succeeded: {'yes' if succeeded(each.result) else 'no'}", *released,
    ]


def show_lines(result: Shown) -> list[str]:
    """The view's lines up to its setup run (an agent attempt) or its result and release (a checks attempt)."""
    each = result.view
    if each.checks is None:
        return [*_agent_lines(each), setup_line(result.setup)]
    return _checks_lines(each, each.checks, setup_line(result.setup))
