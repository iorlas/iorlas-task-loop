"""`tl step rounds`: scheduling rounds one after another in this foreground process until it is stopped.

A round at once; then the next regular round `every` seconds after the previous one ended, or sooner when a slot frees:
the reserved slots are read just before and just after each round (their union is the baseline) and every `CHECK`
seconds after it, and when a slot of the baseline is no longer reserved the next round starts at once (a release during
the round, and the end of a step the round itself started, included). The baseline
is every backlog's reservations: another backlog's release also wakes a round, which then finds nothing to do. Each
round is `round.run_round` as built (it reads the tracker only when a slot may be free). A round that
ends on an unknown (`unavailable`/`uncertain`, whole-round or admission's stop word) backs the regular rounds off,
doubling from the interval up to `CAP`; nothing is stored. It ends gracefully when `stopping` turns True (the first
Ctrl-C) and on a whole-round refusal; a `KeyboardInterrupt` (the second Ctrl-C) passes through as the abrupt stop, after
one best-effort `rounds stopped abrupt` line. It adds no state, lock, write or process of its own beyond its round-log
lines (fixed words, never read back); one rounds process per backlog is the caller's lock (`rounds_lock`).
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from taskloop.attempt_reads import SlotUse
from taskloop.evidence_files import EvidenceError
from taskloop.operations import Ended, Failed, Quiet, Round, minutes_refused
from taskloop.round import STOPPING_UNKNOWN, NextRequest
from taskloop.round_log import IDENT, INTERRUPTED, fixed, stamped

CHECK: Final = 2.0  # seconds between two reads of the reservation rows
CAP: Final = 300  # the longest backoff delay, unless the interval is longer


@dataclass(frozen=True)
class RoundsRequest:
    backlog: str
    every: int  # seconds, at least `machine_config.MIN_SECONDS`


@dataclass(frozen=True)
class RoundsPorts:
    """`round`: one `round.run_round` over fresh ports, with the given `quiet`; `slot_use`: factory.db's reservation rows read
    now (None when unreadable); `clock`, the wall clock for log stamps; `monotonic` and `wait` pace; `warn`, said when
    the round log stops being written; `stopping`, True once a graceful stop is asked."""

    round: Callable[[Quiet], Round | Failed]
    slot_use: Callable[[], SlotUse | None]
    clock: Callable[[], float]
    monotonic: Callable[[], float]
    wait: Callable[[float], None]
    log: Callable[[str], None]
    warn: Callable[[], None]
    stopping: Callable[[], bool]
    pid: int


def inputs(request: NextRequest) -> Failed | None:
    """The round's choices, checked once before the lock or any read: a plain-word backlog (it names the lock file), a
    non-blank label, model and effort, minutes in range."""
    if not IDENT.fullmatch(request.backlog) or "/" in request.backlog:
        return Failed("refused", "backlog", "The backlog must be one word of letters, digits and ._:@+-")
    if not request.label.strip():
        return Failed("refused", "label", "An approval label is required (`--label auto`); a round never takes every ready task")
    if not request.model.strip() or not request.effort.strip():
        return Failed("refused", "choices", "--model and --effort must not be blank")
    return minutes_refused(request.minutes)


class _Log:
    """The rounds process's own round-log lines; `warn` once each time the log stops being written."""

    def __init__(self, ports: RoundsPorts, backlog: str) -> None:
        self.ports, self.backlog = ports, backlog
        self.logged = True

    def write(self, *words: str) -> None:
        try:
            self.ports.log(stamped(self.ports.clock(), self.backlog, "rounds", *words))
        except (OSError, EvidenceError):
            self.seen(False)
            return
        self.seen(True)

    def seen(self, logged: bool) -> None:
        if self.logged and not logged:
            self.ports.warn()
        self.logged = logged


