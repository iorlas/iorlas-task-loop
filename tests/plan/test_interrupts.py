"""The graceful stop's flag (`interrupts.Interrupts`), pressed directly: no test installs a handler or sends a signal
(`installed` is covered by the policy rule and the live Run H only)."""

from taskloop.interrupts import NOTICE, Interrupts


def test_the_first_press_sets_the_flag_restores_the_default_and_says_the_notice_once() -> None:
    said: list[str] = []
    restored: list[bool] = []
    interrupts = Interrupts(said.append, lambda: restored.append(True))
    assert interrupts.stopping() is False and said == restored == []
    interrupts.press()
    assert interrupts.stopping() is True and said == [NOTICE] and restored == [True]
    interrupts.press()  # were a second press ever to reach it: nothing again
    assert said == [NOTICE] and restored == [True]
    assert NOTICE == "Stopping after the current move; Ctrl-C again to exit at once."
