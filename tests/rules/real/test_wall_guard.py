"""Exercise real alarms in children so the gate's own watchdog stays intact."""
import os
import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX timers")


def run_guard(source):
    result = subprocess.run([sys.executable, "-c", textwrap.dedent(source)], timeout=5, check=False)
    assert result.returncode == 0


def test_a_stalled_test_fails_with_waiting_stacks(capfd):
    run_guard('''
        import threading
        import time
        from tltestkit.wall import HungTest, wall_guard

        started = time.monotonic()
        try:
            with wall_guard(0.3, 'x'):
                threading.Event().wait(10)
        except HungTest as error:
            assert str(error) == 'x made no progress for 0 s (wall); thread stacks above'
        else:
            raise AssertionError('guard did not interrupt the wait')
        assert time.monotonic() - started < 1
    ''')
    assert 'wait' in capfd.readouterr().err


def test_a_finished_block_cancels_timer_and_restores_handler():
    run_guard('''
        import signal
        from tltestkit.wall import wall_guard

        previous = signal.getsignal(signal.SIGALRM)
        with wall_guard(1, 'quick'):
            assert signal.getitimer(signal.ITIMER_REAL)[0] > 0
        assert signal.getitimer(signal.ITIMER_REAL) == (0, 0)
        assert signal.getsignal(signal.SIGALRM) == previous
    ''')


@pytest.mark.parametrize('occupied', ['timer', 'handler'])
def test_an_existing_alarm_is_left_alone(occupied):
    run_guard(f'''
        import signal
        from tltestkit.wall import wall_guard

        if {occupied!r} == 'timer':
            signal.setitimer(signal.ITIMER_REAL, 4)
        else:
            signal.signal(signal.SIGALRM, lambda *_: None)
        handler = signal.getsignal(signal.SIGALRM)
        before = signal.getitimer(signal.ITIMER_REAL)
        with wall_guard(0.3, 'occupied'):
            assert signal.getsignal(signal.SIGALRM) == handler
        after = signal.getitimer(signal.ITIMER_REAL)
        assert (0 < after[0] <= before[0]) if before[0] else after == before
        signal.setitimer(signal.ITIMER_REAL, 0)
    ''')


def test_backstop_is_armed_and_cancelled_even_when_the_block_raises():
    run_guard('''
        import faulthandler
        import signal
        from unittest.mock import patch
        from tltestkit.wall import wall_guard

        previous = signal.getsignal(signal.SIGALRM)
        with patch.object(faulthandler, 'dump_traceback_later') as arm:
            with patch.object(faulthandler, 'cancel_dump_traceback_later') as cancel:
                try:
                    with wall_guard(2, 'raises'):
                        assert arm.call_args.args == (62,)
                        assert arm.call_args.kwargs['exit'] is True
                        raise RuntimeError('test failure')
                except RuntimeError as error:
                    assert str(error) == 'test failure'
                else:
                    raise AssertionError('test exception was swallowed')
                cancel.assert_called_once_with()
        assert signal.getitimer(signal.ITIMER_REAL) == (0, 0)
        assert signal.getsignal(signal.SIGALRM) == previous
    ''')
