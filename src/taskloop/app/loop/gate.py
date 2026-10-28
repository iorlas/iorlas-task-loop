"""What a paused bead waits for (tl-7y6.2.8): its role, not a clock. delegate's role view says usable True (wake), False (keep
waiting) or None (unknown: wake once the bead has waited `unknown` seconds). The bead's own retry_after is a hint and never
blocks. The view is cached `cache` seconds. Loop-local: nothing is written to a bead, a label or a file by this class; the held
beads travel only in the loop's own state across a move to a newer install."""
from collections.abc import Callable


class GateRole:
    def __init__(self, roles: Callable[[], dict[str, bool | None] | None], now: Callable[[], float], cache: float = 30,
                 unknown: float = 900) -> None:
        self.roles, self.now, self.cache, self.unknown = roles, now, cache, unknown
        self.held: dict[str, tuple[str, float]] = {}  # bead -> (role, since)
        self.seen: tuple[float | None, dict[str, bool | None]] = (None, {})

    def hold(self, bead: str, role: str) -> None:
        self.held[bead] = (role, self.now())

    def view(self) -> dict[str, bool | None]:
        t = self.now()
        if self.seen[0] is None or t - self.seen[0] >= self.cache:
            self.seen = (t, self.roles() or {})
        return self.seen[1]

    def usable(self, role: str) -> bool | None:
        """True, False or None (delegate does not say)."""
        return self.view().get(role)

    def ready(self, bead: str) -> bool:
        """True when `bead` is not held, or its role is usable now, or its role has been unknown long enough."""
        if bead not in self.held:
            return True
        role, since = self.held[bead]
        u = self.usable(role)
        if u is True or (u is None and self.now() - since >= self.unknown):
            del self.held[bead]
            return True
        return False

    def next_look(self, bead: str) -> float:
        """When `bead` is worth asking about again (epoch)."""
        role, since = self.held[bead]
        t = (self.seen[0] or self.now()) + self.cache
        return min(t, since + self.unknown) if self.usable(role) is None else t
