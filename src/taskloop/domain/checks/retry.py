"""When a red check is run again: how long a held lock is waited out, and when a failure says another run would change nothing."""
from taskloop.domain.checks.matchers import failure_kind

LOCK_BACKOFF = (15, 30, 60)  # seconds; the last repeats until LOCK_WAIT_MAX
LOCK_WAIT_MAX = 300
SLOW_S = 20 * 60.0  # a check slower than this is not run again on the output it failed with before


def lock_waits() -> list[int]:
    """The sleeps before each rerun of a check held by a lock: 15, 30, 60, 60 ... s, 5 min in all."""
    out: list[int] = []
    total = 0
    while total < LOCK_WAIT_MAX:
        d = min(LOCK_BACKOFF[min(len(out), len(LOCK_BACKOFF) - 1)], LOCK_WAIT_MAX - total)
        out.append(d)
        total += d
    return out


def retry_allowed(retry: int, tries: int, output: str) -> bool:
    """Whether a check that failed `tries` times may run again: by its `retry` count; a compile error only once, and only if the log
    shows an asset import in flight; a lock is waited out elsewhere."""
    kind = failure_kind(output)
    if kind == "deterministic":
        return False
    return tries <= (max(retry, 1) if kind == "import" else retry)


def skip_slow_rerun(sig: str, last_round_sig: str, took_s: float) -> bool:
    """True when a check that took over SLOW_S failed with the output it already failed with in the last round: a rerun would cost
    that long again for the same answer."""
    return took_s > SLOW_S and bool(last_round_sig) and sig == last_round_sig
