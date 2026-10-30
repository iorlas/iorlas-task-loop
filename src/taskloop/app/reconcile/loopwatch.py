"""The absent-loop finding for one repo: the loop registry's live loops and the ready beads, judged by the reconcile diff."""
from collections.abc import Sequence

from taskloop.contracts.loop import LoopState
from taskloop.contracts.reconcile import LoopFact
from taskloop.domain.reconcile.diff import diff
from taskloop.domain.reconcile.facts import NoLoop, Observed, RepoView


def absent_loop(repo: str, loops: Sequence[LoopState], ready: int, last_beat: float, now: float, absent: float) -> NoLoop | None:
    """The finding when `repo` has ready beads and no live loop (and no beat for `absent` seconds), else None. `last_beat`: the
    latest beat of any loop of the repo, live or dead, 0 when never."""
    view = RepoView(repo, repo, loops=tuple(LoopFact(st.pid, st.started, st.t or st.started) for st in loops), ready=ready,
                    last_beat=last_beat, absent=absent)
    return next((a for a in diff(Observed(now, 0.0, (view,))) if isinstance(a, NoLoop)), None)
