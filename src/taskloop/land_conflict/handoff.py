"""Ordinary land hands checked conflicts to retained execution and stops delivery."""

from collections.abc import Callable
from dataclasses import dataclass

from git_porcelain import Repo

from taskloop.attempt_reads import StoreUnavailable
from taskloop.attempt_types import AttemptKey
from taskloop.check_store import ChecksRow
from taskloop.land_conflict import models
from taskloop.land_conflict.admit import EXPLANATIONS, Ports, admit
from taskloop.land_conflict.models import AdmissionRefused, Outcome, Record, Request
from taskloop.land_conflict.store import ConflictStore
from taskloop.merge.models import Completed, Result, Terminal
from taskloop.operations import Failed, deadline_after


def request_for(source: AttemptKey, checks: ChecksRow, target: str, deadline: float) -> Request:
    return Request(source=source, checks=checks.key, repo_id=checks.repo_id, backlog=checks.backlog,
                   task_id=checks.task_id, tracker_root=checks.tracker_root, checked=checks.commit,
                   target=target, deadline=deadline)


def refused(outcome: Outcome) -> Failed:
    kind = "unavailable" if outcome in (Outcome.NO_SLOT, Outcome.UNAVAILABLE, Outcome.LANDING) else "refused"
    return Failed(kind, outcome.value if kind == "unavailable" else "conflict", EXPLANATIONS[outcome])


def stopped(result: Result) -> Failed:
    if isinstance(result, Completed):
        return Failed("refused", "conflict", f"{result.explanation} The resolution is retained for review; "
                      "the checked input is unchanged. Delivery has stopped without validation, push or task completion.")
    if isinstance(result, Terminal):
        return Failed("refused", "conflict", result.explanation)
    return Failed("unavailable", result.reason.value, result.explanation)


@dataclass(frozen=True)
class Handoff:
    store: ConflictStore
    admission: Callable[[Repo], Ports]
    execution: Callable[[Repo, Record], Result]

    def resume(self, repo: Repo, source: AttemptKey, checks: ChecksRow) -> Failed | None:
        # find matches checked identities only; target and deadline come exclusively from the retained record.
        try:
            record = self.store.find(request_for(source, checks, checks.commit, 0.0))
        except AdmissionRefused as error:
            return refused(error.outcome)
        except (StoreUnavailable, ValueError):
            return refused(Outcome.UNAVAILABLE)
        return None if record is None else stopped(self.execution(repo, record))

    def start(self, repo: Repo, request: Request) -> Failed:
        found = admit(self.admission(repo), request)
        match found:
            case models.Result(record=Record() as record):
                return stopped(self.execution(repo, record))
        return refused(found.outcome)

    def conflicted(self, repo: Repo, request: Request, minutes: int | None, no_change: bool,
                   clock: Callable[[], float]) -> Failed:
        if no_change:
            return Failed("refused", "conflict", "The checked changes conflict with main; no completion was recorded.")
        if minutes is None:
            return Failed("refused", "minutes", "Conflict resolution needs a time limit; no conflict work was admitted.")
        return self.start(repo, request.model_copy(update={"deadline": deadline_after(minutes, clock)}))
