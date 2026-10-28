"""Budget: what a run may spend (dollars, and minutes of its own time) and what it has. Time spent waiting for a shared resource
(a Unity slot, a lane, an editor lock) is booked as waited and is not the run's minutes."""
import dataclasses
from collections.abc import Callable

from taskloop.contracts.config import EngineConfig


@dataclasses.dataclass
class Budget:
    cfg: EngineConfig  # the run's config: budget_usd, budget_min, budget_min_by_label
    now: Callable[[], float]
    t0: float = 0.0
    waited: float = 0.0
    spent: float = 0.0
    labels: list[str] = dataclasses.field(default_factory=list)

    def __post_init__(self) -> None:
        self.t0 = self.t0 or self.now()

    def limit_min(self) -> float:
        """budget_min, or the largest budget_min_by_label of this bead's labels."""
        by = self.cfg.budget_min_by_label
        return max([float(self.cfg.budget_min)] + [float(by[x]) for x in self.labels if x in by])

    def spent_min(self) -> float:
        """Minutes against the budget: wall clock without the time spent waiting for a shared resource."""
        return (self.now() - self.t0 - self.waited) / 60

    def wall_min(self) -> float:
        return (self.now() - self.t0) / 60

    def charge(self, usd: float) -> None:
        self.spent += usd

    def wait(self, secs: float) -> float:
        """Book `secs` of waiting (never more than the wall time there is); returns what was booked."""
        secs = min(secs, self.now() - self.t0 - self.waited)
        if secs > 0:
            self.waited += secs
        return max(secs, 0.0)

    def used(self) -> float:
        """The larger share used, of the dollars and of the minutes (1.0 = all)."""
        return max(self.spent / float(self.cfg.budget_usd), self.spent_min() / self.limit_min())

    def over(self) -> list[str]:
        """What is past its cap, one phrase each ('181 of 180 min', '$16.00 of $15'); empty while inside."""
        mins, limit, usd = self.spent_min(), self.limit_min(), self.cfg.budget_usd
        return (["%d of %g min" % (mins, limit)] if mins > limit else []) + (["$%.2f of $%s" % (self.spent, usd)] if self.spent > float(usd) else [])
