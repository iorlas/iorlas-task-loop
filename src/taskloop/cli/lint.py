"""The verb `tl lint [BEAD | --ready [--fix]]`: the bead rules (domain/beads/rules.py) over one bead or the repo's ready beads."""
from typing import Any

from taskloop.app.launch import loop as wloop
from taskloop.app.launch import repos
from taskloop.app.loop import lintrun


def cmd_lint(a: Any) -> int:
    root = repos.repo_root(a.repo)
    if a.ready:
        return lintrun.lint_ready(wloop.bd_of(root), root, a.fix)
    if a.fix or not a.bead:
        print("usage: tl lint BEAD | tl lint --ready [--fix]")
        return 2
    return lintrun.lint_one(wloop.bd_of(root), root, a.bead)
