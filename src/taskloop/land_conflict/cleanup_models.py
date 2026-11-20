"""Frozen checkout expectations for cleanup of completely retained work."""

from enum import StrEnum
from typing import Self

from pydantic import model_validator

from taskloop.land_conflict.abort_models import Checkout, Value
from taskloop.merge.models import Work


class CleanupPhase(StrEnum):
    EXCLUDE = "exclude"
    PARK = "park"
    COMPLETE = "complete"


class Cleanup(Value):
    work: Work
    before: Checkout
    restored: Checkout
    after: Checkout
    ignored: dict[str, tuple[str, str]]
    phase: CleanupPhase = CleanupPhase.EXCLUDE

    @model_validator(mode="after")
    def consistent(self) -> Self:
        for checkout in (self.before, self.restored, self.after):
            if (checkout.repo_id, checkout.root, checkout.path, checkout.gitdir) != (
                    self.work.repo_id, self.work.root, self.work.slot, self.work.gitdir):
                raise ValueError("cleanup checkouts must retain the reserved work identity")
        if (self.restored.branch is not None or self.restored.merging or self.restored.merge_head is not None or self.restored.index
                or self.restored.model_dump(exclude={"files"}) != self.after.model_dump(exclude={"files"})):
            raise ValueError("cleanup results require the same clean detached HEAD")
        if (not self.ignored.items() <= self.before.files.items()
                or not self.ignored.items() <= self.after.files.items()
                or not self.after.files.items() <= self.restored.files.items()):
            raise ValueError("cleanup must retain every frozen ignored identity")
        return self


def transition(previous: Cleanup | None, updated: Cleanup | None) -> bool:
    if previous is None:
        return updated is not None and updated.phase is CleanupPhase.EXCLUDE
    progress = {CleanupPhase.EXCLUDE: CleanupPhase.PARK, CleanupPhase.PARK: CleanupPhase.COMPLETE}
    return (updated is not None and progress.get(previous.phase) is updated.phase
            and previous.model_dump(exclude={"phase"}) == updated.model_dump(exclude={"phase"}))
