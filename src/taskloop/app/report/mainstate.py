"""What the scorecard says of main: red when a revert landed on the base since the window began,
or the last release gate on main failed."""

from typing import Protocol

from taskloop.contracts.gitfacts import LogRow
from taskloop.contracts.slots import SlotGitError
from taskloop.contracts.snapshots import ReleaseResult


class Logs(Protocol):
    def log(self, d: str, include: list[str], exclude: list[str] | None = None, limit: int = 0, grep: str = "") -> list[LogRow]: ...


LOOK = 400  # the newest base commits scanned for a revert


def gate_red(last: ReleaseResult | None, repo: str) -> bool:
    """The last release of this repo failed with no branch replayed: main itself did not pass (a failed branch says nothing of main)."""
    return last is not None and not last.ok and last.repo == repo and last.branch == "main"


def main_state(git: Logs, repo: str, base: str, since: float, last: ReleaseResult | None = None) -> dict[str, object]:
    """{red, reverts, gate_red}: the base's commits since `since` titled Revert, and the last release gate. A base git cannot read is
    not red by reverts: nothing is known of it."""
    gate = gate_red(last, repo)
    try:
        rows = git.log(repo, [base], limit=LOOK, grep="Revert")
    except SlotGitError:
        return {"red": gate, "reverts": [], "gate_red": gate}
    found = [{"sha": r.oid, "t": r.time, "subject": r.subject} for r in rows if r.time >= since and r.subject.startswith("Revert")]
    return {"red": bool(found) or gate, "reverts": found, "gate_red": gate}
