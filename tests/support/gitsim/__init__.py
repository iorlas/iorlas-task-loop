"""A git in memory for the engine tests: the argv of `git` answered by Python over a model of repos, with no process.

`Sim.install(case)` puts it where the engine's git calls go (`subprocess.run` and stream-proc's `run`, which every adapter and the
engine's shell use) and guards the rest: a `git` that still reaches a real process (a shell line, an unpatched spawn) fails the test
naming it, and so does a git command the sim does not know. Real git stays in the marked integration cells (`real_git`) where the
behaviour of git itself is the point."""
import contextlib
import os
import stat
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from unittest import mock

import stream_proc

from . import diffs, read, rebase, remote, status, write
from .ctx import Ctx
from .model import Fail, W, locate

HANDLERS: dict[str, Callable[[Ctx], int]] = {
    "add": write.cmd_add, "check-ignore": read.cmd_check_ignore, "checkout": write.cmd_checkout, "clone": remote.cmd_clone,
    "commit": write.cmd_commit, "config": read.cmd_config, "diff": diffs.cmd_diff,
    "fetch": remote.cmd_fetch, "grep": read.cmd_grep, "init": remote.cmd_init, "log": read.cmd_log, "ls-files": read.cmd_ls_files,
    "ls-tree": read.cmd_ls_tree, "merge-base": read.cmd_merge_base, "pull": remote.cmd_pull, "push": remote.cmd_push,
    "read-tree": write.cmd_read_tree, "rebase": rebase.cmd_rebase, "remote": read.cmd_remote, "reset": write.cmd_reset,
    "rev-list": read.cmd_rev_list, "rev-parse": read.cmd_rev_parse, "show": read.cmd_show, "status": status.cmd_status,
    "symbolic-ref": read.cmd_symbolic_ref, "worktree": read.cmd_worktree, "write-tree": write.cmd_write_tree,
}
GLOBAL_FLAGS = ("--no-optional-locks", "--literal-pathspecs", "--no-pager")


# The `git` a shell line finds on PATH: `git grep` over the working tree files (the engine's conflict-marker check is one, run by bash
# and out of the sim's reach), any other git is a real spawn that fails the test (the marker file is read by `Sim.check`).
SHIM = """#!/bin/sh
if [ "$1" = grep ]; then
  shift
  pat=
  for a in "$@"; do case "$a" in -*) ;; --) break ;; *) pat=${pat:-$a} ;; esac; done
  out=$(grep -rnIE --exclude-dir=.git -e "$pat" . | sed 's#^\\./##')
  [ -n "$out" ] && printf '%s\\n' "$out" && exit 0
  exit 1
fi
echo "$@" >> SHIM_DIR/spawned
exit 99
"""


class Unsupported(AssertionError):
    """A git command the sim has no answer for: the test fails by name, so a new git call cannot slip in unseen."""


def is_git(argv: Any) -> bool:
    return isinstance(argv, (list, tuple)) and bool(argv) and os.path.basename(str(argv[0])) == "git"


def run_git(argv: list[str], cwd: Any = None, env: Mapping[str, str] | None = None, stdin: bytes = b"") -> tuple[int, bytes, str]:
    args = [str(a) for a in argv[1:]]
    here = str(cwd or os.getcwd())
    opts: dict[str, str] = {}
    while args and args[0].startswith("-") and args[0] != "--version":
        if args[0] == "-C":
            here, args = str(Path(here, args[1])), args[2:]
        elif args[0] == "-c":
            k, _, v = args[1].partition("=")
            opts[k.lower()], args = v, args[2:]
        elif args[0] in GLOBAL_FLAGS:
            args = args[1:]
        else:
            break
    env_d = dict(os.environ if env is None else env)
    handler = HANDLERS.get(args[0]) if args else None
    if handler is None:
        raise Unsupported(f"git {' '.join(args)}: the gitsim has no such command")
    c = Ctx(locate(here, env_d), args[1:], env_d, here, stdin, opts)
    try:
        rc = handler(c)
    except Fail as f:
        rc, c.err = f.rc, [*c.err, f.msg]
    return rc, bytes(c.out), "\n".join(c.err) + ("\n" if c.err else "")


def textual(kw: Mapping[str, Any]) -> bool:
    return bool(kw.get("text") or kw.get("encoding") or kw.get("universal_newlines"))


