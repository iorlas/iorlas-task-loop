"""Argument adapters for tl report, tl lost and tl reflect digest."""

import time
from typing import Any

from tlkernel.env import Env
from tlkernel.gitport import Git
from tlkernel.identity import Identity

from taskloop.app.launch import repos
from taskloop.app.reconcile import lost as lostwork
from taskloop.app.report import card, planner, reflect
from taskloop.app.report.inputs import bead_status, landed_of, repo_traces
from taskloop.app.report.window import since_of, window


def cmd_report(a: Any, env: Env, git: Git, who: Identity) -> int:
    since, until = window(getattr(a, "since", None), getattr(a, "until", None), time.time())
    if getattr(a, "planner", False):
        return planner.report_planner(who.config, since, until, getattr(a, "prefix", "") or "", as_json=a.json)
    repo = repos.repo_root(a.repo)
    return card.report(repo, repos.default_base(repo, git), since, until, as_json=a.json, git=git, who=who)


def cmd_lost(a: Any, env: Env, git: Git, who: Identity) -> int:
    repo = repos.repo_root(a.repo)
    since = since_of(a.since, time.time())
    traces = repo_traces(repo, git, who.config).runs
    rows = lostwork.lost_work(
        repo,
        repos.default_base(repo, git),
        lambda b: bead_status(b, repo, who),
        traces,
        git,
        lambda b: landed_of(b, repo, who),
        since=since,
    )
    return card.print_lost(rows, as_json=a.json)


def cmd_reflect(a: Any, env: Env, git: Git, who: Identity) -> int:
    return reflect.report_digest(who, a.since, a.until, dry_run=a.dry_run, as_json=a.json)