class _Backoff:
    """The regular rounds' delay: the interval, or after consecutive unknown rounds the interval, then twice the last
    delay up to `CAP` (or the interval if longer); a line when the delay or its cause changes."""

    def __init__(self, every: int) -> None:
        self.every, self.delay, self.word = every, every, ""

    def after(self, found: Round | Failed, log: _Log) -> int:
        word = _unknown(found)
        delay = min(max(CAP, self.every), self.delay * 2) if word and self.word else self.every
        if (delay, word) != (self.delay, self.word):
            log.write("wait", f"seconds={delay}", *([f"after={fixed(word)}"] if word else []))
        self.delay, self.word = delay, word
        return delay


def _unknown(found: Round | Failed) -> str:
    word = found.word if isinstance(found, Failed) else found.stopped
    return word if word.split(":")[0] in STOPPING_UNKNOWN else ""


def run_rounds(ports: RoundsPorts, request: RoundsRequest) -> Ended:
    """Rounds until a stop: `Ended("interrupted")` after a graceful stop (no further move or round), `Ended` with the
    word of a whole-round refusal (`refused:database`, `refused:schema`, ...). Per-task words never end or back off. A
    `KeyboardInterrupt` once `rounds started` is written adds the best-effort `rounds stopped abrupt` and passes on."""
    log = _Log(ports, request.backlog)
    log.write("started", f"every={request.every}", f"pid={ports.pid}")
    try:
        return _rounds(ports, request, log)
    except KeyboardInterrupt:
        abrupt(ports.log, ports.clock, request.backlog)
        raise


def _rounds(ports: RoundsPorts, request: RoundsRequest, log: _Log) -> Ended:
    quiet: Quiet = frozenset()
    backoff = _Backoff(request.every)
    while not ports.stopping():
        before = _held(ports)
        found = ports.round(quiet)
        if isinstance(found, Failed) and found.kind not in STOPPING_UNKNOWN:
            return _end(log, request.backlog, found.word, found.detail)
        if isinstance(found, Round):
            log.seen(found.logged)
            quiet = found.written
        if ports.stopping():
            break
        _pause(ports, backoff.after(found, log), _union(before, _held(ports)))
    return _end(log, request.backlog, INTERRUPTED)


def _held(ports: RoundsPorts) -> frozenset[tuple[str, str]] | None:
    found = ports.slot_use()
    return None if found is None else found.held


def _union(before: frozenset[tuple[str, str]] | None, after: frozenset[tuple[str, str]] | None) -> frozenset[tuple[str, str]] | None:
    """The wake baseline: the slots reserved before the round (released during it: the first check wakes) and after it
    (reserved by it: its step's end wakes); None only when neither read succeeded."""
    if before is None or after is None:
        return after if before is None else before
    return before | after


def _pause(ports: RoundsPorts, delay: int, baseline: frozenset[tuple[str, str]] | None) -> None:
    """Until the next regular round is due, a stop is asked, or a reserved slot of the baseline (read before and after
    the round) is no longer reserved. A slot reserved since never wakes; an empty baseline has nothing to lose and is not read
    again; a failed read neither wakes nor fails, and while there is no baseline each check retries it."""
    due = ports.monotonic() + delay
    while not ports.stopping() and (left := due - ports.monotonic()) > 0:
        ports.wait(min(CHECK, left))
        if baseline is not None and not baseline:
            continue
        now = _held(ports)
        if baseline is not None and now is not None and not baseline <= now:
            return
        baseline = now if baseline is None else baseline


def _end(log: _Log, backlog: str, reason: str, detail: str = "") -> Ended:
    log.write("stopped", fixed(reason))
    return Ended(backlog, reason, detail)


def abrupt(log: Callable[[str], None], clock: Callable[[], float], backlog: str) -> None:
    """The abrupt stop's one best-effort line: a write error or a further Ctrl-C during it is ignored."""
    try:
        log(stamped(clock(), backlog, "rounds", "stopped", "abrupt"))
    except (OSError, EvidenceError, KeyboardInterrupt):
        return
