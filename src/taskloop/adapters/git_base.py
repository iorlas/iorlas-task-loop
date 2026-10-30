"""How the real git is run: pinned to the checkout (or, for the questions whether the pin itself is right, as the ambient environment has
it), the answers that may be remembered, and git's failure words read into the typed SlotGitErrors. The environment is the `Env` the
port was built with at the edge; nothing here reads the process."""

import re
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from taskloop.adapters import gitmemo
from taskloop.adapters.childenv import tool_env, without
from taskloop.adapters.gitrepo import pinned_env
from taskloop.contracts.env import Env
from taskloop.contracts.gitfacts import GitOutcome
from taskloop.contracts.slots import BranchPinned, DirtyTree, IndexLocked, RefRace, SlotGitError

INDEX_LOCK = re.compile(r"index\.lock")
REF_RACE = re.compile(r"incorrect old value|cannot lock ref|unable to update local ref|Unable to create '[^']*\.lock'")
PINNED = re.compile(r"already (?:checked out|used by worktree) at '?([^'\n]*)'?")
DIRTY = re.compile(r"would be overwritten|commit your changes|local changes|unmerged|unresolved|cannot (?:do a )?(?:commit|merge)")


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


class GitBase:
    """`pinned=False` reads git as the environment has it (no GIT_DIR/GIT_WORK_TREE/GIT_COMMON_DIR), as a worker's or a check's git
    would see the folder: for the questions whether the pin itself is right (core.worktree, core.bare in the shared config)."""

    def __init__(self, env: Env, sleep: Callable[[float], None] = time.sleep, pinned: bool = True) -> None:
        self.env = env
        self.sleep = sleep
        self.pinned = pinned

    def git_env(self, d: str | Path) -> dict[str, str]:
        """The environment of a git command on the checkout at `d`: the port's, cleaned, pinned to that checkout."""
        if not self.pinned:
            return without(self.env.vars, "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR")
        return tool_env(self.env.vars, pinned_env(d))

    def _run(self, d: str, *args: str, stdin: str | None = None, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", d, *args],
            env=self.git_env(d),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            input=stdin,
            timeout=timeout,
        )

    def _must(self, d: str, *args: str) -> str:
        r = self._run(d, *args)
        if r.returncode != 0:
            raise classify(r.stderr or r.stdout)
        return r.stdout.strip()

    def _ask(self, d: str, *args: str) -> str:
        key = sigs = None
        if self.pinned and d:
            key, sigs, known = gitmemo.memo_key(self.env, args, d)
            if known is not None:
                return known
        r = self._run(d, *args)
        out = r.stdout.strip() if r.returncode == 0 else ""
        gitmemo.remember(key, sigs, args, out)
        return out

    def _try(self, d: str, *args: str, stdin: str | None = None, timeout: float | None = None) -> GitOutcome:
        """The command's end and its words: for the callers that read what git said, not only whether it worked."""
        try:
            r = self._run(d, *args, stdin=stdin, timeout=timeout)
        except subprocess.TimeoutExpired:
            return GitOutcome(ok=False, output=f"git {args[0]} timed out after {round((timeout or 0) / 60)} min")
        return GitOutcome(ok=r.returncode == 0, output=(r.stdout + r.stderr).strip())
