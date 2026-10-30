"""`tl lost`: the bead-branch commits no run will bring home, classed. Reads only: the facts come from app/reconcile/commits.py and
the class from the pure rule in domain/reconcile (diff.findings); this module only chooses the inputs and prints the rows' shape.

Classes: landed (its patch is on the base, or a land of its bead came after it), reclaimed (a later run of the bead started after it),
superseded (on a task/<bead>-stale-<time> branch --fresh set aside), pending (its bead is open, blocked or in progress: its next run
continues the branch), unknown (bd failed: listed, never counted as lost), lost (its bead is closed or absent with no land after it,
or it is on a wip/* branch of a dead session)."""
from collections.abc import Callable, Sequence
from typing import Any

from taskloop.adapters import ident
from taskloop.app.reconcile.commits import observe_commits
from taskloop.contracts.ids import BeadId
from taskloop.contracts.landed import LandedStore
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import Git
from taskloop.contracts.trace import RunTrace
from taskloop.domain.reconcile.diff import findings
from taskloop.domain.reconcile.facts import Observed


def lost_work(repo: str, base: str, status_of: Callable[[BeadId], str | None], traces: Sequence[RunTrace], git: Git,
              since: float | None = None, cfg: ConfigDir | None = None) -> list[dict[str, Any]]:
    """Every commit on a task/<bead> or wip/* branch that is not on the base, classed. `status_of`: a bead's bd status (None: no such
    bead, "?": bd failed); `traces`: the engine's runs of this repo."""
    store = LandedStore(cfg or ConfigDir(ident.config_dir()))
    commits = observe_commits(git, repo, base, since, status_of, traces, store)
    seen = Observed(now=0.0, keep_days=0.0, commits=commits)
    return [{"branch": f.commit.branch, "bead": f.commit.bead, "sha": f.commit.sha, "time": f.commit.time, "subject": f.commit.subject,
             "class": f.cls, "why": f.why} for f in findings(seen)]

