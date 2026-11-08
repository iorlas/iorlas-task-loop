"""The land gate on the rebased tree, refusals for unverified checks, and owner-only profile delivery."""

import hashlib
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Protocol, final

from tlgate.api import CheckFault, engine_digest, evidence, gate_items
from tlkernel import log as rec
from tlkernel.checks import UNVERIFIED_EXIT, Check, CheckFaultKind, CheckResult, CheckRun
from tlkernel.config import EngineConfig
from tlkernel.env import Env
from tlkernel.envvars import registered
from tlkernel.gitport import Git
from tlkernel.ids import TreeSha
from tlkernel.runkey import BaseSha, Digest
from tlkernel.stagefacts import RunLogPort

from tlland.host import LandState

FAULTS = MappingProxyType({CheckFaultKind.STALE_BASE: "FAULT_STALE_BASE", CheckFaultKind.KILLED: "PAUSE_KILLED",
                         CheckFaultKind.DIRTY_SLOT: "FAULT_SLOT",})


class ProblemKind(StrEnum):
    GATE = "gate"
    CONFLICT = "conflict"
    VERIFY = "verify"
    STALE = "stale"  # main (or the tree) moved under the gate: no fix round, the lock is let go and the gate runs again


class _Seal(Enum):
    """The key to GatePass's constructor: only `mint` (below, in this module) holds it, so pyrefly refuses a GatePass built anywhere else
    (and tests/rules/test_gatepass_rule.py refuses the seal named anywhere else)."""

    ISSUED = 1


NO_DIGEST = Digest("")


@final
@dataclass(frozen=True)
class GatePass:
    """The gate's word that `tree` passed on `base`: the push takes one and pushes only that tree on that base. Only the gate makes one."""

    tree: TreeSha
    base: BaseSha
    config: Digest = NO_DIGEST
    seal: _Seal = field(kw_only=True, repr=False, compare=False)


def mint(tree: TreeSha, base: BaseSha, config: Digest = NO_DIGEST) -> GatePass:
    """The one factory of GatePass. Called by Gate (after its steps are green in the memo, or when the repo has no gate) and by tests."""
    return GatePass(tree, base, config, seal=_Seal.ISSUED)


@dataclass(frozen=True)
class Problem:
    """Why a try of the land did not push: `kind`; `text` goes to the fix round; `named`: a gate's red steps."""

    kind: ProblemKind
    text: str
    named: str = ""


class GateChecker(Protocol):
    def run_items(self, items: Sequence[Check], everything: bool = ..., learn: bool = ..., show_clean: bool = ...,
                  clean: bool = ...) -> CheckRun: ...
    def gate_green(self, clean: bool = ...) -> bool: ...


class GateSteps(Protocol):
    def outcome(self, outcome: str, detail: str = ...) -> None: ...


class GateCheckout(Protocol):
    def tree_hash(self) -> TreeSha: ...


class GateHost(Protocol):
    """What the gate reads of the engine: the repo's gate steps and the checker that runs them, git, the log and the stop point."""

    land_state: LandState

    @property
    def cfg(self) -> EngineConfig: ...
    @property
    def run_dir(self) -> Path: ...
    @property
    def log(self) -> RunLogPort: ...
    @property
    def steps(self) -> GateSteps: ...
    @property
    def checker(self) -> GateChecker: ...
    @property
    def checkout(self) -> GateCheckout: ...
    @property
    def git(self) -> Git: ...
    @property
    def wt(self) -> str: ...
    def halt_point(self, when: bool = ..., wait: float = ...) -> None: ...
    def blocked_for(self, why: str, kind: str) -> Exception: ...
    def move_host(self, needs: list[str], why: str) -> Exception: ...


