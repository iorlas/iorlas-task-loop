"""Budget: what a run may spend (dollars, and minutes of its own time) and what it has. Time spent waiting for a shared resource
(a Unity slot, a lane, an editor lock) is booked as waited and is not the run's minutes."""

import dataclasses
from collections.abc import Callable

from any_clock import PhaseClock

from tlkernel.config import EngineConfig

WAIT = "wait"  # the clock's phase for time spent waiting for a shared resource: exempt from the minutes


@dataclasses.dataclass
class Budget:
    cfg: EngineConfig  # the run's config: budget_usd, budget_min, budget_min_by_label
    now: Callable[[], float]
    spent: float = 0.0
    labels: list[str] = dataclasses.field(default_factory=list)

    def __post_init__(self) -> None:
        self.restore(0.0, 0.0)

    def restore(self, elapsed: float, waited: float) -> None:
        """The run's clock as it stood: `elapsed` seconds old, `waited` of them spent waiting (a run that exec'd or paused)."""
        self.clock = PhaseClock(self.now, exempt=(WAIT,), elapsed=elapsed)
        self.clock.book(WAIT, waited)

    @property
    def t0(self) -> float:
        return self.clock.started

    @property
    def waited(self) -> float:
        return self.clock.total(WAIT)

    def limit_min(self) -> float:
        """budget_min, or the largest budget_min_by_label of this bead's labels."""
        by = self.cfg.budget_min_by_label
        return max([float(self.cfg.budget_min)] + [float(by[x]) for x in self.labels if x in by])

    def spent_min(self) -> float:
        """Minutes against the budget: wall clock without the time spent waiting for a shared resource."""
        return self.clock.charged() / 60

    def wall_min(self) -> float:
        return self.clock.wall() / 60

    def charge(self, usd: float) -> None:
        self.spent += usd

    def wait(self, secs: float) -> float:
        """Book `secs` of waiting (never more than the wall time there is); returns what was booked."""
        return self.clock.book(WAIT, secs)
    def used(self) -> float:
        """The larger share used, of the dollars and of the minutes (1.0 = all)."""
        return max(self.spent / float(self.cfg.budget_usd), self.spent_min() / self.limit_min())

    def over(self) -> list[str]:
        """What is past its cap, one phrase each ('181 of 180 min', '$16.00 of $15'); empty while inside."""
        mins, limit, usd = self.spent_min(), self.limit_min(), self.cfg.budget_usd
        return ([f"{int(mins)} of {limit:g} min"] if mins > limit else []) + (
            [f"${self.spent:.2f} of ${usd}"] if self.spent > float(usd) else []
        )
