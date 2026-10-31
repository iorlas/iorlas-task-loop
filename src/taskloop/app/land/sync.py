"""What follows the push: a plan of effects (the landed fact, then bd's data; a failure of the second blocks the bead), applied once each
by key under this run's id."""
from functools import cached_property
from typing import Protocol, assert_never

from taskloop.contracts.ids import BeadId
from taskloop.domain import effects
from taskloop.domain.interpret import CheckpointLedger, interpret


class SyncCheckpoints(Protocol):
    def applied(self) -> frozenset[str]: ...
    def mark_applied(self, key: str) -> None: ...


class BdSync(Protocol):
    def bd_sync(self, sha: str) -> None: ...


class SyncHost(Protocol):
    """What the after-steps read of the engine: the bead, the run's id (its log path), the dry flag, the ledger in the checkpoint and the
    landed record."""

    @property
    def bead(self) -> BeadId: ...
    @property
    def dry(self) -> bool: ...
    @property
    def run_id(self) -> str: ...
    @property
    def checkpoints(self) -> SyncCheckpoints: ...
    def record_land(self, sha: str) -> None: ...


class Sync:
    def __init__(self, host: SyncHost, out: BdSync) -> None:
        self.e = host
        self.out = out

    @cached_property
    def ledger(self) -> CheckpointLedger:
        return CheckpointLedger(self.e.checkpoints)

    def run(self, sha: str) -> str:
        """The land is done and the lock is let go. -> sha."""
        e = self.e
        if sha and not e.dry:
            interpret(e.bead, e.run_id, effects.plan_land(sha), self.ledger, self.apply)
        return sha

    def apply(self, eff: effects.LandEffect) -> None:
        match eff:
            case effects.RecordLand():
                self.e.record_land(eff.sha)
            case effects.BdSync():
                self.out.bd_sync(eff.sha)
            case _:
                assert_never(eff)
