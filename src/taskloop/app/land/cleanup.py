"""Cleanup after a recorded land: compare the checked oids, log the result, and keep failures retryable."""
from collections.abc import Callable

from tlkernel import log as rec
from tlkernel.gitport import Git
from tlkernel.locator import RunLocator
from tlkernel.paths import ConfigDir
from tlslots.api import Effects, engine_busy, leave_slot

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
