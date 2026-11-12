"""The rounds process's own Ctrl-C and SIGTERM: the only signal use in factory source (CLAUDE.md, `.importlinter`
one-signal-owner).

While `tl step rounds` runs, a SIGINT handler sets a flag (`stopping`), puts the previous disposition back (Python's
`default_int_handler` in a terminal, so the next press is the ordinary `KeyboardInterrupt`: the abrupt stop) and says one
line; on exit the previous disposition is restored. A process started with SIGINT ignored (`SIG_IGN`: `nohup`, `&`, an
agent's background shell) keeps it ignored and says so once (`IGNORED`). SIGTERM is the abrupt stop in every case: it
raises `KeyboardInterrupt`, so rounds write their `rounds stopped abrupt` line. This process only: it sends no signal and
controls no other process. Tests never install it.
"""

import signal
from collections.abc import Callable, Generator
from contextlib import contextmanager
from types import FrameType
from typing import Final

NOTICE: Final = "Stopping after the current move; Ctrl-C again to exit at once."
IGNORED: Final = "Ctrl-C is ignored in this process (started with SIGINT ignored); only SIGTERM stops these rounds, abruptly."


class Interrupts:
    """The graceful stop's flag. `press` is the first Ctrl-C: the flag, the default handler back, the notice once."""

    def __init__(self, say: Callable[[str], object], restore: Callable[[], object], ignored: bool = False) -> None:
        self.say, self.restore, self.ignored = say, restore, ignored
        self.pressed = False

    def stopping(self) -> bool:
        return self.pressed

    def press(self) -> None:
        if self.pressed:
            return
        self.pressed = True
        self.restore()
        self.say(NOTICE)


def terminated(_number: int, _frame: FrameType | None) -> None:
    """SIGTERM is the abrupt stop: the same exception as the second Ctrl-C."""
    raise KeyboardInterrupt


@contextmanager
def installed(say: Callable[[str], object]) -> Generator[Interrupts]:
    """The handlers for the block's life (main thread only); the previous dispositions back when it ends, raised or not
    (`default_int_handler` when Python cannot name SIGINT's)."""
    found = signal.getsignal(signal.SIGINT)
    previous = signal.default_int_handler if found is None else found
    term = signal.signal(signal.SIGTERM, terminated)

    def restore() -> None:
        signal.signal(signal.SIGINT, previous)

    interrupts = Interrupts(say, restore, previous == signal.SIG_IGN)

    def pressed(_number: int, _frame: FrameType | None) -> None:
        interrupts.press()

    try:
        if previous == signal.SIG_IGN:
            say(IGNORED)
            yield interrupts
        else:
            signal.signal(signal.SIGINT, pressed)
            yield interrupts
    finally:
        restore()
        signal.signal(signal.SIGTERM, signal.SIG_DFL if term is None else term)
