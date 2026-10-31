"""`tl land-stack`: deliver an existing PR, a branch, or a stack of branches, lowest first, as one run on the board (mode stage:land-stack).

Per item: push the branch and see it on the remote, open its PR when it has none, merge it under the repo's land lock with
--match-head-commit, check the forge says MERGED, and (still under the lock) record `tl land` with that PR's own merge commit. A PR
it replaces is closed only after the replacement merged. After the last, bd's Dolt data is synced. The first failure ends the run with
the failing command's exit code and leaves every later item untouched. Every command is a row of the run's log (Cmds)."""
import contextlib
import time
from collections.abc import Callable, Generator
from pathlib import Path

from taskloop.adapters import landlock
from taskloop.app.land.cmds import Cmds, Stop
from taskloop.app.land.forge import Forge
from taskloop.app.land.stackgate import StackGate
from taskloop.contracts import log as rec
from taskloop.contracts.enums import Outcome, WhyCode
from taskloop.contracts.forge import CLOSED, MERGED, OPEN, Pr, StackItem
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import DoltPush, Git
from taskloop.domain.land.matchers import no_dolt_remote
from taskloop.stores.runlog import RunLog

MODE = "stage:land-stack"
LOCK_BUSY = 75
TASK = "task/"


def lock_path(home: ConfigDir, git: Git, repo: str) -> Path:
    """The repo's land lock: the one the engine lands under."""
    return landlock.land_lock_path(home, git.remote_url(repo, "origin") or repo)


