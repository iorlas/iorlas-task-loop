"""Authorize the registered child before its entry receives permission to execute."""

from taskloop.attempt_types import AttemptKey
from taskloop.drain.models import Identity
from taskloop.recovery.models import Result
from taskloop.recovery.recover import Recovery


class RecoveryLaunch:
    def __init__(self, recovery: Recovery) -> None:
        self.recovery = recovery

    def __call__(self, key: AttemptKey, owner: Identity, deadline: float) -> Result:
        # A prior uncertain start stays authoritative until observations prove its owner gone.
        return self.recovery.authorize(key, owner, deadline=deadline)
