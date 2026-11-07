"""Argument adapters for tl report, tl lost and tl reflect digest."""

from typing import Any

from tlkernel.env import Env
from tlkernel.gitport import Git
from tlkernel.identity import Identity

from taskloop.app.launch import repos
from taskloop.app.report import reflect, window


def cmd_report(a: Any, env: Env, git: Git, who: Identity) -> int:
    return window.report(
        a.repo, getattr(a, "since", None), getattr(a, "until", None),
        getattr(a, "planner", False), getattr(a, "prefix", "") or "", a.json, who, git, repos.default_base,
    )


def cmd_lost(a: Any, env: Env, git: Git, who: Identity) -> int:
    return window.lost(a.repo, a.since, a.json, who, git, repos.default_base)


def cmd_reflect(a: Any, env: Env, git: Git, who: Identity) -> int:
    return reflect.report_digest(who, a.since, a.until, dry_run=a.dry_run, as_json=a.json)
