"""Carry check passes across base moves and clean up after recorded lands, keeping failures retryable."""
import hashlib
from collections.abc import Callable
from pathlib import Path

from tlgate import authorization
from tlgate.cache import satisfied
from tlgate.domain.specs import repo_check
from tlkernel import config, scratch
from tlkernel import log as rec
from tlkernel.checks import PassRecord
from tlkernel.env import Env
from tlkernel.gitport import Git
from tlkernel.ids import TreeSha
from tlkernel.locator import RunLocator
from tlkernel.paths import ConfigDir
from tlkernel.runkey import BaseSha, RunKey
from tlslots.effects import Effects
from tlslots.engine_lock import engine_busy
from tlslots.reset import leave_slot

from taskloop.app.land.cmds import Cmds
from taskloop.stores.bundle import Stores
from taskloop.stores.real import real_stores
from taskloop.stores.runlog import RunLog


def remote_oid(git: Git, repo: str, remote: str, branch: str) -> str:
    """Snapshot the task ref before the merge check/push, so cleanup never adopts work pushed later."""
    return next((ref.oid for ref in git.ls_remote(repo, remote, f"refs/heads/{branch}")
                 if ref.name == f"refs/heads/{branch}"), "")


def tidy_local(git: Git, repo: str, log: RunLog, branch: str, head: str,
               is_slot: Callable[[str], bool] = lambda _path: False, base: str = "origin/main", *, cfg: ConfigDir, fx: Effects) -> str:
    """The stack and engine share this local cleanup. An empty result means gone; otherwise it says why it stays."""
    local = git.rev_parse(repo, f"refs/heads/{branch}")
    if not local:
        return ""
    if local != head:
        return f"local {branch} is at {local[:12]}, not the {head[:12]} that landed: kept"
    why = _tidy_checkouts(git, repo, log, branch, head, is_slot, base, cfg, fx=fx)
    if why:
        return why
    git.delete_branch_at(repo, branch, head)
    return ""


def _tidy_checkouts(git: Git, repo: str, log: RunLog, branch: str, head: str,
                    is_slot: Callable[[str], bool], base: str, cfg: ConfigDir, *, fx: Effects) -> str:
    """Release matching checkouts, stopping at the first reason to keep the branch."""
    for co in git.checkouts(repo):
        if co.branch != branch:
            continue
        if co.main:
            return f"{branch} is checked out in the main checkout: kept"
        busy = engine_busy(cfg, co.path, fx=fx)
        if busy:
            return f"worktree {co.path} stays: {branch} kept: {busy}"
        # A ref can move while the checkout list is being read. Never remove that checkout's newer work.
        if git.rev_parse(repo, f"refs/heads/{branch}") != head:
            return f"local {branch} moved before worktree removal: kept"
        if is_slot(co.path):
            if not leave_slot(cfg, git, co.path, base, branch, fx=fx):
                return f"slot {co.path} has unsaved work or changed branch: {branch} kept"
            log.note(f"left slot {co.path} detached at {base}")
            continue
        why = git.remove_worktree_why(repo, co.path)
        if why:
            return f"worktree {co.path} stays: {branch} kept: {why}"
        log.note(f"removed worktree {co.path}")
    return ""


def previous(home: ConfigDir, bead: str, repo: str, branch: str, sha: str) -> rec.LandCleanup | None:
    """A repeated landing receipt retains the first run's leases, even if a branch has since moved."""
    found: rec.LandCleanup | None = None
    stores = real_stores(home)
    for bundle in RunLocator(home).of_bead(bead):
        for item in stores.run_log(bundle.run).read_from(0).items:
            row = item.rec
            if isinstance(row, rec.LandCleanup) and (row.repo, row.branch, row.sha) == (repo, branch, sha):
                found = row
    return found


def record(log: RunLog, repo: str, branch: str, head: str, sha: str, remote: str = "", remote_oid: str = "",
           prior: rec.LandCleanup | None = None) -> rec.LandCleanup:
    """Persist both the receipt and the retry inputs before attempting cleanup. PR lands pass no remote."""
    log.emit(rec.LandReceipt(repo=repo, branch=branch, head=head, sha=sha))
    row = prior.replace(t=0, run_id="", host="") if prior else rec.LandCleanup(
        repo=repo, branch=branch, head=head, sha=sha, remote=remote, remote_oid=remote_oid,
        remote_outcome="pending" if remote and remote_oid else "skipped")
    log.emit(row)
    return row


