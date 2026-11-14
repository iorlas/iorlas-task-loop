"""Ordinary land consumes verified, durably released conflict completion."""

from collections.abc import Callable
from dataclasses import dataclass

from git_porcelain import GitUnavailable, MissingRevision, Repo

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
        return Failed("refused", "conflict", "The resolution has no matching durable accepted release; delivery stopped.")
    if isinstance(result, Terminal):
        return Failed("refused", "conflict", result.explanation)
    return Failed("unavailable", result.reason.value, result.explanation)


@dataclass(frozen=True)
class Handoff:
    store: ConflictStore
    admission: Callable[[Repo], Ports]
    execution: Callable[[Repo, Record], Result]

    def _result(self, repo: Repo, record: Record) -> Completed | Failed:
        try:
            saved = self.store.completed(record.key)
            result = saved.release.result if saved is not None and saved.release is not None else self.execution(repo, record)
            if not isinstance(result, Completed):
                return stopped(result)
            saved = self.store.completed(record.key)
            if (saved is None or not saved.accepted or saved.release is None or saved.release.result != result
                    or (saved.source, saved.target, saved.commit) != (result.source, result.target, result.commit)
                    or (result.source, result.target) != (record.request.checked, record.request.target)
                    or saved.repo_id != record.request.repo_id):
                return stopped(result)
            tip = next((ref.sha for ref in repo.refs([saved.ref]) if ref.name == saved.ref), None)
            tree = repo.tree(result.commit)
            if tip != result.commit or tree is None or str(tree.sha) != result.commit:
                return Failed("refused", "conflict", "The retained resolution's ref or commit is missing or changed; delivery stopped.")
            return result
        except (StoreUnavailable, GitUnavailable, MissingRevision, ValueError):
            return Failed("unavailable", "conflict", "The retained resolution evidence cannot be verified; delivery stopped.")

    def resume(self, repo: Repo, source: AttemptKey, checks: ChecksRow) -> Completed | Failed | None:
        # find matches checked identities only; target and deadline come exclusively from the retained record.
        try:
            record = self.store.find(request_for(source, checks, checks.commit, 0.0))
        except AdmissionRefused as error:
            return refused(error.outcome)
        except (StoreUnavailable, ValueError):
            return refused(Outcome.UNAVAILABLE)
        return None if record is None else self._result(repo, record)

    def start(self, repo: Repo, request: Request) -> Completed | Failed:
        found = admit(self.admission(repo), request)
        match found:
            case models.Result(record=Record() as record):
                return self._result(repo, record)
            case models.Result():
                return refused(found.outcome)

    def conflicted(self, repo: Repo, request: Request, minutes: int | None, no_change: bool,
                   clock: Callable[[], float]) -> Completed | Failed:
        if no_change:
            return Failed("refused", "conflict", "The checked changes conflict with main; no completion was recorded.")
        if minutes is None:
            return Failed("refused", "minutes", "Conflict resolution needs a time limit; no conflict work was admitted.")
        return self.start(repo, request.model_copy(update={"deadline": deadline_after(minutes, clock)}))
