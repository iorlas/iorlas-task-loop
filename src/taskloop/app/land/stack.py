"""`tl land-stack`: deliver an existing PR, a branch, or a stack of branches, lowest first, as one run on the board (mode stage:land-stack).

Per item: push the branch and see it on the remote, open its PR when it has none, merge it under the repo's land lock with
--match-head-commit, check the forge says MERGED, and (still under the lock) record `tl land` with that PR's own merge commit. A PR
it replaces is closed only after the replacement merged. After the last, bd's Dolt data is synced. The first failure ends the run with
the failing command's exit code and leaves every later item untouched. Every command is a row of the run's log (Cmds)."""
import argparse
import contextlib
import os
import threading
import time
from collections.abc import Callable, Generator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tlkernel import check_files
from tlkernel import log as rec
from tlkernel.beadsport import Beads, DoltPush
from tlkernel.branches import TASK
from tlkernel.env import Env
from tlkernel.forge import CLOSED, MERGED, OPEN, Pr, StackItem
from tlkernel.gitport import Git
from tlkernel.identity import Identity
from tlkernel.ids import BeadId
from tlkernel.locator import RunLocator
from tlkernel.paths import ConfigDir
from tlkernel.profile_changes import ProfileChange
from tlkernel.queue_doc import QueueDoc
from tlkernel.slots import MissingRemote

from taskloop.adapters import landlock
from taskloop.app.land import cleanup
from taskloop.app.land.cmds import Cmds, Runs, Stop
from taskloop.app.land.forge import Forge
from taskloop.app.land.phases import phase
from taskloop.app.land.profile_change import diff_sha, owner_refusal
from taskloop.app.land.queue_land import Queued, QueueLand
from taskloop.app.land.stackgate import StackGate
from taskloop.app.land.treecheck import Tested, TreeGuard
from taskloop.domain.land.matchers import no_dolt_remote
from taskloop.stores.api import Doc
from taskloop.stores.bundle import Stores
from taskloop.stores.real import real_stores
from taskloop.stores.runlog import RunLog

MODE = "stage:land-stack"
LOCK_BUSY = 75
HEAD_TRIES = 2  # a head that moved after the gate is judged again once: the owner pushed a fix while the gate ran


class HeadMoved(Stop):
    """The PR's head is no longer the commit the gate judged: nothing is merged."""


def lock_path(home: ConfigDir, git: Git, repo: str) -> Path:
    """The repo's land lock: the one the engine lands under."""
    try:
        url = git.remote_url(repo, "origin")
    except MissingRemote:
        url = ""
    return landlock.land_lock_path(home, url or repo)