def retry(git: Git, log: RunLog, row: rec.LandCleanup, is_slot: Callable[[str], bool] = lambda _path: False,
          base: str = "origin/main", *, cfg: ConfigDir, fx: Effects) -> rec.LandCleanup:
    """Retry a logged cleanup with its original oids, never with freshly observed tips. The land remains successful."""
    local, remote = row.local_outcome, row.remote_outcome
    detail: list[str] = []
    if remote == "pending":
        try:
            git.delete_remote_at(row.repo, row.remote, f"refs/heads/{row.branch}", row.remote_oid)
            remote = "gone"
        except Exception as err:  # network trouble or a moved ref: the original lease remains retryable
            detail.append(f"remote: {err}")
    if local == "pending":
        try:
            why = tidy_local(git, row.repo, log, row.branch, row.head, is_slot, base, cfg=cfg, fx=fx)
            if why:
                detail.append(why)
            else:
                local = "gone"
        except Exception as err:
            detail.append(f"local: {err}")
    done = row.replace(local_outcome=local, remote_outcome=remote, detail="; ".join(detail))
    log.emit(done)
    if detail:
        log.note(f"landed {row.sha[:12]}; cleanup pending: {done.detail}")
    return done


def retry_logged(git: Git, log: RunLog, is_slot: Callable[[str], bool] = lambda _path: False, base: str = "origin/main", *,
                 cfg: ConfigDir, fx: Effects) -> None:
    """At the end of an engine run, after the trace's last checkout read, retry its latest cleanup rows."""
    latest: dict[tuple[str, str, str], rec.LandCleanup] = {}
    for item in log.log.read_from(0).items:
        row = item.rec
        if isinstance(row, rec.LandCleanup):
            latest[row.repo, row.branch, row.sha] = row
    for row in latest.values():
        if "pending" in (row.local_outcome, row.remote_outcome):
            retry(git, log, row, is_slot, base, cfg=cfg, fx=fx)


# git-port-exempt: a throwaway merge in a scratch worktree beside the closure command; a Git port method waits for a second caller
MERGE = ("git", "-c", "user.name=task-loop", "-c", "user.email=task-loop@localhost", "merge", "--no-ff", "--no-edit", "-q")


def earlier_pass(check_id: str, expected: RunKey, repo: str, stores: Stores) -> PassRecord | None:
    """The newest pass whose key differs from `expected` only in the base."""
    docs = stores.results(repo, check_id)
    found = [rec for name in docs.keys() if (rec := docs.of(name).get()) is not None  # noqa: SIM118 (a DocSet is not iterable)
             and rec.result.status == "passed" and satisfied(rec.result) and rec.key.base != expected.base
             and rec.key.replace(base=expected.base) == expected]
    return max(found, key=lambda r: r.ts, default=None)


def queue_parent_pass(check_id: str, expected: RunKey, parent: str, repo: str, stores: Stores) -> PassRecord | None:
    """The newest pass made at base `parent` (the commit of the queue ahead) whose key is `expected` in every other field."""
    docs = stores.results(repo, check_id)
    found = [rec for name in docs.keys() if (rec := docs.of(name).get()) is not None  # noqa: SIM118 (a DocSet is not iterable)
             and rec.result.status == "passed" and satisfied(rec.result) and rec.key.base == parent
             and rec.key.replace(base=expected.base) == expected]
    return max(found, key=lambda r: r.ts, default=None)


def digest_of(root: str, paths: list[str]) -> dict[str, str]:
    """{path: sha1 of its bytes, '' when it is gone}."""
    out = {}
    for p in paths:
        f = Path(root, p)
        out[p] = hashlib.sha1(f.read_bytes()).hexdigest() if f.is_file() else ""
    return out


