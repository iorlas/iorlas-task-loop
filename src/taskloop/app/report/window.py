"""The window a report verb reads: the owner's T for --since and --until (see tlkernel/lifecyclematchers.py: parse_time)."""
import time
from collections.abc import Callable

from tlkernel import lifecyclematchers as matchers
from tlkernel.gitport import Git
from tlkernel.identity import Identity

from taskloop.adapters import gitrepo
from taskloop.app.reconcile import lost as lostwork
from taskloop.app.report import card, planner
from taskloop.app.report.inputs import bead_status, landed_of, repo_traces

DAY_S = 86400


def window(since: str | None, until: str | None, now: float) -> tuple[float, float]:
    """(since, until) of `tl report`: --since defaults to 24 h back, --until to now."""
    return (matchers.parse_time(since, now) if since else now - DAY_S,
            matchers.parse_time(until, now, forward=True) if until else now)


def since_of(text: str | None, now: float) -> float | None:
    """`tl lost --since`: the time, or None for no limit."""
    return matchers.parse_time(text, now) if text else None


def digest_time(text: str, now: float) -> float:
    """`tl reflect digest --since/--until`: Nh back, epoch seconds, or anything a report takes."""
    return matchers.window_time(text, now)


def report(
    repo: str | None, since: str | None, until: str | None, planner_mode: bool,
    prefix: str, as_json: bool, who: Identity, git: Git, base_of: Callable[[str, Git], str],
) -> int:
    """Select a planner report or the repository scorecard over the requested window."""
    start, end = window(since, until, time.time())
    if planner_mode:
        return planner.report_planner(who.config, start, end, prefix, as_json=as_json)
    root = gitrepo.repo_root(repo)
    return card.report(root, base_of(root, git), start, end, as_json=as_json, git=git, who=who)


def lost(
    repo: str | None, since: str | None, as_json: bool, who: Identity, git: Git, base_of: Callable[[str, Git], str],
) -> int:
    """Print the repository's lost work since the requested time."""
    root = gitrepo.repo_root(repo)
    start = since_of(since, time.time())
    traces = repo_traces(root, git, who.config).runs
    rows = lostwork.lost_work(
        root,
        base_of(root, git),
        lambda b: bead_status(b, root, who),
        traces,
        git,
        lambda b: landed_of(b, root, who),
        since=start,
    )
    return card.print_lost(rows, as_json=as_json)