class Stack:
    def __init__(self, forge: Forge, cmds: Cmds, log: RunLog, git: Git, repo: str, lock: Path, record: Callable[[str, str], int],
                 sync: Callable[[], DoltPush], owner: str, session: str, gate: StackGate, beads: Beads, wait_min: float | None = None,
                 named: Callable[[str], None] = lambda _bead: None,
                 is_slot: Callable[[str], bool] = lambda _path: False, slot_base: str = "", *, cfg: ConfigDir,
                 profile_change: str | None = None, jobs: int = 1, assert_trees: bool = False, queue: bool = False) -> None:
        self.forge, self.cmds, self.log, self.git, self.repo, self.lock = forge, cmds, log, git, repo, lock
        self.record, self.sync, self.owner, self.session, self.wait_min = record, sync, owner, session, wait_min
        self.gate, self.named = gate, named  # named(bead): the run's manifest learns each bead
        self.beads, self.failure_reason = beads, ""
        self.is_slot, self.cfg = is_slot, cfg
        self.slot_base = slot_base or f"origin/{forge.base}"
        self.profile_change = profile_change
        self.jobs = jobs  # gates run at once before the serial merges
        self.assert_trees = assert_trees  # dark: judge the tested tree against the landed one (treecheck.py); off until the queue rolls out
        self.queue = queue  # dark: land through the merge queue (queue_land.py); the CLI turns it on only at the rollout
        self.trees = TreeGuard(cmds, git, gate.stores, repo, f"{forge.remote}/{forge.base}")
        self.recorded = 0
        self.synced = False  # bd sync was tried
        self.last = ""  # the merge commit of the last item delivered
        self.pending: list[rec.LandCleanup] = []

    @property
    def queue_doc(self) -> Doc[QueueDoc]:
        return self.gate.stores.queue.of(check_files.repo_key(self.git, self.repo))

    def run(self, items: list[StackItem]) -> int:
        """Deliver the items in order; -> 0, or the exit code of the first failure."""
        self.log.emit(rec.RunStart(worktree=self.repo, mode=MODE, owner=self.owner, session=self.session,
                                   started_because="first"))
        rc = 0
        try:
            self.validate_beads(items)
            self.prewarm(items)
            if self.queue:
                QueueLand(self).run(items)
            else:
                for item in items:
                    self.item(item)
            self.sync_bd()
        except Stop as stop:
            rc = stop.rc
            self.failure_reason = stop.why
            self.log.warn(stop.why)
            if self.recorded and not self.synced:  # what landed keeps its records safe on the remote; the original exit code stays
                with contextlib.suppress(Stop):
                    self.sync_bd()
        finally:
            for row in self.pending:
                cleanup.retry(self.git, self.log, row, self.is_slot, self.slot_base, cfg=self.cfg)
        return rc

    def validate_beads(self, items: list[StackItem]) -> None:
        """Every explicitly named bead must exist before any item can push or merge."""
        for bead in dict.fromkeys(item.bead for item in items if item.bead):
            try:
                found = self.beads.show(BeadId(bead))
            except Exception as e:
                raise Stop(1, f"cannot verify bead {bead}: {e}") from None
            if found is None:
                raise Stop(1, f"unknown bead {bead}: no issue found")

    def prewarm(self, items: list[StackItem]) -> None:
        """Gate the open items at once, then merge them one by one as before: the checks of independent PRs do not wait for each other.
        Only receipts come of it; the serial loop still asks the gate for each item, finds the pass (or carries it over the base the
        earlier merges moved) and merges under the land lock. A failure here is not reported: the loop's own gate says it."""
        if self.jobs < 2 or len(items) < 2 or self.profile_change is not None:
            return
        try:
            self.forge.fetch()
            todo: list[tuple[str, str]] = []
            for item in items:
                branch, oid, pr = self.resolve(item)
                if (pr is None or pr.state == OPEN) and self.gate.needs_run(oid):
                    todo.append((branch, oid))
        except Stop:
            return
        if len(todo) < 2:
            return
        git_lock = threading.Lock()

        def warm(job: tuple[str, str]) -> int:
            return self.gate.warm(job[1], git_lock)
        with ThreadPoolExecutor(max_workers=min(self.jobs, len(todo))) as pool:
            for (branch, oid), code in zip(todo, pool.map(warm, todo), strict=True):
                self.log.note(f"gated {branch} ({oid[:12]}) ahead of the merges: exit {code}")

    def item(self, item: StackItem) -> None:
        """Deliver one item. A head that moved while its gate ran is read and judged again (once), never merged unjudged."""
        for attempt in range(1, HEAD_TRIES + 1):
            try:
                return self.deliver(item)
            except HeadMoved as moved:
                if attempt == HEAD_TRIES:
                    raise
                self.log.note(f"{moved.why}: judging the new head")

    def deliver(self, item: StackItem, queued: Queued | None = None) -> None:
        branch, oid, pr = self.resolve(item)
        if not item.bead and branch.startswith(TASK):  # a task branch names its bead
            item = item.replace(bead=branch.removeprefix(TASK))
        self.log.stamp["bead"] = item.bead
        self.named(item.bead)
        sid = self.log.next_id("s")
        name = f"land:{branch}"
        self.log.emit(rec.StepStart(id=sid, step=name, text=f"land {branch}"))
        tested = None
        try:
            if pr is None or pr.state == OPEN:  # a PR already merged or closed is prepare's to judge
                with phase(self.log, "fetch"):
                    self.forge.fetch()  # the judged commit's profile, and the base as origin has it now
                if queued is not None:
                    tested = self.crossing(branch, oid, queued)
                else:
                    with phase(self.log, "gate"):
                        base = self.gate.require(branch, oid, profile_change=self.profile_change)
                    if self.assert_trees:
                        tested = Tested(parent=base, parent_tree=self.trees.tree(base), tree=self.trees.tree(oid))
                    if self.profile_change is not None:
                        self.audit_profile(branch, oid, base)
            pr = self.prepare(item, branch, oid, pr)
            head = pr.head_oid
            sha = self.merged(item, pr, head, tested)
        except Stop as stop:
            self.log.emit(rec.StepEnd(id=sid, step=name, outcome="failed", detail=stop.why))
            raise
        self.log.emit(rec.StepEnd(id=sid, step=name, outcome="landed", detail=sha[:12]))
        self.last = sha
        self.after(item, pr, branch, head, sha)

    def crossing(self, branch: str, oid: str, queued: Queued) -> Tested:
        """The queue gated Q(N) at Q(N-1): the head must still be the one it judged; its passes cross to main (`Carry.queue_carried`) and
        the merge is asserted against that tree (merged -> TreeGuard)."""
        if oid != queued.head:
            raise HeadMoved(1, f"{branch}: head moved from {queued.head[:12]} to {oid[:12]} while it was queued")
        parent = self.git.rev_parse(self.repo, f"{queued.q}^")
        with phase(self.log, "carry"):
            self.gate.carry_queue(queued.q, parent)
        return Tested(parent=parent, parent_tree=self.trees.tree(parent), tree=queued.tree)

    def audit_profile(self, branch: str, tip: str, base: str) -> None:
        """One atomic row per explicitly authorized item, after evidence and before its push or merge."""
        assert self.profile_change is not None
        digest = self.cmds.port(f"git diff {base} {tip} -- .task-loop.json",
                                lambda: diff_sha(self.git, self.repo, base, tip))
        try:
            self.gate.stores.profile_changes.append(ProfileChange(
                t=time.time(), owner_text=self.profile_change, repo=self.repo, branch=branch,
                tip=tip, base=base, diff_sha=digest, pid=os.getpid()))
        except OSError as err:
            raise Stop(1, f"cannot append profile change audit: {err}") from None

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
            with phase(self.log, "push"):  # the repo's pre-push judge runs inside git push
                self.forge.push(branch, oid)
        if pr is None:
            with phase(self.log, "pr"):
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

    def merged(self, item: StackItem, pr: Pr, head: str, tested: Tested | None = None) -> str:
        """Under the land lock: merge the head we saw, see MERGED, record the PR's own merge commit. -> that commit. With `tested`, the
        merge is refused unless it lands the tested tree, and a merge that did not is an incident (treecheck.py)."""
        with self.locked():
            main_before = ""
            if pr.state == OPEN and tested is not None:
                self.forge.fetch()
                main_before = self.git.rev_parse(self.repo, self.trees.main_ref)
                if why := self.trees.refuse(head, tested):
                    raise Stop(1, f"PR #{pr.number} not merged: {why}")
            if pr.state == OPEN:
                now = self.forge.view(pr.number)
                if now.state == OPEN and now.head_oid != head:  # the gate judged `head`: the forge would refuse this later
                    raise HeadMoved(1, f"PR #{pr.number} head moved from {head[:12]} to {now.head_oid[:12]} while it was gated")
                with phase(self.log, "merge"):
                    self.forge.merge(pr, head)
                    pr = self.forge.view(pr.number)
            if pr.state != MERGED or not pr.merge_sha:
                raise Stop(1, f"PR #{pr.number} is {pr.state} after the merge (merge commit {pr.merge_sha or 'none'}): not recorded")
            if tested is not None and main_before:
                self.forge.fetch()
                self.trees.verify(tested, main_before, pr.merge_sha, pr.number, item.bead)
            if item.bead:
                with phase(self.log, "record"):
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
        sid = self.log.next_id("s")
        self.log.emit(rec.StepStart(id=sid, step="land:lock-wait"))
        try:
            with landlock.os_lock(self.lock, holder, self.waiting, None if self.wait_min is None else self.wait_min * 60):
                self.log.emit(rec.StepEnd(id=sid, step="land:lock-wait", outcome="done", wait_seconds=time.monotonic() - t0))
                self.log.emit(rec.Lock(what="land", holder=holder))
                try:
                    yield
                finally:
                    self.log.emit(rec.Unlock(what="land", secs=time.monotonic() - t0))
        except TimeoutError as e:
            self.log.emit(rec.StepEnd(id=sid, step="land:lock-wait", outcome="failed", wait_seconds=time.monotonic() - t0))
            raise Stop(LOCK_BUSY, f"gave up waiting for the land lock (held by {e})") from None

    def after(self, item: StackItem, pr: Pr, branch: str, head: str, sha: str) -> None:
        """Landed and recorded: persist cleanup before closing a replaced PR, which can fail independently."""
        with phase(self.log, "cleanup"):
            self.tidy(branch, head, sha)
        if item.supersedes:
            old = self.forge.view(item.supersedes)
            if old.state == OPEN:
                self.forge.close(old.number, f"Superseded by #{pr.number}, merged as {sha[:12]}.")
            else:
                self.log.note(f"PR #{old.number} is {old.state}: left as it is")

    def tidy(self, branch: str, head: str, sha: str) -> None:
        """Persist cleanup now; keep --repo alive until every item and bd sync finish.
        Cleanup itself uses the main checkout so removing --repo cannot strand branch deletion or later retries."""
        repo = str(Path(self.git.common_dir(self.repo)).parent)
        row = cleanup.record(self.log, repo, branch, head, sha)
        self.pending.append(row.replace(bead=self.log.stamp["bead"]))

    def sync_bd(self) -> None:
        """`bd sync --no-adopt` (pull, then push) through the store; a remote bd does not have is a quiet no-op."""
        self.synced = True
        cid = self.log.next_id("c")
        self.log.emit(rec.CmdStart(id=cid, text="bd sync --no-adopt", cwd=self.repo))
        try:
            done = self.sync()
        except Exception as e:  # bd itself failed
            done = DoltPush(1, str(e))
        self.log.emit(rec.CmdEnd(id=cid, exit=done.code, out=done.text))
        if done.code and not (done.code == 1 and no_dolt_remote(done.text)):
            raise Stop(done.code, f"bd sync failed (exit {done.code}): {done.text.strip()}")


