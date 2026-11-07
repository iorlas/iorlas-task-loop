"""How the real git is run: pinned to the checkout (or, for the questions whether the pin itself is right, as the ambient environment has
it), the answers that may be remembered, and git's failure words read into the typed SlotGitErrors. The environment is the `Env` the
port was built with at the edge; nothing here reads the process."""

import re
import subprocess
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from taskloop.adapters import gitmemo, procs
from taskloop.adapters.gitrepo import pinned_env
from tlkernel.childenv import tool_env, without
from tlkernel.env import Env
from tlkernel.gitfacts import GitOutcome, push_error_line
from tlkernel.slots import (
    BranchPinned,
    DirtyTree,
    GitReadFailure,
    IndexLocked,
    MissingRemote,
    MissingRevision,
    NotARepo,
    NotAWorktree,
    RefRace,
    SlotGitError,
)

INDEX_LOCK = re.compile(r"index\.lock")
REF_RACE = re.compile(r"incorrect old value|cannot lock ref|unable to update local ref|Unable to create '[^']*\.lock'")
PINNED = re.compile(r"already (?:checked out|used by worktree) at '?([^'\n]*)'?")
DIRTY = re.compile(r"would be overwritten|commit your changes|local changes|unmerged|unresolved|cannot (?:do a )?(?:commit|merge)")
MISSING_REVISION = re.compile(r"fatal: (?:bad revision '.+'|Not a valid object name .+)")
AMBIGUOUS_REVISION = re.compile(r"fatal: ambiguous argument '.+': unknown revision or path not in the working tree\.")


# Linux says "up to mount point" where macOS says "of the parent directories".
NOT_A_REPO = re.compile(r"fatal: not a git repository \(or any (of the )?parent (directories|up to mount point .+)\)(: \.git)?")


def error_line(text: str) -> str:
    """The line of git's stderr that says what went wrong: the first fatal/error one, else the last."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return next((ln for ln in lines if ln.startswith(("fatal:", "error:"))), lines[-1] if lines else "no message from git")


def classify(stderr: str, *, push: bool = False) -> SlotGitError:
    tail = push_error_line(stderr) if push else error_line(stderr)
    if INDEX_LOCK.search(stderr):
        return IndexLocked(tail)
    if m := PINNED.search(stderr):
        return BranchPinned(tail, m.group(1).strip())
    if REF_RACE.search(stderr):
        return RefRace(tail)
    if DIRTY.search(stderr):
        return DirtyTree(tail)
    return SlotGitError(tail)


def read_failure(args: tuple[str, ...], r: subprocess.CompletedProcess[str]) -> GitReadFailure:
    """Only git's specific absence diagnostics are typed absence; other exit-128 failures stay unknown."""
    tail = error_line(r.stderr or r.stdout)
    kind: type[GitReadFailure] = GitReadFailure
    if args[:2] == ("remote", "get-url") and r.returncode == 2 and re.fullmatch(r"error: No such remote '.+'", tail):
        kind = MissingRemote
    if r.returncode == 128:
        if (NOT_A_REPO.fullmatch(tail)
                or re.fullmatch(r"fatal: cannot change to '.+': No such file or directory", tail)):
            kind = NotARepo
        elif tail == "fatal: this operation must be run in a work tree":
            kind = NotAWorktree
        elif MISSING_REVISION.fullmatch(tail) or AMBIGUOUS_REVISION.fullmatch(tail):
            kind = MissingRevision
    return kind(f"git {args[0]} exited {r.returncode}: {tail}")


def no_fsmonitor(env: Mapping[str, str]) -> dict[str, str]:
    """`env` with core.fsmonitor=false added through git's env config: a repo's own fsmonitor setting is a program git runs on every
    status, and the engine's git never runs it (tl-7i9k.53, M-066). A count the caller already set is extended, never replaced."""
    try:
        n = max(int(env.get("GIT_CONFIG_COUNT") or 0), 0)
    except ValueError:
        n = 0
    return {**env, "GIT_CONFIG_COUNT": str(n + 1), f"GIT_CONFIG_KEY_{n}": "core.fsmonitor", f"GIT_CONFIG_VALUE_{n}": "false"}


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
            return no_fsmonitor(without(self.env.vars, "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR"))
        return tool_env(no_fsmonitor(self.env.vars), pinned_env(d))  # tool_env then appends core.hooksPath last, where readers look

    def _run(self, d: str, *args: str, stdin: str | None = None, timeout: float | None = None,
             extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return procs.run(
            ["git", "-C", d, *args],
            env={**self.git_env(d), **(extra or {})},
            input=stdin,
            timeout=timeout,
        )

    def _must(self, d: str, *args: str, extra: dict[str, str] | None = None) -> str:
        r = self._run(d, *args, extra=extra)
        if r.returncode != 0:
            output = r.stdout + r.stderr
            err = classify(output if args[0] == "push" else r.stderr or r.stdout, push=args[0] == "push")
            err.output = output
            raise err
        return r.stdout.strip()

    def _read(self, d: str, *args: str, missing: bool = False, extra: dict[str, str] | None = None) -> str:
        """Preserve read failures, accepting silent exit 1 only for an operation's documented absence."""
        try:
            r = self._run(d, *args, extra=extra)
        except (OSError, subprocess.TimeoutExpired) as err:
            raise GitReadFailure(f"git {args[0]}: {err}") from err
        if r.returncode == 0:
            return r.stdout
        if missing and r.returncode == 1 and not r.stdout and not r.stderr:
            return ""
        raise read_failure(args, r)

    def _predicate(self, d: str, *args: str) -> bool:
        """A quiet predicate: exit 0 is true, silent exit 1 is false, everything else is unknown."""
        try:
            r = self._run(d, *args)
        except (OSError, subprocess.TimeoutExpired) as err:
            raise GitReadFailure(f"git {args[0]}: {err}") from err
        if r.returncode == 0:
            return True
        if r.returncode == 1 and not r.stdout and not r.stderr:
            return False
        raise read_failure(args, r)

    def _ask(self, d: str, *args: str, missing: bool = False) -> str:
        key = sigs = None
        if self.pinned and d:
            key, sigs, known = gitmemo.memo_key(self.env, args, d)
            if known is not None:
                return known
        out = self._read(d, *args, missing=missing).strip()
        if out:
            gitmemo.remember(key, sigs, args, out)
        return out

    def _try(self, d: str, *args: str, stdin: str | None = None, timeout: float | None = None,
             extra: dict[str, str] | None = None) -> GitOutcome:
        """The command's end and its words: for the callers that read what git said, not only whether it worked."""
        try:
            r = self._run(d, *args, stdin=stdin, timeout=timeout, extra=extra)
        except subprocess.TimeoutExpired:
            return GitOutcome(ok=False, output=f"git {args[0]} timed out after {round((timeout or 0) / 60)} min")
        output = r.stdout + r.stderr
        return GitOutcome(ok=r.returncode == 0, output=output if "push" in args[:2] else output.strip())