class Sim:
    def __init__(self, case: Any) -> None:
        self.case = case
        self.calls: list[tuple[str, ...]] = []
        self.problems: list[str] = []
        self.faults: list[tuple[tuple[str, ...], str, Callable[[int], bool]]] = []

    def fail(self, prefix: tuple[str, ...], stderr: str, when: Callable[[int], bool] = lambda n: True) -> None:
        """Make a command that starts with `prefix` fail with `stderr` when `when(n)` says so, n counting its calls from 1."""
        self.faults.append((prefix, stderr, when))

    def answer(self, argv: list[str], cwd: Any, env: Any, stdin: bytes) -> tuple[int, bytes, str]:
        self.calls.append(tuple(str(a) for a in argv[1:]))
        for prefix, stderr, when in self.faults:
            words = [a for a in self.calls[-1] if a not in GLOBAL_FLAGS]
            n = sum(tuple(w for w in x if w not in GLOBAL_FLAGS)[: len(prefix)] == prefix for x in self.calls)
            if tuple(words[: len(prefix)]) == prefix and when(n):
                return 1, b"", stderr + "\n"
        try:
            return run_git(argv, cwd, env, stdin)
        except Unsupported as e:
            self.problems.append(f"{self.case.id()}: {e}")
            raise

    def sp_run(self, real: Callable[..., Any]) -> Callable[..., Any]:
        def run(argv: Any, *a: Any, **kw: Any) -> Any:
            if not is_git(argv):
                return real(argv, *a, **kw)
            data = kw.get("input") or b""
            rc, out, err = self.answer(list(argv), kw.get("cwd"), kw.get("env"), data.encode() if isinstance(data, str) else data)
            if kw.get("check") and rc:
                raise subprocess.CalledProcessError(rc, argv, out, err.encode())
            cap = kw.get("capture_output") or kw.get("stdout") == subprocess.PIPE
            cape = kw.get("capture_output") or kw.get("stderr") == subprocess.PIPE
            conv = (lambda b: b.decode("utf-8", "replace")) if textual(kw) else (lambda b: b)
            return subprocess.CompletedProcess(argv, rc, conv(out) if cap else None, conv(err.encode()) if cape else None)
        return run

    def sp_stream(self, real: Callable[..., Any]) -> Callable[..., Any]:
        def run(argv: Any, *, cwd: Any = None, env: Any = None, on_stdout: Any = None, on_stderr: Any = None, **kw: Any) -> Any:
            if not is_git(argv):
                return real(argv, cwd=cwd, env=env, on_stdout=on_stdout, on_stderr=on_stderr, **kw)
            rc, out, err = self.answer(list(argv), cwd, env, b"")
            for text, cb in ((out.decode("utf-8", "replace"), on_stdout), (err, on_stderr)):
                if cb and text:
                    cb(text)
            return stream_proc.Result(rc, None, None, 0, 0, None, 0.0)
        return run

    def guard(self, real_init: Callable[..., Any]) -> Callable[..., Any]:
        def init(popen: Any, args: Any, *a: Any, **kw: Any) -> Any:
            if is_git(args):
                self.problems.append(f"{self.case.id()}: spawned a real git process ({' '.join(map(str, args[1:4]))}...)")
                raise AssertionError(self.problems[-1] + ": a logic test runs on the gitsim; mark it @real_git(reason) if git is the point")
            return real_init(popen, args, *a, **kw)
        return init

    def install(self, stack: contextlib.ExitStack) -> None:
        stack.enter_context(mock.patch.object(subprocess, "run", self.sp_run(subprocess.run)))
        stack.enter_context(mock.patch.object(stream_proc, "run", self.sp_stream(stream_proc.run)))
        stack.enter_context(mock.patch.object(subprocess.Popen, "__init__", self.guard(subprocess.Popen.__init__)))
        shim = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="tl-nogit-")))
        (shim / "git").write_text(SHIM.replace("SHIM_DIR", str(shim)))
        (shim / "git").chmod((shim / "git").stat().st_mode | stat.S_IXUSR)
        self.shim = shim
        stack.enter_context(mock.patch.dict(os.environ, {"PATH": f"{shim}{os.pathsep}{os.environ.get('PATH', '')}"}))

    def check(self) -> None:
        """Fails the test when a real git ran in a shell line or the sim met a command it does not know (even one the code swallowed)."""
        spawned = self.shim / "spawned"
        if spawned.exists():
            self.problems.append(f"{self.case.id()}: a shell line ran a real git: {spawned.read_text().strip()[:200]}")
        if self.problems:
            raise AssertionError("; ".join(self.problems))


def reset() -> None:
    W.reset()


def new_world(home: Path) -> None:
    """The engine tests' repo: origin `o.git` (bare) and the clone `wt`, one pushed commit with a.txt."""
    origin = remote.make_repo(home / "o.git", True)
    origin.set_config("gc.auto", "0")
    git_dir = home / "wt" / ".git"
    wt = remote.make_repo(home / "wt", False)
    wt.set_config("remote.origin.url", str(home / "o.git"))
    wt.set_config("branch.main.remote", "origin")
    wt.set_config("branch.main.merge", "refs/heads/main")
    (home / "wt" / "a.txt").write_text("a\n")
    for argv in (["add", "-A"], ["commit", "-qm", "init"], ["push", "-q", "origin", "HEAD:main"]):
        rc, _, err = run_git(["git", *argv], cwd=home / "wt", env={"GIT_DIR": str(git_dir), "GIT_WORK_TREE": str(home / "wt")})
        assert rc == 0, err