class Carry:
    def __init__(self, cmds: Cmds, git: Git, stores: Stores, repo: str, env: Env) -> None:
        self.cmds, self.git, self.stores, self.repo, self.env = cmds, git, stores, repo, env

    def closure(self, argv: list[str], wt: str, rev: str) -> dict[str, str] | None:
        ran = self.cmds.run([*argv, "--base", rev], cwd=wt)
        if ran.exit:
            return None
        return digest_of(wt, sorted(ln for ln in ran.out.splitlines() if ln.strip()))

    def merged(self, oid: str, base: str) -> str:
        """A throwaway worktree with `oid` merged into `base` ('' when it conflicts)."""
        path = str(scratch.scratch_dir(self.env.vars, "tl-land-merge-"))
        self.cmds.port(f"git worktree add --detach {path} {base[:12]}", lambda: self.git.add_worktree(self.repo, path, base))
        if self.cmds.run([*MERGE, oid], cwd=path).exit:
            self.cmds.run(["git", "merge", "--abort"], cwd=path)
            self.drop(path)
            return ""
        return path

    def drop(self, path: str) -> None:
        self.cmds.row(f"git worktree remove {path}", lambda: self.git.remove_worktree_force(self.repo, path))

    def carried(self, engine: config.EngineConfig, step: str, oid: str, tree: str, base: str, wt: str) -> bool:
        """True when the step's earlier pass now holds under the key of (tree, base) and has been stored under it."""
        spec = next((k for k in engine.checks if k.id == step), None)
        if spec is None or not spec.closure_cmd:
            return False
        memo = authorization.memo_for(self.stores, self.git, wt, engine, TreeSha(tree), BaseSha(base), self.env)
        check = repo_check(spec, engine)
        key = memo.key(check)
        found = earlier_pass(check.id, key, memo.repo, self.stores) if key is not None else None
        if found is None or key is None:
            return self.miss(step, "no earlier pass of this tree")
        merged = self.merged(oid, base)
        if not merged:
            return self.miss(step, "the branch does not merge into the base")
        try:
            mine = self.closure(spec.closure_cmd, wt, self.git.merge_base(self.repo, oid, base) or base)
            theirs = self.closure(spec.closure_cmd, merged, base)
        finally:
            self.drop(merged)
        if mine is None or theirs is None:
            return self.miss(step, "the closure command failed")
        if mine != theirs:
            differ = sorted(p for p in mine.keys() | theirs.keys() if mine.get(p) != theirs.get(p))
            more = f" (+{len(differ) - 3} more)" if len(differ) > 3 else ""
            return self.miss(step, f"the closure differs: {', '.join(differ[:3])}{more}")
        memo.run_id = "carry"
        memo.carry_over(key, found)
        self.cmds.log.note(f"carry: {step} carried, the closure of {len(mine)} files is the same on the moved base")
        return True

    def queue_carried(self, engine: config.EngineConfig, step: str, tree: str, base: str, parent: str, wt: str) -> bool:
        """True when the step's pass at the queue parent `parent` now counts under `base` (main) and has been stored under that key. It
        counts when main has the tree of the parent, so no closure command is needed; any other difference in the key is a miss."""
        spec = next((k for k in engine.checks if k.id == step), None)
        if spec is None:
            return False
        if self.git.rev_parse(self.repo, f"{base}^{{tree}}") != self.git.rev_parse(self.repo, f"{parent}^{{tree}}"):
            return self.miss(step, "main is not the tree of the queue parent")
        memo = authorization.memo_for(self.stores, self.git, wt, engine, TreeSha(tree), BaseSha(base), self.env)
        check = repo_check(spec, engine)
        key = memo.key(check)
        found = queue_parent_pass(check.id, key, parent, memo.repo, self.stores) if key is not None else None
        if found is None or key is None:
            return self.miss(step, "no pass of this tree at the queue parent")
        memo.run_id = "queue-carry"
        memo.carry_over(key, found)
        self.cmds.log.note(f"carry: {step} carried from the queue parent {parent[:12]}, main has its tree")
        return True

    def miss(self, step: str, why: str) -> bool:
        """The land runs the step; the note says why it did not carry."""
        self.cmds.log.note(f"carry: {step} not carried, {why}")
        return False
