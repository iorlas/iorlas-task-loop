"""The one record that a bead's work reached its base: three keys of the bead's own metadata (landed_sha, landed_base, landed_at), so
another machine reads the outcome from bead state. `verbs.land` writes them once the sha is on the base; `tl lost`, `tl prune` and the
loop read them, and each checks that the sha is an ancestor of the base they mean (a record is a claim until git confirms it). Subject
text, committer time and a trace outcome decide nothing for a bead that has a record. A newer land of a reopened bead replaces them."""
from collections.abc import Callable, Mapping
from typing import Any

from taskloop.contracts.ids import BeadId
from taskloop.contracts.ports import BdFailure, Beads
from taskloop.contracts.wire import Rec

LANDED_SHA, LANDED_BASE, LANDED_AT = "landed_sha", "landed_base", "landed_at"


class Landed(Rec):
    bead: BeadId
    sha: str  # the base ref's tip as `git ls-remote` showed it right after the push
    base: str  # the base ref the land pushed to (origin/main)
    t: float  # wall clock of the push; a rebase never rewrites it


def landed_meta(rec: Landed) -> dict[str, str]:
    """The metadata keys that say `rec` (for BeadPatch.set_metadata)."""
    return {LANDED_SHA: rec.sha, LANDED_BASE: rec.base, LANDED_AT: repr(rec.t)}


def landed_in(bead: BeadId, metadata: Mapping[str, Any]) -> Landed | None:
    """The landed record a bead's metadata holds; None when it holds none (or an unreadable one)."""
    sha, base, at = metadata.get(LANDED_SHA), metadata.get(LANDED_BASE), metadata.get(LANDED_AT)
    if not (isinstance(sha, str) and sha and isinstance(base, str) and isinstance(at, str)):
        return None
    try:
        return Landed(bead=bead, sha=sha, base=base, t=float(at))
    except ValueError:
        return None


def landed_by(store: Beads) -> Callable[[BeadId], Landed | None]:
    """A bead's landed record from the tracker; None when it has none or the tracker does not answer (git's legacy proofs then decide)."""
    def of(bead: BeadId) -> Landed | None:
        try:
            shown = store.show(bead)
        except BdFailure:
            return None
        return landed_in(bead, shown.metadata) if shown else None
    return of
