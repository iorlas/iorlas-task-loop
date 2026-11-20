"""The dashboard's factory commit of an agent attempt: what the factory checked after a committing answer, which check failed and
the typed result, from the owners of those facts only (the stored answer and verdict, and the repeat attempt that records the
listing the failed factory commit gave). Display only; the order of the checks is `factory_commit.settle`'s, and a name here is the
page's wording, never parsed from a log."""

from typing import Final

from taskloop.attempt_reads import AttemptRow
from taskloop.attempt_result import committing, judged
from taskloop.attempt_types import AttemptResult, Rejected
from taskloop.dash_model import CommitCheck, FactoryCommit, State

STEP: Final = "commit"
# The checks in the order the factory makes them, each with the reason that names it as the failing one.
CHECKS: Final = (
    ("The slot is on the task branch at the agent's start", "branch"),
    ("Every listed path is a plain file the factory may commit", "unsafe"),
    ("No ignored file under the listed paths", "ignored"),
    ("Nothing is left uncommitted at the commit", "uncommitted"),
    ("The commit passes the step's rules", "rejected"),
)


def applies(result: AttemptResult) -> bool:
    """A clean run's valid answer of effect `commit` or `keep` receives a factory commit; every other end has none."""
    return result.execution is not None and committing(result.execution)


def _failed(result: AttemptResult, successor: AttemptRow | None) -> str | None:
    """The reason or `rejected` of the check that failed; None when the factory commit passed or has no result yet."""
    verdict = None if result.execution is None else result.execution.verdict
    if isinstance(verdict, Rejected):
        return "rejected"
    if verdict is None and successor is not None:
        return successor.repeat_reason
    return None


def factory_commit(row: AttemptRow, number: int, result: AttemptResult, successor: AttemptRow | None) -> tuple[FactoryCommit, State]:
    """Where `row` (agent attempt `number` of its step) received its factory commit: checks passed, failed or not reached, the result and
    listing the failed check gave (only a repeat stores it). State: passed, failed, or running while it still holds its slot unsettled."""
    stored = result.execution
    verdict = None if stored is None else stored.verdict
    failed = _failed(result, successor)
    names = [reason for _text, reason in CHECKS]
    at = names.index(failed) if failed in names else len(names) if verdict is not None else -1
    checks = tuple(CommitCheck(text, "failed" if index == at else "passed" if index < at else "not_run")
                   for index, (text, _reason) in enumerate(CHECKS))
    if verdict is not None:
        word = judged(verdict)
    elif failed in {"unsafe", "ignored", "uncommitted"}:
        word = f"uncommitted:{failed}"
    else:
        word = "refused:" + failed if failed else "pending"
    state: State = "failed" if failed else "succeeded" if verdict is not None else "running" if row.held else "failed"
    listing = successor.repeat_listing if verdict is None and successor is not None else ()
    paths = () if stored is None else stored.answer.paths
    return FactoryCommit(row.step, number, paths, checks, word, listing), state
