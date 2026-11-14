"""Frozen checkout and result evidence for releasing saved conflict work."""

from enum import StrEnum
from typing import Self

from pydantic import model_validator

from taskloop.land_conflict.abort_models import Checkout, Value
from taskloop.merge.models import Phase, Terminal, Work


class ReleasePhase(StrEnum):
    PENDING = "pending"
    COMPLETE = "complete"


class Release(Value):
    work: Work
    before: Checkout
    after: Checkout
    result: Terminal
    phase: ReleasePhase = ReleasePhase.PENDING

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if (self.work.phase is not Phase.TERMINAL or self.result.reason != self.work.reason
                or self.result.explanation != self.work.explanation):
            raise ValueError("release requires the exact terminal work and result")
        for checkout in (self.before, self.after):
            if (checkout.repo_id, checkout.root, checkout.path, checkout.gitdir) != (
                    self.work.repo_id, self.work.root, self.work.slot, self.work.gitdir):
                raise ValueError("release checkouts must retain the reserved work identity")
            if checkout.branch is not None or checkout.merging or checkout.merge_head is not None or checkout.index:
                raise ValueError("release requires clean detached checkout expectations")
        if self.after.head != self.work.base:
            raise ValueError("release must park at the admitted base")
        return self
