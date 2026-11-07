"""The verb `tl lint [BEAD | --ready [--fix]]`: the bead rules (domain/beads/rules.py) over one bead or the repo's ready beads."""
from typing import Any

from tlkernel.identity import Identity

from taskloop.app.launch import loop as wloop
from taskloop.app.launch import repos
from taskloop.app.loop import lintrun


def cmd_lint(a: Any, who: Identity) -> int:
    root = repos.repo_root(a.repo)
    return lintrun.run(wloop.bd_of(who, root), root, a.ready, a.fix, a.bead)
