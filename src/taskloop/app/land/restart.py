"""The branch's earlier work conflicts with the base: it is kept under another name and the task starts again on the base."""
import time
from typing import Protocol

from taskloop.app.land.gitcall import must
from taskloop.app.land.parts import MoveSteps
from taskloop.contracts.checkpoint import RunState
from taskloop.contracts.plancheck import PlanData
from taskloop.contracts.ports import Git
from taskloop.contracts.slots import SlotGitError
from taskloop.stores.runlog import RunLog


class RestartConfig(Protocol):
    @property
    def base(self) -> str: ...


class RestartCheckpoints(Protocol):
    def drop(self) -> None: ...


class RestartHost(Protocol):
    """What a restart on the base reads of the engine: git, the branch, the checkpoint it drops, and the run's plan
    bookkeeping that the old attempt leaves and a restart clears."""

    old_plan: PlanData | None
    amend_why: str
    amend_text: str
    replan_first: bool
    plan_summary: str
    last_summary: str
    amended: bool
    state: RunState
    unverified: list[dict[str, str]]
    unchecked: list[dict[str, str]]

    @property
    def wt(self) -> str: ...
    @property
    def branch(self) -> str: ...
    @property
    def cfg(self) -> RestartConfig: ...
    @property
    def git(self) -> Git: ...
    @property
    def log(self) -> RunLog: ...
    @property
    def steps(self) -> MoveSteps: ...
    @property
    def checkpoints(self) -> RestartCheckpoints: ...
    def warn(self, text: str) -> None: ...
    def blocked_for(self, why: str, kind: str) -> Exception: ...
    def comment(self, text: str) -> None: ...


class Restart:
    def __init__(self, host: RestartHost) -> None:
        self.e = host

    def again(self, why: str) -> bool:
        """tl-19i: the branch's earlier work conflicts with main, so it cannot go on. It is kept under another name; the task starts again
        on the base with a fresh plan (the owner's answer is in the bead's comments), and nothing so far counts toward the re-plan limit."""
        e = self.e
        branch = e.git.branch(e.wt)
        if not branch or branch != (e.branch or branch):
            e.warn(f"resume conflict, but HEAD is not the task branch ({branch or 'detached'}): the branch stays as it was")
            return False
        stale = f"{branch}-stale-{time.strftime('%Y%m%d-%H%M%S')}"
        if e.git.has_branch(e.wt, stale):
            stale += "-2"
        try:
            e.git.rename_branch(e.wt, branch, stale)
        except SlotGitError as err:  # never reset a branch whose work could not be kept
            e.warn(f"resume conflict, but the branch could not be kept aside ({str(err).strip()[-160:]}): it stays as it was")
            return False
        must(e, f"checkout -B {branch} {e.cfg.base}", lambda: e.git.checkout_reset(e.wt, branch, e.cfg.base))
        e.checkpoints.drop()
        self.forget()
        e.steps.move("plan", "resume_conflict",
                     f"the branch's earlier work conflicts with {e.cfg.base}: kept as {stale}, planning fresh. {why[:160]}")
        e.log.note(f"resume conflict: {branch} kept as {stale}; the task starts again on {e.cfg.base}")
        e.comment(f"Resume (engine): the earlier work on {branch} conflicts with {e.cfg.base}. It is kept as the branch {stale}; "
                  f"the task starts again on {e.cfg.base} with a fresh plan.")
        return True

    def forget(self) -> None:
        """What the old attempt left in the run: the plan, the accepted stages, the writer, the look state (verify_answer stays: the owner's
        word still goes to the planner)."""
        e = self.e
        e.old_plan, e.amend_why, e.amend_text, e.replan_first = None, "", "", False
        e.plan_summary, e.last_summary, e.amended = "", "", False
        e.state = e.state.start_again()
        e.unverified = list[dict[str, str]]()
        e.unchecked = list[dict[str, str]]()
