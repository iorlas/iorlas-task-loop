"""Commit, check clean, then judge: the one operation that settles a stored valid `planned` or `unchanged` answer.

The entry (once, after the run) and `tl plan verify` run the same operation; running it again finishes a crash at any
step. A stored verdict is returned with no Git read; slot state and every unknown store nothing.
"""

from collections.abc import Callable

from git_porcelain import GitUnavailable

from taskloop.plan import outcome
from taskloop.plan_commit import NotSettled, clean_at, leftovers, settle
from taskloop.plan_store import PlanStore, StoreRefused, StoreUnavailable
from taskloop.plan_types import (
    AttemptKey,
    AttemptRecord,
    Checkouts,
    NotApplicable,
    Rejected,
    SlotFiles,
    StoredExecution,
    Unsettled,
    Verdict,
    VerifyRefused,
    VerifyResult,
    VerifyUnavailable,
)
from taskloop.plan_verify import Unreadable, judge

STAGED = ("planned", "unchanged")  # the answers whose stage the factory commits and checks


def applicable(stored: StoredExecution | None) -> StoredExecution | VerifyResult:
    """The stored execution when a verdict is still to be made; otherwise what `verify` returns, with no Git read."""
    if stored is None:
        return VerifyRefused("not_captured")
    if stored.answer.kind == "validation_pending":
        return VerifyUnavailable("validation_pending")
    if stored.verification is not None:
        return stored.verification
    if outcome(stored) not in STAGED:
        return NotApplicable(outcome(stored))
    if stored.publication != "complete":  # the verdict's writer requires a complete session publication too
        return VerifyRefused("session") if stored.publication == "conflict" else VerifyUnavailable("session_" + stored.publication)
    return stored


class PlanVerifier:
    """Git evidence for a stored valid `planned` or `unchanged` answer: the factory's commit of the listed paths, the
    clean tree at it, then one verdict over immutable facts, stored once and then returned with no Git read."""

    def __init__(self, store: PlanStore, checkouts: Checkouts, files: SlotFiles, clock: Callable[[], float]) -> None:
        self.store, self.checkouts, self.files, self.clock = store, checkouts, files, clock

    def verify(self, key: AttemptKey) -> VerifyResult:
        try:
            return self._verify(key)
        except StoreUnavailable:
            return VerifyUnavailable("store")
        except StoreRefused as error:
            return VerifyRefused(str(error))
        except NotSettled as error:
            return VerifyUnavailable(error.reason)
        except (GitUnavailable, Unreadable) as error:
            return VerifyUnavailable("git:" + type(error).__name__)

    def _verify(self, key: AttemptKey) -> VerifyResult:
        stored = applicable(self.store.collect(key))
        if not isinstance(stored, StoredExecution):
            return stored
        record = self.store.load(key)
        if record is None or record.base_commit is None:
            return VerifyRefused("absent" if record is None else "no_base")
        return self._settle(record, record.base_commit, stored)

    def leftovers(self, key: AttemptKey) -> Unsettled | None:
        """Read-only: the leftovers a verify would report for a stage still to settle, read now; None when there is
        nothing to report or it cannot be read (the person runs `tl plan verify` for the reason)."""
        try:
            stored = applicable(self.store.collect(key))
            record = self.store.load(key)
            if not isinstance(stored, StoredExecution) or record is None or record.base_commit is None:
                return None
            admission = record.admission
            return leftovers(self.checkouts, self.files, admission, record.base_commit, stored.answer, record.plan_commit)
        except (StoreUnavailable, StoreRefused, NotSettled, GitUnavailable, Unreadable):
            return None

    def _settle(self, record: AttemptRecord, base: str, stored: StoredExecution) -> VerifyResult:
        """Outside any transaction: X (stored, adopted or made), then the clean tree at X, then the verdict."""
        admission, answer, commit = record.admission, stored.answer, record.plan_commit
        if commit is None:
            settled = settle(self.checkouts, self.files, admission, base, answer)
            if isinstance(settled, Unsettled):
                return settled
            if isinstance(settled, Rejected):  # nothing_written: no commit to bind
                return self._kept(record, base, None, settled)
            commit = settled.sha if answer.disposition == "unchanged" else self.store.plan_commit(admission, settled.sha)
            if commit != settled.sha:
                return VerifyUnavailable("inconsistent")
        root = clean_at(self.checkouts, self.files, admission, commit)
        if isinstance(root, Unsettled):
            return root
        if record.plan_commit is None and answer.disposition == "unchanged" and self.store.plan_commit(admission, commit) != commit:
            return VerifyUnavailable("inconsistent")
        unchanged = answer.disposition == "unchanged"
        found = judge(self.checkouts(root), root, base, commit, admission.rules, answer.paths, unchanged=unchanged)
        return self._kept(record, base, commit, found)

    def _kept(self, record: AttemptRecord, base: str, commit: str | None, found: Verdict) -> Verdict | VerifyUnavailable:
        kept = self.store.verdict(record.admission, base, commit, found, self.clock())
        return found if kept == found else VerifyUnavailable("inconsistent")  # same inputs, same rules: a defect

