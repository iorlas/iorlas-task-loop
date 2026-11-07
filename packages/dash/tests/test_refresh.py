"""RefreshCache: a refresh that outlives its deadline is abandoned for a new one; the late result never replaces a newer build."""

import threading

from tldash.refresh import RefreshCache


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_a_hung_background_refresh_is_replaced_after_its_deadline_and_its_late_result_is_dropped():
    clock, hang, entered = Clock(), threading.Event(), threading.Event()
    cache: RefreshCache[str] = RefreshCache(clock, deadline=30.0)
    assert cache.get("k", 3.0, lambda: "first") == "first"

    def hung() -> str:
        entered.set()
        hang.wait(5)
        return "late"

    clock.now = 10
    assert cache.get("k", 3.0, hung) == "first"  # stale: served at once while the refresh hangs
    assert entered.wait(2)
    clock.now = 20
    assert cache.get("k", 3.0, lambda: "never") == "first"  # still inside the deadline: no second refresh
    clock.now = 45
    assert cache.get("k", 3.0, lambda: "second") == "first"  # overdue: a new refresh starts, the stale value still answers
    with cache.condition:
        assert cache.condition.wait_for(lambda: cache.items["k"][1] == "second", 2)
    hang.set()  # the abandoned refresh finishes late
    cache.wait()
    assert cache.peek("k") == "second"
    clock.now = 46
    assert cache.get("k", 3.0, lambda: "unused") == "second"


def test_a_first_build_that_hangs_past_its_deadline_does_not_block_the_next_reader_forever():
    clock, release = Clock(), threading.Event()
    cache: RefreshCache[str] = RefreshCache(clock, deadline=30.0)
    first = threading.Thread(target=lambda: cache.get("k", 3.0, lambda: (release.wait(5), "late")[1]), daemon=True)
    first.start()
    with cache.condition:
        assert cache.condition.wait_for(lambda: "k" in cache.running, 2)
    clock.now = 100
    assert cache.get("k", 3.0, lambda: "fresh") == "fresh"
    release.set()
    first.join(2)
    assert cache.peek("k") == "fresh"
