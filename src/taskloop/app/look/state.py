"""What the look stage keeps between its steps. The five checkpointed fields are the run state's (a view, so the checkpoint on disk is
the one it always was); the rest is the stage's own and is not saved."""
from collections.abc import Callable

from tlkernel.checkpoint import RunState
from tlkernel.looks import Methods
from tlkernel.wire import Open

LOOK_FIELDS = ("look_notes", "look_unjudged", "look_done", "rendered_names", "last_reqs")  # RunState fields the look stage owns


class LookState:
    """`run` returns the engine's current RunState (it is replaced when a task starts again)."""

    def __init__(self, run: Callable[[], RunState]) -> None:
        self._run = run
        self.filed = False  # the owner-look bead was filed
        self.retried: set[str] = set()  # items the judge asked again
        self.skipped: set[str] = set()  # shots the table named that could not be rendered
        self.shot_cache: Methods | None = None  # the vendor methods of the shot table, once read

    @property
    def notes(self) -> list[str]:
        """The judge's last round, for the owner-look bead."""
        return self._run().look_notes

    @notes.setter
    def notes(self, value: list[str]) -> None:
        self._run().look_notes = value

    @property
    def unjudged(self) -> dict[str, str]:
        """What could not be judged: item -> why."""
        return self._run().look_unjudged

    @unjudged.setter
    def unjudged(self, value: dict[str, str]) -> None:
        self._run().look_unjudged = value

    @property
    def done(self) -> int:
        """Judge rounds so far in this stage."""
        return self._run().look_done

    @done.setter
    def done(self, value: int) -> None:
        self._run().look_done = value

    @property
    def rendered(self) -> list[str]:
        """Sorted: the pictures rendered so far."""
        return self._run().rendered_names

    @rendered.setter
    def rendered(self, value: list[str]) -> None:
        self._run().rendered_names = value

    @property
    def last_reqs(self) -> list[Open]:
        return self._run().last_reqs

    @last_reqs.setter
    def last_reqs(self, value: list[Open]) -> None:
        self._run().last_reqs = value
