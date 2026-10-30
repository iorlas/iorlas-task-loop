"""The land and a check that could not verify (exit UNVERIFIED_EXIT): such a check is not a pass, so the land refuses to land on it."""

from collections.abc import Callable

from taskloop.contracts.checks import UNVERIFIED_EXIT, CheckResult, CheckRun


def deferred(c: CheckResult) -> bool:
    """The one hook for tl-7k8.5: True when a resource rule lets the land go on past this unverified check (and says why in a note).
    Until that exists nothing is deferred."""
    return False


def refusal(run: CheckRun) -> str:
    """'' when the land may go on; else the message naming every unverified check that is not deferred."""
    held = [c for c in run.unverified if not deferred(c)]
    if not held:
        return ""
    names = ", ".join(f"`{c.id[:80]}`" for c in held)
    return (f"failed: not landed: required check {names} is unverified (it exited {UNVERIFIED_EXIT}: it could not verify what it checks), "
            "and an unverified check is not a pass; the branch is kept. Make the check able to run (the tool, host or resource it "
            "lacks), then run the bead again")


def latest(last: CheckRun | None, saved: Callable[[], CheckRun | None]) -> CheckRun | None:
    """The last round of the engine's checks: in memory, else the saved one (after a resume)."""
    return last or saved()
