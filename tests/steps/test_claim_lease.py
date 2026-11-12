"""The claim's keep-alive: the loop body driven directly by a scripted stop and scripted beats on a fake clock; one
thread start and stop with a real event that is never waited out."""

import threading

import pytest

from taskloop.claim_lease import BEAT_EVERY_S, LEASE_TTL_S, Beat, ClaimWord, KeepAlive, keeping, renewal


class Stop:
    """`wait` answers False (go on) `rounds` times, then True (stopped); every wait advances the clock by its timeout."""

    def __init__(self, clock: Clock, rounds: int) -> None:
        self.clock, self.rounds, self.waits, self.stopped = clock, rounds, 0, False

    def wait(self, timeout: float) -> bool:
        self.waits += 1
        if self.waits > self.rounds:
            return True
        self.clock.now += timeout
        return False

    def set(self) -> None:
        self.stopped = True


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Beats:
    """Answers the scripted beats in order (the last one repeats); an exception instance is raised. Each beat takes
    `takes` seconds on the clock (a bd call that runs into its timeout takes 30)."""

    def __init__(self, clock: Clock, *script: Beat | Exception, takes: float = 0) -> None:
        self.clock, self.script, self.takes, self.calls = clock, list(script), takes, 0

    def __call__(self) -> Beat:
        answer = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        self.clock.now += self.takes
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.mark.parametrize(
    ("script", "takes", "rounds", "word", "calls"),
    [
        (("held",), 0, 5, "held", 6),
        (("held",), 30, 5, "held", 6),
        (("held", "lost", "held"), 0, 5, "lost", 2),
        (("unrenewed",), 0, 5, "unrenewed", 6),
        (("unrenewed", "held"), 0, 5, "held", 6),
        (("held", "unrenewed", "held"), 0, 5, "held", 6),
        (("held", "unrenewed", "unrenewed", "held"), 0, 5, "unrenewed", 6),
        (("held", "unrenewed", "unrenewed", "held"), 30, 5, "unrenewed", 6),
        (("held", "unrenewed"), 0, 2, "held", 3),
        (("held", TypeError("bug"), "held"), 0, 5, "fault", 2),
        ((TypeError("bug"),), 0, 5, "fault", 1),
    ],
    ids=[
        "all_held", "all_held_slowly", "lost_stops_beating", "never_held", "held_after_one_failure", "one_failure",
        "two_failures_then_held", "two_timeouts_then_held", "stopped_before_the_ttl", "fault", "fault_before_the_agent",
    ],
)
def test_the_first_renewal_then_the_loop_record_one_word(
    script: tuple[Beat | Exception, ...], takes: float, rounds: int, word: ClaimWord, calls: int
) -> None:
    """As the entry does: one renewal, then the loop until stopped. `held` needs one held beat and no possible lapse: two
    failed beats in a row reach the TTL by the next held one (BEAT_EVERY_S is a third of it)."""
    clock = Clock()
    beats, stop = Beats(clock, *script, takes=takes), Stop(clock, rounds)
    alive = KeepAlive(beats, stop, clock)
    alive.renew()
    alive.run()
    assert alive.word() == word and beats.calls == calls
    assert BEAT_EVERY_S * 3 == LEASE_TTL_S


def test_a_lapse_is_also_judged_at_the_end_of_the_step() -> None:
    clock = Clock()
    alive = KeepAlive(Beats(clock, "held", "unrenewed"), Stop(clock, 2), clock)
    alive.renew()
    alive.run()
    assert alive.word() == "held"
    clock.now += BEAT_EVERY_S  # the step ends a whole TTL after the last held beat began
    assert alive.word() == "unrenewed"


def test_a_first_renewal_that_finds_the_claim_lost_ends_the_loop_before_it_waits() -> None:
    clock = Clock()
    beats, stop = Beats(clock, "lost"), Stop(clock, 5)
    alive = KeepAlive(beats, stop, clock)
    alive.renew()
    alive.run()
    assert alive.word() == "lost" and beats.calls == 1 and stop.waits == 0


def test_keeping_starts_one_daemon_thread_and_stops_and_joins_it_on_exit() -> None:
    event, waiting, woke = threading.Event(), threading.Event(), threading.Event()

    class Watched:
        def wait(self, timeout: float) -> bool:
            waiting.set()
            stopped = event.wait(timeout)
            woke.set()
            return stopped

        def set(self) -> None:
            event.set()

    clock = Clock()
    beats = Beats(clock, "held")
    alive = KeepAlive(beats, Watched(), clock, interval=1e9)
    with keeping(alive) as kept:
        assert kept is alive and waiting.wait(5)  # the thread blocks in its wait, never waited out
        assert any(each.name == "claim-lease" and each.daemon for each in threading.enumerate())
    assert event.is_set() and woke.is_set() and beats.calls == 0 and alive.word() == "unrenewed"
    assert not any(each.name == "claim-lease" for each in threading.enumerate())


def test_the_one_renewal_shared_by_the_entries_and_the_land_answers_a_faulted_beat_unrenewed() -> None:
    """`renewal` lives here (tl-8bh9.14.8 slice L2) so the checks entry, the shared validation and the land renew the claim
    without importing the agent attempt's entry; a beat that raised is never `held`."""
    clock = Clock()
    alive = KeepAlive(Beats(clock, RuntimeError("bd")), Stop(clock, 0), clock)
    renew = renewal(alive)
    assert (renew(), alive.word()) == ("unrenewed", "fault")
