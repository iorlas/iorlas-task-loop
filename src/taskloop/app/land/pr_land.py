"""The land in `land_mode: pr`: the gated, rebased task branch goes to the remote, a PR is opened for it (gh only), and the bead waits as
an ask to the owner until the PR is merged. The engine NEVER merges: no `gh pr merge`, no auto-merge. A rerun reads the PR: merged ->
the land is the PR's own merge commit; open -> the ask again (or, when the work changed since, the PR is updated); closed without a merge
-> a typed ask. The PR number lives in the bead's metadata for as long as the land is pending."""
from pathlib import Path
from typing import Protocol

from taskloop.app.land.cmds import Cmds, Runs, Stop
from taskloop.app.land.forge import Forge
from taskloop.app.land.gate import GatePass, Problem
from taskloop.app.land.outbound import target
from taskloop.app.land.parts import FetchCheckout, OutcomeSteps
from taskloop.app.land.push import stale
from taskloop.app.land.push_evidence import failure
from taskloop.app.land.state import Land, Next
from taskloop.contracts import fence
from taskloop.contracts.forge import CLOSED, MERGED, PR_NUMBER, PR_URL, Pr, pr_waited_on
from taskloop.contracts.ids import BeadId
from taskloop.contracts.ports import BeadPatch, Beads, Git
from taskloop.domain.asks import specs as askspecs
from taskloop.domain.asks.spec import AskSpec
from taskloop.domain.land.matchers import Push
from taskloop.stores.runlog import RunLog


class PrConfig(Protocol):
    @property
    def base(self) -> str: ...
    @property
    def land(self) -> list[str]: ...


class PrHost(Protocol):
    """What the PR land reads of the engine: git and the Spawner for gh, the bead and its fence, the log, the fetch, the stop."""

    landed_sha: str  # set the moment the PR is seen merged
    task_branch: str

    @property
    def bead(self) -> BeadId: ...
    @property
    def cfg(self) -> PrConfig: ...
    @property
    def spawner(self) -> Runs: ...
    @property
    def log(self) -> RunLog: ...
    @property
    def run_dir(self) -> Path: ...
    @property
    def git(self) -> Git: ...
    @property
    def wt(self) -> str: ...
    @property
    def store(self) -> Beads: ...
    @property
    def claim(self) -> fence.Claim: ...
    @property
    def steps(self) -> OutcomeSteps: ...
    @property
    def checkout(self) -> FetchCheckout: ...
    def blocked_for(self, why: str, kind: str, *, spec: AskSpec | None = ...) -> Exception: ...


class PrLand:
    def __init__(self, host: PrHost) -> None:
        self.e = host

    def forge(self, remote: str) -> Forge:
        e = self.e
        return Forge(Cmds(e.spawner, e.log, e.wt, e.run_dir), e.git, e.wt, e.cfg.base.partition("/")[2] or e.cfg.base, remote=remote)

    def remote(self) -> str:
        want = target(self.e.cfg.land)
        return want[0] if want else "origin"

    def number(self) -> int:
        shown = self.e.store.show(self.e.bead)
        return pr_waited_on(shown.metadata) if shown else 0

    def settled(self) -> str:
        """Before a land starts: the PR this bead waits on, if any. -> the merge commit (merged), "" (no PR, or the work moved on since:
        land again); raises the owner's ask while the PR is open unchanged, or closed unmerged."""
        e = self.e
        number = self.number()
        if not number:
            return ""
        try:
            pr = self.forge(self.remote()).view(number)
        except Stop as stop:
            raise e.blocked_for(f"failed: {stop.why}", "FAULT_LAND") from None
        if pr.state == MERGED:
            return self.merged(pr)
        if pr.state == CLOSED:
            self.forget()
            raise e.blocked_for(f"PR #{pr.number} was closed without a merge: {pr.url}", "ASK_DECISION",
                                spec=askspecs.pr_closed(e.bead, pr.number, pr.url))
        if e.git.rev_parse(e.wt, "HEAD") == pr.head_oid:
            raise self.waiting(pr)
        return ""

    def merged(self, pr: Pr) -> str:
        """The PR's own merge commit, fetched so the receipt can see it on the base."""
        e = self.e
        rc, tail = e.checkout.fetch()
        if rc:
            raise e.blocked_for(f"paused: fetch after the PR #{pr.number} merge failed; the next run records the land\n{tail.strip()}",
                                "PAUSE_NETWORK")
        if not pr.merge_sha:
            raise e.blocked_for(f"failed: PR #{pr.number} is merged but the forge names no merge commit", "FAULT_LAND")
        e.landed_sha = pr.merge_sha
        e.steps.outcome("landed", pr.merge_sha[:12])
        return pr.merge_sha

    def waiting(self, pr: Pr) -> Exception:
        e = self.e
        return e.blocked_for(f"PR #{pr.number} is open, waiting for the owner to merge it: {pr.url}", "ASK_DECISION",
                             spec=askspecs.pr_open(e.bead, pr.number, pr.url))

    def push(self, st: Land, gate_pass: GatePass) -> str | Problem | Next:
        """In the lock, where the push would be: send the gated tip to the task branch and open (or update) its PR. -> the merge commit
        when that PR is already merged; otherwise raises the owner's ask."""
        e = self.e
        problem = stale(e.git, e.wt, e.cfg.base, gate_pass)
        if problem is not None:
            return problem
        fence.check(e.store, e.claim)
        sha, remote, branch = e.git.rev_parse(e.wt, "HEAD"), self.remote(), e.task_branch
        done = e.git.push_lease(e.wt, remote, f"{sha}:refs/heads/{branch}")
        if not done.ok:
            kind = "PAUSE_NETWORK" if Push.transient(done.output) else "FAULT_LAND"
            raise e.blocked_for(f"{'paused' if kind == 'PAUSE_NETWORK' else 'failed'}: pushing {branch} to {remote} for the PR failed; "
                                f"the branch is kept\n{failure(done.output, e.run_dir, branch)}", kind)
        forge = self.forge(remote)
        try:
            pr = forge.find(branch, sha) or forge.create(branch, self.title(sha), self.body())
        except Stop as stop:
            raise e.blocked_for(f"failed: {stop.why}", "FAULT_LAND") from None
        if pr.state == MERGED:
            return self.merged(pr)
        e.store.update(e.bead, BeadPatch(set_metadata={PR_NUMBER: str(pr.number), PR_URL: pr.url}, if_assignee=fence.guard(e.claim)))
        raise self.waiting(pr)

    def title(self, sha: str) -> str:
        rows = self.e.git.log(self.e.wt, [sha], limit=1)
        return rows[0].subject if rows else self.e.task_branch

    def body(self) -> str:
        return f"Opened by task-loop for {self.e.bead}. The engine does not merge it: the bead closes once you do."

    def forget(self) -> None:
        """The land is over (recorded) or its PR is dead: the bead no longer waits on a PR."""
        e = self.e
        if self.number():
            e.store.update(e.bead, BeadPatch(unset_metadata=[PR_NUMBER, PR_URL], if_assignee=fence.guard(e.claim)))

    done = forget
