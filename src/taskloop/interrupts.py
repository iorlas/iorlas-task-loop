"""The rounds process's own Ctrl-C: the only signal use in factory source (CLAUDE.md, `.importlinter` one-signal-owner).

While `tl plan rounds` runs, a SIGINT handler sets a flag (`stopping`), puts the previous disposition back (Python's
`default_int_handler` in a terminal, so the next press is the ordinary `KeyboardInterrupt`: the abrupt stop) and says one
line; on exit the previous disposition is restored. A process started with SIGINT ignored (`SIG_IGN`) keeps it ignored:
nothing is installed and Ctrl-C is not re-enabled. SIGINT only, this process only: it sends no signal and controls no
other process. Tests never install it.
"""

import signal
from collections.abc import Callable, Generator
from contextlib import contextmanager
from types import FrameType
from typing import Final

NOTICE: Final = "Stopping after the current move; Ctrl-C again to exit at once."


class Interrupts:
    """The graceful stop's flag. `press` is the first Ctrl-C: the flag, the default handler back, the notice once."""

    def __init__(self, say: Callable[[str], object], restore: Callable[[], object]) -> None:
        self.say, self.restore = say, restore
        self.pressed = False

    def stopping(self) -> bool:
        return self.pressed

    def press(self) -> None:
        if self.pressed:
            return
        self.pressed = True
        self.restore()
        self.say(NOTICE)


@contextmanager
def installed(say: Callable[[str], object]) -> Generator[Interrupts]:
    """The handler for the block's life (main thread only); the previous disposition back when it ends, raised or not
    (`default_int_handler` when Python cannot name it)."""
    found = signal.getsignal(signal.SIGINT)
    previous = signal.default_int_handler if found is None else found

    def restore() -> None:
        signal.signal(signal.SIGINT, previous)

    interrupts = Interrupts(say, restore)
    if previous == signal.SIG_IGN:
        yield interrupts
        return

    def pressed(_number: int, _frame: FrameType | None) -> None:
        interrupts.press()

    signal.signal(signal.SIGINT, pressed)
    try:
        yield interrupts
    finally:
        restore()
