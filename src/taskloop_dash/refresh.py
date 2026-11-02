"""Single-flight resources: serve the last finished value while one background refresh runs."""

import logging
import threading
from collections.abc import Callable


class RefreshCache[T]:
    def __init__(self, clock: Callable[[], float]) -> None:
        self.clock = clock
        self.condition = threading.Condition()
        self.items: dict[str, tuple[float, T]] = {}
        self.running: set[str] = set()

    def peek(self, key: str) -> T | None:
        with self.condition:
            hit = self.items.get(key)
            return hit[1] if hit else None

    def get(self, key: str, ttl: float, make: Callable[[], T]) -> T:
        with self.condition:
            while key in self.running and key not in self.items:
                self.condition.wait()
            hit = self.items.get(key)
            if hit and (key in self.running or self.clock() - hit[0] < ttl):
                return hit[1]
            self.running.add(key)
            if hit:
                try:
                    threading.Thread(target=self._background, args=(key, make), daemon=True).start()
                except RuntimeError:
                    self.running.remove(key)
                    self.condition.notify_all()
                    raise
                return hit[1]
        return self._build(key, make)

    def _build(self, key: str, make: Callable[[], T]) -> T:
        try:
            value = make()
            with self.condition:
                self.items[key] = (self.clock(), value)
            return value
        finally:
            with self.condition:
                self.running.remove(key)
                self.condition.notify_all()

    def _background(self, key: str, make: Callable[[], T]) -> None:
        try:
            self._build(key, make)
        except Exception:
            logging.getLogger(__name__).exception("dashboard refresh failed: %s", key)

    def wait(self) -> None:
        """Drain in-flight builds for shutdown, profiling, and deterministic tests."""
        with self.condition:
            self.condition.wait_for(lambda: not self.running)
