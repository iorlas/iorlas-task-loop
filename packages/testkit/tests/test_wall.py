"""The wall watchdog is inert in worker threads."""
import threading

from tltestkit.wall import wall_guard


def test_off_main_thread_is_a_noop():
    finished = threading.Event()

    def run():
        with wall_guard(0.01, "thread"):
            threading.Event().wait(0.05)
        finished.set()

    thread = threading.Thread(target=run)
    thread.start()
    thread.join(1)
    assert finished.is_set()
    assert not thread.is_alive()