class Gate:
    def __init__(self, host: GateHost) -> None:
        self.e = host

    def green(self) -> bool:
        """Both clean and slot steps passed on this tree and base, using each location's own input keys."""
        return self.e.checker.gate_green(clean=True)

    def passed(self) -> GatePass | None:
        """A pass for the tree and base in the worktree now: the gate is green in the memo, or the repo has no gate. Else None."""
        e = self.e
        if e.cfg.gate_checks and not self.green():
            return None
        return self.issue()

    def issue(self) -> GatePass:
        e = self.e
        return mint(TreeSha(e.git.rev_parse(e.wt, "HEAD^{tree}")), BaseSha(e.git.rev_parse(e.wt, e.cfg.base)), engine_digest(e.cfg))

    def run(self) -> GatePass | Problem:
        """-> the pass when the gate passed (or already had on this tree), else the problem for a fix round."""
        e = self.e
        if getattr(e.steps, "only", None) == "land":
            if not self.green():
                raise ValueError("land refused: gate is no longer green for this tree and base; run --stage gate")
            return self.issue()
        e.land_state.gate_log = None
        tree = e.git.rev_parse(e.wt, "HEAD^{tree}")
        head = e.git.rev_parse(e.wt, "HEAD")
        config = engine_digest(e.cfg)
        started = time.time()
        e.log.emit(rec.GateStart(cmd=e.cfg.gate_text, log=str(e.run_dir / "checks"), tree=tree))
        try:
            # Keep both locations in one plan: a red in either group blocks the gate and its later dependent steps.
            # The checker routes slot items through non-clean input keys while guarding the committed tree in both hosts.
            run = e.checker.run_items(gate_items(e.cfg), clean=True)
        except CheckFault as fault:
            e.log.emit(rec.GateEnd(exit=fault.rc, exec_seconds=round(time.time() - started)))
            raise e.blocked_for(fault.text, FAULTS[fault.kind]) from fault
        if refusal(run):
            e.log.emit(rec.GateEnd(exit=1, exec_seconds=round(time.time() - started)))
            raise stop(run, e)
        e.halt_point()  # a stop ended a step, which then reports itself red: the run stops here, not in a fix round
        reds = [c for c in run.results if c.red and not deferred(c)]
        skipped = not reds and all(c.cached or c.exit is None for c in run.results)
        if skipped:
            e.log.note(f"gate skipped: every step already passed on tree {tree[:12]}")
        passed = passed_over(run)
        if passed:
            e.log.note(f"gate passed past deferred checks (no such resource here, inputs unchanged): {', '.join(passed)}")
        stale = False
        if not reds:
            current_tree = e.checkout.tree_hash()
            current_head = e.git.rev_parse(e.wt, "HEAD")
            current_base = e.git.rev_parse(e.wt, e.cfg.base)
            head_tree = e.git.rev_parse(e.wt, "HEAD^{tree}")
            stale = (not run.tree or not run.base or run.tree != current_tree or run.tree != tree or run.tree != head_tree
                     or head != current_head or run.base != current_base or run.config != config or config != engine_digest(e.cfg))
        e.log.emit(rec.GateEnd(exit=1 if reds or stale else 0, exec_seconds=round(time.time() - started),
                               skipped=skipped, deferred=passed))
        if stale:
            text = "gate stale: tree, HEAD, base or configuration moved during checks; rerun the gate"
            e.steps.outcome("gate stale", text)
            return Problem(ProblemKind.STALE, text)
        if not reds:
            return mint(run.tree, run.base, run.config)
        e.land_state.gate_log = e.run_dir / reds[0].log if reds[0].log else None
        names = ", ".join(c.id for c in reds)
        e.steps.outcome("gate red", names)
        return Problem(ProblemKind.GATE, f"gate steps red: {names}\n" + evidence.failure_brief(reds, e.run_dir), names)


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


def owner_refusal(text: str | None, env: Env) -> str:
    if text is None:
        return ""
    settings = ("TASK_LOOP_DASH_",)
    if any(registered(name) and not name.startswith(settings) for name in env.vars):
        return "profile change is an owner decision; not available to the engine or an account"
    if len(text.strip()) < 12 or not any(char.isdigit() for char in text):
        return "land-stack: --profile-change requires the owner's words and a timestamp (at least 12 characters and a digit)"
    return ""


def diff_sha(git: Git, repo: str, base: str, tip: str) -> str:
    return hashlib.sha256(git.profile_diff(repo, base, tip).encode("utf-8")).hexdigest()
