"""ThreadFlag: a bool attribute that each thread has its own copy of, False until the thread sets it.

The engine's `killed` and `wall_hit` say how the last command of the calling thread ended; with the lanes of a gate (several checks
running at once) one shared value would be the answer of whichever lane wrote last."""
import threading


class ThreadFlag:
    def __set_name__(self, owner: type, name: str) -> None:
        self.slot = "_threadflag_" + name

    def __get__(self, obj: object, owner: type | None = None) -> bool:
        return bool(getattr(self._local(obj), "value", False))

    def __set__(self, obj: object, value: bool) -> None:
        self._local(obj).value = value

    def _local(self, obj: object) -> threading.local:
        seen = vars(obj)
        found = seen.get(self.slot)
        if found is None:
            found = seen.setdefault(self.slot, threading.local())
        return found
