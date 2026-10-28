"""The loop's offline detector (tl-kyy): a PAUSE_NETWORK close sets it down (one `down` transition), then it probes every
`every` seconds while down (one `up` transition). An unknown probe reads as "go and see" once the first gap has passed: a
loop is never held by a broken probe."""
from taskloop.app.loop.env import Probe


class NetState:
    def __init__(self, every: float = 60.0) -> None:
        self.every = every
        self.down_since: float | None = None
        self.next_probe = 0.0
        self.polls = 0

    @property
    def down(self) -> bool:
        return self.down_since is not None

    def mark_down(self, now: float) -> bool:
        """True only for the transition (the one `net_down` event)."""
        if self.down:
            return False
        self.down_since, self.next_probe, self.polls = now, now, 0
        return True

    def poll(self, probe: Probe, now: float) -> bool:
        """True when the network is back (the state is cleared). Probes at most every `every` seconds."""
        if self.down_since is None or now < self.next_probe:
            return False
        self.polls += 1
        answer = probe.up()
        if answer is None and now - self.down_since < self.every:
            answer = False
        if answer is False:
            self.next_probe = now + self.every
            return False
        self.down_since, self.next_probe = None, 0.0
        return True
