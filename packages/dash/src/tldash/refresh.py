"""Single-flight resources: serve the last finished value while one background refresh runs. A refresh older than the deadline is
abandoned (a hung source must not freeze the value forever): the next read starts a new one, and the abandoned one's late result is
dropped."""

import logging
import threading
from collections.abc import Callable


class RefreshCache[T]:
    def __init__(self, clock: Callable[[], float], deadline: float = 60.0) -> None:
        self.clock, self.deadline = clock, deadline
        self.condition = threading.Condition()
        self.items: dict[str, tuple[float, T]] = {}
        self.running: dict[str, tuple[float, object]] = {}  # key -> (started, token) of the build that owns the key

    def peek(self, key: str) -> T | None:
        with self.condition:
            hit = self.items.get(key)
            return hit[1] if hit else None

    def get(self, key: str, ttl: float, make: Callable[[], T]) -> T:
        with self.condition:
            while key not in self.items and self._busy(key):
                self.condition.wait(1.0)  # woken by a finished build; the timeout re-checks the deadline
            hit = self.items.get(key)
            if hit and (self._busy(key) or self.clock() - hit[0] < ttl):
                return hit[1]
            token = self._claim(key)
            if hit:
                try:
                    threading.Thread(target=self._background, args=(key, make, token), daemon=True).start()
                except RuntimeError:
                    self._release(key, token)
                    raise
                return hit[1]
        return self._build(key, make, token)

    def _busy(self, key: str) -> bool:
        """A refresh of the key is in flight and inside its deadline."""
        owner = self.running.get(key)
        return owner is not None and self.clock() - owner[0] < self.deadline

    def _claim(self, key: str) -> object:
        token = object()
        self.running[key] = (self.clock(), token)
        return token

    def _release(self, key: str, token: object) -> None:
        if self.running.get(key, (0.0, None))[1] is token:
            del self.running[key]
        self.condition.notify_all()

    def _build(self, key: str, make: Callable[[], T], token: object) -> T:
        try:
            value = make()
            with self.condition:
                if self.running.get(key, (0.0, None))[1] is token:  # an abandoned build's late value never replaces a newer one
                    self.items[key] = (self.clock(), value)
            return value
        finally:
            with self.condition:
                self._release(key, token)

    def _background(self, key: str, make: Callable[[], T], token: object) -> None:
        try:
            self._build(key, make, token)
        except Exception:
            logging.getLogger(__name__).exception("dashboard refresh failed: %s", key)

    def wait(self) -> None:
        """Drain in-flight builds for shutdown, profiling, and deterministic tests."""
        with self.condition:
            self.condition.wait_for(lambda: not self.running)
