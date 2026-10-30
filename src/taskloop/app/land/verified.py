"""The land and a check that could not verify (exit UNVERIFIED_EXIT): such a check is not a pass, so the land refuses to land on it."""

from collections.abc import Callable
from typing import Protocol

from taskloop.contracts.checks import UNVERIFIED_EXIT, CheckResult, CheckRun


def deferred(c: CheckResult) -> bool:
    """True when the land may go on past this unverified check: the host lacks a resource it needs (tl-7k8.5) and the diff did not
    touch anything it reads, so a host that has the resource has nothing new to verify."""
    return bool(c.deferred) and not c.inputs_changed


def passed_over(run: CheckRun) -> list[str]:
    """The ids of the checks the land goes on past because they were deferred (the land's note names them)."""
    return [c.id for c in run.unverified if deferred(c)]


def _held(run: CheckRun) -> list[CheckResult]:
    return [c for c in run.unverified if not deferred(c)]


def waiting(run: CheckRun) -> list[CheckResult]:
    """The unverified checks that wait for a host that has their resource (deferred, and their inputs changed)."""
    return [c for c in _held(run) if c.deferred]


def kind_of(run: CheckRun) -> str:
    """The outcome kind of a refusal: PAUSE_MOVED (to a host with the resource) when every check held waits for one, else FAULT_LAND."""
    held = _held(run)
    return "PAUSE_MOVED" if held and len(waiting(run)) == len(held) else "FAULT_LAND"


def moves(run: CheckRun) -> list[str]:
    """The resources the bead must move to a host for: what the waiting checks need and this host lacks."""
    return sorted({r for c in waiting(run) for r in c.deferred})


def refusal(run: CheckRun) -> str:
    """'' when the land may go on; else the message naming every unverified check that is not deferred."""
    held = _held(run)
    if not held:
        return ""
    names = ", ".join(f"`{c.id[:80]}`" for c in held)
    if kind_of(run) == "PAUSE_MOVED":
        need = ", ".join(moves(run))
        return (f"paused: not landed: check {names} needs {need}, which this host does not have, and this diff changes what it reads; "
                f"the branch is kept, the bead is labelled needs:{need} and goes back to the queue for a host that has it")
    return (f"failed: not landed: required check {names} is unverified (it exited {UNVERIFIED_EXIT}: it could not verify what it checks), "
            "and an unverified check is not a pass; the branch is kept. Make the check able to run (the tool, host or resource it "
            "lacks), then run the bead again")


def latest(last: CheckRun | None, saved: Callable[[], CheckRun | None]) -> CheckRun | None:
    """The last round of the engine's checks: in memory, else the saved one (after a resume)."""
    return last or saved()


class Blocks(Protocol):
    def blocked_for(self, why: str, kind: str) -> Exception: ...
    def move_host(self, needs: list[str], why: str) -> Exception: ...


def stop(run: CheckRun, host: Blocks) -> Exception:
    """The stop for a run `refusal` refuses: a move to a capable host (the needs label set, the bead released), else a land fault."""
    why = refusal(run)
    return host.move_host(moves(run), why) if kind_of(run) == "PAUSE_MOVED" else host.blocked_for(why, kind_of(run))


def refuse(run: CheckRun | None, host: Blocks) -> list[str]:
    """A required check that could not verify is no pass: nothing is committed or pushed. -> the deferred checks the land goes on
    past (it says so in a note)."""
    if run and refusal(run):
        raise stop(run, host)
    return passed_over(run) if run else []
