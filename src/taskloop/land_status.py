"""A task's land in its status (tl-8bh9.14.8 section 14): the latest land candidate of a released checks attempt, its
latest block's results and its land process as observed now, and the `Next` word it gives. Reads and values only (the
land's own modules are never imported: `entries-never-land`); `attempt_status` places the view, `show_render` and
`result_data` print it.

`Next`, after a released, not abandoned checks attempt (otherwise its own word stands):

| the latest candidate | `Next` |
|---|---|
| validated or superseded, still holding its slot (delivered or closed or not) | `release` |
| superseded `abandoned` (the checks attempt not abandoned: an abandon stopped half way) | `release` (`--abandon` again) |
| pending, its land process unobservable | `unknown` |
| none: the checks passed | `land` (failed checks: `done`, unchanged) |
| pending (validating in its slot), pushable, failed, superseded, or delivered and not closed | `land` |
| delivered and closed, its slot released | `landed` |

A pending candidate holds its slot too, but `tl step land` (not a release) resumes it: `land`. A round lands it under `land: auto`
(`round_land`); otherwise rounds only report `land`, `landed` and a land's `release`."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from taskloop.attempt_reads import StoreConnection
from taskloop.attempt_types import EntryIdentity, Observe
from taskloop.check_store import ChecksRow, CheckStore, ResultRow
from taskloop.land_store import LandRow, LandStore

type LandNext = Literal["land", "landed", "release", "unknown"]
type Process = Literal["none", "running", "gone", "different_process", "unknown"]


@dataclass(frozen=True)
class LandView:
    """The latest candidate (`row`), its latest block's results with each log path by position (`tl step show` only), and
    its stored land process as observed now (`none`: none stored)."""

    row: LandRow
    results: tuple[ResultRow, ...]
    process: Process = "none"
    logs: tuple[Path | None, ...] = ()


def land_view(store: StoreConnection, checks: ChecksRow, observe: Observe) -> LandView | None:
    """The checks attempt's latest candidate with its results and its land process observed (an abandoned one's too: its
    history); None when it has none or the checks attempt is not released (no land can follow). StoreUnavailable
    propagates."""
    if checks.released_at is None:
        return None
    row = LandStore(store.connect, store.begin).latest(checks.key.attempt_id)
    if row is None:
        return None
    results = CheckStore(store.connect, store.begin).results(row.key) if row.slot is not None else ()
    return LandView(row, results, _seen(observe, row.entry) if row.holds_slot else "none")


def _seen(observe: Observe, entry: EntryIdentity | None) -> Process:
    if entry is None:
        return "none"
    seen = observe(entry)
    return "running" if seen == "matching" else seen


def land_next[W: str](word: W, checks: ChecksRow, land: LandView | None) -> W | LandNext:
    """Section 14's `Next` over the checks view's own word: only a released, not abandoned checks attempt (its `done`)
    goes on to the land."""
    if word != "done" or checks.abandoned:
        return word
    if land is None:
        return "land" if checks.conclusion == "passed" else word
    row = land.row
    if (row.holds_slot and not row.pending) or row.superseded == "abandoned":  # the abandon's own candidate: it goes on
        return "release"
    if row.pending and land.process == "unknown":
        return "unknown"
    return "landed" if row.delivery is not None and row.close is not None else "land"


def with_logs(land: LandView, path: Callable[[int, str], Path]) -> LandView:
    """Each result's log path (`check-<block>-<name>.log` in the candidate's evidence directory; none for `undefined`)."""
    logs = tuple(None if row.conclusion == "undefined" else path(row.block, row.name) for row in land.results)
    return LandView(land.row, land.results, land.process, logs)
