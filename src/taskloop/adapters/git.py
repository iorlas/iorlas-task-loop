"""Git (the port in contracts/ports.py) on the real git binary, pinned to the checkout. git's words are read here and nowhere else:
a failure becomes one of the typed SlotGitErrors (BranchPinned, DirtyTree, RefRace, IndexLocked) or the plain SlotGitError."""
import os
import re
import subprocess
import time
from collections.abc import Callable

from taskloop.adapters.gitenv import run_git
from taskloop.contracts.slots import BranchPinned, Checkout, DirtyTree, IndexLocked, RefRace, SlotGitError

INDEX_LOCK = re.compile(r"index\.lock")
REF_RACE = re.compile(r"incorrect old value|cannot lock ref|unable to update local ref|Unable to create '[^']*\.lock'")
PINNED = re.compile(r"already (?:checked out|used by worktree) at '?([^'\n]*)'?")
DIRTY = re.compile(r"would be overwritten|commit your changes|local changes|unmerged|unresolved|cannot (?:do a )?(?:commit|merge)")
FETCH_TRIES = 5


def error_line(text: str) -> str:
    """The line of git's stderr that says what went wrong: the first fatal/error one, else the last."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return next((ln for ln in lines if ln.startswith(("fatal:", "error:"))), lines[-1] if lines else "no message from git")


def classify(stderr: str) -> SlotGitError:
    tail = error_line(stderr)
    if INDEX_LOCK.search(stderr):
        return IndexLocked(tail)
    if m := PINNED.search(stderr):
        return BranchPinned(tail, m.group(1).strip())
    if REF_RACE.search(stderr):
        return RefRace(tail)
    if DIRTY.search(stderr):
        return DirtyTree(tail)
    return SlotGitError(tail)


class RealGit:
    def __init__(self, sleep: Callable[[float], None] = time.sleep) -> None:
        self.sleep = sleep

    @staticmethod
    def _run(d: str, *args: str) -> subprocess.CompletedProcess[str]:
        return run_git(d, *args, capture_output=True, text=True, encoding="utf-8", errors="replace")

    def _must(self, d: str, *args: str) -> str:
        r = self._run(d, *args)
        if r.returncode != 0:
            raise classify(r.stderr or r.stdout)
        return r.stdout.strip()

    def _ask(self, d: str, *args: str) -> str:
        r = self._run(d, *args)
        return r.stdout.strip() if r.returncode == 0 else ""

    def fetch(self, d: str) -> None:
        """`git fetch -q origin`, again while it loses a ref lock to a concurrent fetch (worktrees share refs/remotes)."""
        for i in range(FETCH_TRIES):
            r = self._run(d, "fetch", "-q", "origin")
            if r.returncode == 0:
                return
            err = classify(r.stderr)
            if not isinstance(err, RefRace) or i == FETCH_TRIES - 1:
                raise err
            self.sleep(0.1 * (i + 1))

    def rebasing(self, d: str) -> bool:
        gd = self._ask(d, "rev-parse", "--git-dir")
        return bool(gd) and any(os.path.isdir(os.path.join(d, gd, x)) for x in ("rebase-merge", "rebase-apply"))

    def rebase_abort(self, d: str) -> None:
        self._run(d, "rebase", "--abort")

    def dirty(self, d: str) -> bool:
        return bool(self._ask(d, "status", "--porcelain"))

    def branch(self, d: str) -> str:
        return self._ask(d, "symbolic-ref", "--short", "-q", "HEAD")

    def commit_all(self, d: str, branch: str, message: str) -> None:
        if not self.branch(d):
            self._must(d, "checkout", "-b", branch)
        self._must(d, "add", "-A")
        self._must(d, "commit", "-q", "--no-verify", "-m", message)

    def has_branch(self, d: str, branch: str) -> bool:
        return bool(self._ask(d, "rev-parse", "--verify", "-q", "refs/heads/" + branch))

    def checkout(self, d: str, branch: str) -> None:
        self._must(d, "checkout", branch)

    def checkout_new(self, d: str, branch: str, start: str) -> None:
        self._must(d, "checkout", "-b", branch, start)

    def checkout_detached(self, d: str, ref: str) -> None:
        self._must(d, "checkout", "--detach", ref)

    def clean(self, d: str, keep: list[str]) -> None:
        self._run(d, "clean", "-fdq", *[x for k in keep for x in ("-e", k)])

    def checkouts(self, d: str) -> list[Checkout]:
        out = self._ask(d, "worktree", "list", "--porcelain")
        found = []
        for i, block in enumerate(out.split("\n\n")):
            lines = block.splitlines()
            path = next((ln[9:] for ln in lines if ln.startswith("worktree ")), "")
            branch = next((ln[18:] for ln in lines if ln.startswith("branch refs/heads/")), "")
            if path:
                found.append(Checkout(path=path, branch=branch, main=i == 0))
        return found

    def remove_worktree(self, repo: str, path: str) -> bool:
        return self._run(repo, "worktree", "remove", path).returncode == 0

    def add_worktree(self, repo: str, path: str, ref: str) -> None:
        self._must(repo, "worktree", "add", "--detach", path, ref)
