"""What `tl run-task` runs: a bead, or the task branch or PR of one (tl-9un.52). The bead is the one thing the engine runs on."""
import json
from argparse import Namespace
from typing import Protocol

from taskloop.contracts.ids import BeadId
from taskloop.contracts.ports import Ran

TASK = "task/"


class Runs(Protocol):
    """The one thing resolving needs of a Spawner: run a command and wait."""

    def run(self, argv: list[str], *, cwd: str | None = None) -> Ran: ...


def resolve(a: Namespace, spawner: Runs, repo: str) -> BeadId:
    """The bead named by the ID, by --branch (task/<bead>) or by --pr N (its head branch); ValueError says why none."""
    ident, branch, pr = (getattr(a, k, None) for k in ("id", "branch", "pr"))  # a caller's Args may carry only the id
    named = [x for x in (ident, branch, pr) if x]
    if len(named) != 1:
        raise ValueError("name exactly one of a bead ID, --branch B, --pr N")
    if pr:
        ran = spawner.run(["gh", "pr", "view", str(pr), "--json", "headRefName"], cwd=repo)
        try:
            branch = json.loads(ran.out)["headRefName"] if ran.exit == 0 else ""
        except (ValueError, KeyError):
            branch = ""
        if not branch:
            raise ValueError(f"PR {pr} could not be read: {ran.err.strip()[-200:]}")
    if branch:
        if not branch.startswith(TASK) or len(branch) == len(TASK):
            raise ValueError(f"{branch} is not a task branch (task/<bead>): run-task takes the branch of a bead")
        return BeadId(branch[len(TASK):])
    return BeadId(str(ident))
