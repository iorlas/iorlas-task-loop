"""A nested phase stopwatch: one phase owns each instant, totals add up to wall time."""

from any_clock.clock import PhaseClock

__all__ = ["PhaseClock"]