class Stack:
    def __init__(self, forge: Forge, cmds: Cmds, log: RunLog, git: Git, repo: str, lock: Path, record: Callable[[str, str], int],
                 sync: Callable[[], DoltPush], owner: str, session: str, gate: StackGate, wait_min: float | None = None,
                 named: Callable[[str], None] = lambda _bead: None) -> None:
        self.forge, self.cmds, self.log, self.git, self.repo, self.lock = forge, cmds, log, git, repo, lock
        self.record, self.sync, self.owner, self.session, self.wait_min = record, sync, owner, session, wait_min
        self.gate, self.named = gate, named  # named(bead): the run's manifest learns each bead
        self.recorded = 0
        self.synced = False  # bd sync was tried
        self.last = ""  # the merge commit of the last item delivered

    def run(self, items: list[StackItem]) -> int:
        """Deliver the items in order; -> 0, or the exit code of the first failure."""
        self.log.emit(rec.RunStart(worktree=self.repo, mode=MODE, owner=self.owner, session=self.session,
                                   started_because="first"))
        rc, why = 0, f"{len(items)} delivered"
        try:
            for item in items:
                self.item(item)
            self.sync_bd()
        except Stop as stop:
            rc, why = stop.rc, stop.why
            self.log.warn(why)
            if self.recorded and not self.synced:  # what landed keeps its records safe on the remote; the original exit code stays
                with contextlib.suppress(Stop):
                    self.sync_bd()
        self.log.emit(rec.Close(outcome=Outcome.LANDED if rc == 0 else Outcome.FAILED, why_code=None if rc == 0 else WhyCode.FAILED,
                                sha=self.last, why=why))
        return rc

    def item(self, item: StackItem) -> None:
        branch, oid, pr = self.resolve(item)
        if not item.bead and branch.startswith(TASK):  # a task branch names its bead
            item = item.replace(bead=branch.removeprefix(TASK))
        self.log.stamp["bead"] = item.bead
        self.named(item.bead)
        sid = self.log.next_id("s")
        name = f"land:{branch}"
        self.log.emit(rec.StepStart(id=sid, step=name, text=f"land {branch}"))
        try:
            if pr is None or pr.state == OPEN:  # a PR already merged or closed is prepare's to judge
                if self.gate.steps():
                    self.forge.fetch()  # the base and the head as origin has them now
                self.gate.require(branch, oid)
            pr = self.prepare(item, branch, oid, pr)
            head = pr.head_oid
            sha = self.merged(item, pr, head)
        except Stop as stop:
            self.log.emit(rec.StepEnd(id=sid, step=name, outcome="failed", detail=stop.why))
            raise
        self.log.emit(rec.StepEnd(id=sid, step=name, outcome="landed", detail=sha[:12]))
        self.last = sha
        self.after(item, pr, branch, head, sha)

    def resolve(self, item: StackItem) -> tuple[str, str, Pr | None]:
        """(branch, the oid to deliver, its PR if there is one): a PR is the forge's word, a branch is this clone's."""
        if item.pr:
            pr = self.forge.view(item.pr)
            return pr.head_ref, pr.head_oid, pr
        oid = self.cmds.port(f"git rev-parse --verify refs/heads/{item.branch}",
                             lambda: self.git.rev_parse(self.repo, f"refs/heads/{item.branch}")) or self.from_remote(item.branch)
        return item.branch, oid, self.forge.find(item.branch, oid)

    def from_remote(self, branch: str) -> str:
        """A branch with no local twin: the oid origin shows for it, fetched so the clone has it."""
        oid = self.forge.remote_oid(branch)
        if not oid:
            raise Stop(1, f"no branch {branch}: not local (git rev-parse --verify refs/heads/{branch}) and not on {self.forge.remote} "
                          f"(git ls-remote {self.forge.remote} refs/heads/{branch})")
        self.forge.fetch()
        if not self.cmds.port(f"git rev-parse --verify {oid[:12]}", lambda: self.git.rev_parse(self.repo, oid)):
            raise Stop(1, f"{branch} is at {oid[:12]} on {self.forge.remote} but git fetch {self.forge.remote} did not bring it")
        return oid

    def prepare(self, item: StackItem, branch: str, oid: str, pr: Pr | None) -> Pr:
        """The branch pushed and verified, the PR open and aimed at the base."""
        if pr is not None and pr.state == CLOSED:
            raise Stop(1, f"PR #{pr.number} ({branch}) is closed, not merged: nothing to deliver")
        if pr is not None and pr.state == MERGED:
            return pr
        if not item.pr:
            self.forge.push(branch, oid)
        if pr is None:
            pr = self.forge.create(branch, self.title(branch, oid), f"Delivered by `tl land-stack`{self.bead_note(item)}.")
        elif not item.pr:
            pr = self.forge.view(pr.number)  # the push may have moved its head
        if pr.head_oid != oid:
            raise Stop(1, f"PR #{pr.number} head is {pr.head_oid[:12]}, not the {oid[:12]} that was pushed")
        if pr.base_ref != self.forge.base:
            self.forge.retarget(pr)
        return pr

    def title(self, branch: str, oid: str) -> str:
        rows = self.git.log(self.repo, [oid], limit=1)
        return rows[0].subject if rows else branch

    @staticmethod
    def bead_note(item: StackItem) -> str:
        return f" for {item.bead}" if item.bead else ""

    def merged(self, item: StackItem, pr: Pr, head: str) -> str:
        """Under the land lock: merge the head we saw, see MERGED, record the PR's own merge commit. -> that commit."""
        with self.locked():
            if pr.state == OPEN:
                self.forge.merge(pr, head)
                pr = self.forge.view(pr.number)
            if pr.state != MERGED or not pr.merge_sha:
                raise Stop(1, f"PR #{pr.number} is {pr.state} after the merge (merge commit {pr.merge_sha or 'none'}): not recorded")
            if item.bead:
                self.forge.fetch()
                rc = self.record(item.bead, pr.merge_sha)
                if rc:
                    raise Stop(rc, f"tl land {item.bead} {pr.merge_sha[:12]} was refused (exit {rc})")
                self.recorded += 1
            else:
                self.log.note(f"PR #{pr.number} merged as {pr.merge_sha[:12]}; no bead named, no land recorded")
            return pr.merge_sha

    def waiting(self, who: str) -> None:
        self.log.note(f"waiting for the land lock (held by {who})")

    @contextlib.contextmanager
    def locked(self) -> Generator[None]:
        holder = f"land-stack {self.session or self.owner}"
        t0 = time.monotonic()
        try:
            with landlock.os_lock(self.lock, holder, self.waiting, None if self.wait_min is None else self.wait_min * 60):
                self.log.emit(rec.Lock(what="land", holder=holder))
                try:
                    yield
                finally:
                    self.log.emit(rec.Unlock(what="land", secs=time.monotonic() - t0))
        except TimeoutError as e:
            raise Stop(LOCK_BUSY, f"gave up waiting for the land lock (held by {e})") from None

    def after(self, item: StackItem, pr: Pr, branch: str, head: str, sha: str) -> None:
        """Landed and recorded: the replaced PR is closed, then the local branch and worktree go (only while at the oid that landed)."""
        if item.supersedes:
            old = self.forge.view(item.supersedes)
            if old.state == OPEN:
                self.forge.close(old.number, f"Superseded by #{pr.number}, merged as {sha[:12]}.")
            else:
                self.log.note(f"PR #{old.number} is {old.state}: left as it is")
        self.tidy(branch, head)

    def tidy(self, branch: str, head: str) -> None:
        """Delete the local task branch and its worktree after a verified land, the compare-oid way: a branch that moved since is kept.
        The remote branch is the forge's (delete on merge); gone or not, it is not a failure."""
        local = self.git.rev_parse(self.repo, f"refs/heads/{branch}")
        if not local:
            return
        if local != head:
            self.log.note(f"local {branch} is at {local[:12]}, not the {head[:12]} that landed: kept")
            return
        for co in self.git.checkouts(self.repo):
            if co.branch != branch:
                continue
            if co.main:
                self.log.note(f"{branch} is checked out in the main checkout: kept")
                return
            if self.cmds.row(f"git worktree remove {co.path}", lambda p=co.path: self.drop_worktree(p)):
                self.log.note(f"worktree {co.path} stays (not clean?): {branch} kept")
                return
        self.cmds.row(f"git update-ref -d refs/heads/{branch} {head[:12]}", lambda: self.git.delete_branch_at(self.repo, branch, head))

    def drop_worktree(self, path: str) -> None:
        why = self.git.remove_worktree_why(self.repo, path)
        if why:
            raise RuntimeError(why)

    def sync_bd(self) -> None:
        """`bd sync --no-adopt` (pull, then push) through the store; a remote bd does not have is a quiet no-op."""
        self.synced = True
        cid = self.log.next_id("c")
        self.log.emit(rec.CmdStart(id=cid, text="bd sync --no-adopt", cwd=self.repo))
        try:
            done = self.sync()
        except Exception as e:  # bd itself failed
            done = DoltPush(1, str(e))
        self.log.emit(rec.CmdEnd(id=cid, exit=done.code, out=done.text[-600:]))
        if done.code and not (done.code == 1 and no_dolt_remote(done.text)):
            raise Stop(done.code, f"bd sync failed (exit {done.code}): {done.text.strip()[-300:]}")