def item_of(text: str, beads: dict[str, str], supersedes: dict[str, str]) -> StackItem:
    """An argument: a PR number or url, or a branch name. `beads` and `supersedes` are keyed by that same text."""
    tail = text.rstrip("/").rpartition("/pull/")[2] if "/pull/" in text else text
    pr = int(tail) if tail.isdigit() else 0
    old = supersedes.get(text, "")
    return StackItem(branch="" if pr else text, pr=pr, bead=beads.get(text, ""), supersedes=int(old) if old else 0)


def pairs(values: list[str], flag: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for v in values:
        key, eq, val = v.partition("=")
        if not eq or not key or not val:
            raise SystemExit(f"land-stack: {flag} wants ITEM=VALUE, got {v!r}")
        out[key] = val
    return out


def run_stack(a: argparse.Namespace, who: Identity, git: Git, spawner: Runs, store: Beads,
              tl: list[str], *, record: Callable[[str, str, BeadId, str, str], int],
              slot: Callable[[str, str], str], slot_base: Callable[[str], str],
              runlog: Callable[[Stores, str], RunLog],
              finish: Callable[[str, float, str, str, bool], object], env: Env | None = None) -> tuple[int, list[str]]:
    """Run the stack and return its exit code and final output lines."""
    env = env or Env()
    profile_change = a.profile_change
    if why := owner_refusal(profile_change, env):
        return 2, [why]
    repo = str(Path(a.repo).resolve())
    beads, old = pairs(a.bead, "--bead"), pairs(a.supersede, "--supersede")
    for flag, given in (("--bead", beads), ("--supersede", old)):
        for key in given:
            if key not in a.items:
                raise SystemExit(f"land-stack: {flag} {key}=... matches no item; the items given are: {', '.join(a.items)}")
    items = [item_of(t, beads, old) for t in a.items]
    locator = RunLocator(who.config)
    run = locator.create(repo, "", time.time(), mode=MODE, owner=who.actor, session=who.session).run  # the board finds a run through it
    stores = real_stores(who.config)
    log = runlog(stores, run)
    cmds = Cmds(spawner, log, repo, who.config.run_dir(run))
    lock = lock_path(who.config, git, repo)
    forge = Forge(cmds, git, repo, a.base, a.method)
    slot_repo = next((co.path for co in git.checkouts(repo) if co.main), repo)

    def landed(bead: str, sha: str) -> int:
        """`tl land` and its LANDED row (what `tl trace BEAD`, the board's landings and the close guard read): the one writer."""
        return record(repo, f"origin/{a.base}", BeadId(bead), sha, f"{MODE}: merged as {sha[:12]}")

    stack = Stack(forge, cmds, log, git, repo, lock, landed, store.dolt_push, who.actor, who.session,
                  StackGate(cmds, git, stores, repo, f"origin/{a.base}", tl, env), store, a.wait_min,
                  lambda bead: locator.add_bead(run, bead),
                  lambda path: bool(slot(slot_repo, path)), slot_base(slot_repo),
                  cfg=who.config, profile_change=profile_change, jobs=a.jobs)
    rc = 1
    try:
        rc = stack.run(items)
    finally:  # every exit leaves a terminal state: done, or failed (a raise included)
        finish(run, time.time(), f"{len(items)} delivered" if rc == 0 else stack.failure_reason or f"exit {rc}",
               stack.last, rc == 0)
    lines = [f"land-stack: {stack.failure_reason}"] if stack.failure_reason else []
    lines.append(f"land-stack {'landed ' + str(len(items)) if rc == 0 else 'stopped, exit ' + str(rc)} (run {run})")
    return rc, lines
