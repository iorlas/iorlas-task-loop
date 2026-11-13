"""The backlog's tasks in flight (`round.run_round`'s `max_running` bound)."""

from collections.abc import Iterable
from typing import Final

from taskloop.attempt_status import AttemptView

IN_FLIGHT: Final = frozenset({"start", "wait", "verify", "repeat", "release", "publish", "advance", "land"})


def in_flight(current: Iterable[AttemptView]) -> frozenset[str]:
    """The backlog's tasks with work that goes on without the person: a step starting, running, verified, repeated,
    released, published or advanced, or a passed task waiting to be landed (counted until landed). Failed (`done`),
    `repeats_exhausted`, `stuck:*`, `unknown`, held, landed and abandoned ones need the person: not counted."""
    return frozenset(e.task_id for e in current if e.next in IN_FLIGHT and not (e.release is not None and e.release.abandoned))
