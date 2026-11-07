"""Compose the stage-owned restart sections and checkpoint hooks at the run root."""
from collections.abc import Callable, Sequence

from tlkernel.checkpoint import RunState
from tlwork.plan import restart as plan

from taskloop.app.land import section as land


class RestartSections(plan.Kept, land.Kept):
    """The sum of the stage-owned restart fields."""


def restarted(state: RunState) -> RunState:
    """Build a fresh attempt from each stage's restart section."""
    kept: RestartSections = {**plan.keep(state), **land.keep(state)}
    return RunState(**kept)


def checkpoint_hooks(state: Callable[[], RunState]) -> Sequence[Callable[[str, str], tuple[str, str]]]:
    """Bind the stage-owned save hooks to the run's current state."""
    return (lambda step, feedback: land.pin_validation(state(), step, feedback),)
