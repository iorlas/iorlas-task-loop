"""What the scorecard says of main: red when a revert landed on the base since the window began."""

from typing import Protocol

from taskloop.contracts.gitfacts import LogRow
from taskloop.contracts.slots import SlotGitError


class Logs(Protocol):
    def log(self, d: str, include: list[str], exclude: list[str] | None = None, limit: int = 0, grep: str = "") -> list[LogRow]: ...


LOOK = 400  # the newest base commits scanned for a revert


def main_state(git: Logs, repo: str, base: str, since: float) -> dict[str, object]:
    """{red, reverts}: the base's commits since `since` titled Revert. A base git cannot read is not red: nothing is known of it."""
    try:
        rows = git.log(repo, [base], limit=LOOK, grep="Revert")
    except SlotGitError:
        return {"red": False, "reverts": []}
    found = [{"sha": r.oid, "t": r.time, "subject": r.subject} for r in rows if r.time >= since and r.subject.startswith("Revert")]
    return {"red": bool(found), "reverts": found}
