"""When a stuck episode ends, from typed engine records alone."""

from collections.abc import Sequence

from tlkernel import log as rec


def silent_ends(r: rec.EngineLog) -> bool:
    """Any activity record ends a silent episode; Beats and Stucks do not."""
    return not isinstance(r, (rec.Beat, rec.Stuck))


def red_ends(sig: str, r: rec.EngineLog) -> bool:
    """A green check round or a different red signature ends a same_red episode."""
    return isinstance(r, rec.Checks) and (not r.run.failed or r.run.signature() != sig)


def open_episode(records: Sequence[rec.EngineLog]) -> rec.Stuck | None:
    """The newest Stuck whose episode is still open; a newer Stuck replaces the previous episode."""
    last: rec.Stuck | None = None
    for r in records:
        if isinstance(r, rec.Stuck):
            last = r
        elif last is not None and (silent_ends(r) if last.why == "silent" else red_ends(last.sig, r)):
            last = None
    return last
