"""Pipeline admission and read-only plans over narrow observation ports."""
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from tlkernel.branches import task_branch
from tlkernel.checkpoint import Checkpoint
from tlkernel.enums import Step
from tlkernel.gitfacts import StatusRow
from tlkernel.ids import BeadId, TreeSha
from tlkernel.locator import RunBundle
from tlkernel.slots import NotARepo
from tlpipeline.cursor import select_step


class Printer(Protocol):
    def say(self, text: str) -> None: ...


class GitView(Protocol):
    def branch(self, d: str) -> str: ...
    def toplevel(self, d: str) -> str: ...
    def status(self, d: str, all_untracked: bool = False) -> list[StatusRow]: ...
    def rev_parse(self, d: str, rev: str) -> str: ...


def _inspect_uncommitted(printer: Printer, wt: str, paths: list[str], last: RunBundle | None, *, force: bool, continuous: bool) -> None:
    if paths and not continuous:
        state = str(last.manifest.state) if last else "unrecorded"
        printer.say(f"uncommitted work in {wt} (previous run: {state}); a WIP commit would include {len(paths)} files:")
        for path in paths:
            printer.say(f"  {path}")
        if not force:
            raise ValueError("uncommitted work refused: use --force to allow a WIP commit")


def inspect(bead: BeadId, wt: str, repo: str, *, git: GitView, printer: Printer,
            newest: Callable[[BeadId, str], RunBundle | None], checkpoint: Callable[[], Checkpoint | None],
            has_land: Callable[[], bool], green_gate: Callable[[TreeSha, bool], bool], plan_deferred: bool,
            requested: str | None, fresh: bool, force: bool, continuous: bool, dry: bool, slot: str = "") -> str:
    """Read-only admission and preview using supplied observations."""
    if not dry and (continuous or not requested):
        return ""
    last = newest(bead, repo)
    ck = None if fresh else checkpoint()
    try:
        branch = git.branch(wt) if wt else ""
    except NotARepo:
        branch = ""  # a new checkout has no branch to inspect yet
    top = git.toplevel(wt) if branch == task_branch(bead) else ""
    checkout = bool(top) and Path(top).resolve() == Path(wt).resolve()
    if dry:
        printer.say(f"plan: bead {bead}; stage {requested or ('loop' if continuous else 'auto-next')}")
        printer.say(f"worktree: {wt or '(new worktree)'}; slot: {slot or '(none)'}; lease: would acquire")
        printer.say(f"branch: {branch or '(new task branch)'}")
    try:
        step = select_step(last, ck, fresh, requested)
        if dry:
            printer.say(f"next stage: {step}")
        paths = (sorted({row.path for row in git.status(wt, all_untracked=True)})
                 if not continuous and checkout else [])
        _inspect_uncommitted(printer, wt, paths, last, force=force, continuous=continuous)
        if dry and not continuous:
            if step is Step.CLOSE and not has_land():
                raise ValueError("close refused: no land on record; run --stage land")
            if step is Step.LAND:
                tree = TreeSha(git.rev_parse(wt, "HEAD^{tree}")) if checkout and not paths else TreeSha("")
                # A preview never executes plan_cmd. Without its answer every gate step is required.
                planned = plan_deferred
                if planned:
                    printer.say("gate plan: producer deferred; requiring cached passes for every gate step")
                if not green_gate(tree, planned):
                    raise ValueError("land refused: no green gate for the current tree and base; run --stage gate")
        if dry:
            printer.say("refusals: none")
    except ValueError as err:
        return str(err)
    return ""


def enter(bead: BeadId, *, release_dead: Callable[[], None], parked: Callable[[], str],
          admit: Callable[[], tuple[bool, str]], claim: Callable[[], int],
          say: Callable[[str], None], taken: Callable[[str], None]) -> str | None:
    """Sweep leases, honor parks, admit (including reopen), then retry the claim."""
    release_dead()
    if why := parked():
        taken(f"TAKEN: {why}")
        return why
    ok, why = admit()
    if not ok:
        taken(f"TAKEN: {why}")
        return why
    if why:
        say(f"{bead}: {why}")
    if claim() != 0:
        return "claimed by another session"
    return None
