"""Reconcile recorded external actions by asking their owning adapters; never start another attempt or land."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from git_porcelain import GitUnavailable

from taskloop.admit import Tasks
from taskloop.attempt_reads import StoreRefused
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import Checkouts
from taskloop.drain.models import Action, ActionKind
from taskloop.land_push import Origin, reconcile_delivery
from taskloop.land_store import LandStore
from taskloop.task import TaskInspectionError


@dataclass(frozen=True)
class Reconcile:
    attempts: AttemptStore
    lands: LandStore
    remotes: Checkouts
    tasks: Tasks
    return_claim: Callable[[Action], bool]
    clock: Callable[[], float]

    def __call__(self, action: Action) -> bool:
        if action.kind is ActionKind.DISPATCH:
            # A dead launcher cannot register again. The handshake permits only a persisted entry,
            # observed independently by the execution readers, including entries of concluded attempts.
            return True
        if action.kind is ActionKind.CLAIM:
            rows = self.attempts.attempts(action.backlog, action.subject)
            adopted = rows and (rows[0].release is None or rows[0].release.claim not in {"unclaimed", "not_held"})
            return bool(adopted) or self.return_claim(action)
        if action.kind is ActionKind.LAND:
            return self._land(action)
        return False

    def _land(self, action: Action) -> bool:
        rows = self.lands.for_task(action.backlog, action.subject)
        if not rows:
            return True  # no candidate: no delivery or close could have started
        if not action.checkout:
            return False
        try:
            origin = Origin(self.remotes(Path(action.checkout)), Path(action.checkout))
            for row in rows:
                if origin.repo.identity().key != row.repo_id:
                    return False
                if not reconcile_delivery(self.lands, origin, row, self.clock()):
                    return False
                found = self.lands.row(row.key)
                if found is not None and found.delivery is not None and found.close is None:
                    task = self.tasks(found.task_id, found.backlog, found.tracker_root)
                    if task.status == "closed":
                        self.lands.record_close(found.key, "already_closed", self.clock())
            return True
        except GitUnavailable, TaskInspectionError, StoreRefused:
            return False
