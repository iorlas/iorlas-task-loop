"""The graceful stop's flag (`interrupts.Interrupts`), pressed directly: no test installs a handler or sends a signal
(`installed` is covered by the policy rule and the live Run H only)."""

import pytest

from taskloop.interrupts import NOTICE, Interrupts, terminated


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


def test_sigterm_and_sighup_share_one_handler_that_is_the_abrupt_stop() -> None:
    """`installed` registers `terminated` for both; calling it is the second Ctrl-C's exception (no handler is installed)."""
    with pytest.raises(KeyboardInterrupt):
        terminated(1, None)
