"""The Agent: one worker call the engine started and may only wait for or stop (docs/design/isolation.md, step A1).

The engine holds an `Agent` and nothing of the harness or the process under it: no Handle, no pid. `stop` is the only way to end it."""
from typing import Any, Protocol


class Agent(Protocol):
    def done(self, timeout: float) -> bool:
        """Wait up to `timeout` seconds; True once the call has ended (answered or stopped)."""
        ...

    def result(self) -> dict[str, Any]:
        """The answer object (contract 4 wire form) of a call that ended by itself; ValueError when there is none."""
        ...

    def stop(self) -> list[int]:
        """End the call and its tree, then wait for the call to hand back. -> the pids that outlived it (empty: proven dead)."""
        ...
