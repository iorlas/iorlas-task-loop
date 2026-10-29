"""A check that is a Python function, not a process: the argv the engine runs answered in memory, with no spawn.

A fake is `(cwd, env) -> (exit, output)` registered under a short command text (`fake("has-f", fn)` returns the text to put in a plan);
`install` puts the fakes where the engine's spawns go (stream-proc's `run`, which the shell and every adapter use, and `subprocess.run`)
and guards the rest: a real process (a Popen of anything but git, which the gitsim answers or a `real_git` test runs) fails the test
naming its argv. A test whose subject is the process itself (a tree kill, a signal, a child's environment) is marked `@real_proc(reason)`;
the guard is off there and an unregistered command runs for real. A fake may add a third value, the seconds it would take: past the
engine's wall limit for the command it is reported stopped there (a check that sleeps past its limit), and nothing sleeps."""
import contextlib
import os
import re
import shlex
import shutil
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
import stream_proc

Fake = Callable[[Path, Mapping[str, str]], tuple[Any, ...]]  # (exit, output) or (exit, output, seconds it would take)


def real_proc(reason: str) -> Any:
    """Marks a test whose subject is the process itself: `reason`, one line, is what only a real process can show."""
    return pytest.mark.real_proc(reason)


def has_f(cwd: Path, env: Mapping[str, str]) -> tuple[int, str]:
    return (0, "") if (cwd / "f.txt").exists() else (1, "")


def f_txt(cwd: Path) -> str:
    """What f.txt holds (stripped) in the check's directory, '' when there is none: a check that reads the file is red without it."""
    f = cwd / "f.txt"
    return f.read_text().strip() if f.exists() else ""


def markers(cwd: Path, env: Mapping[str, str]) -> tuple[int, str]:
    """The engine's conflict-marker check (cli/markers.py, `git grep` for <<<<<<< and >>>>>>>) over the files of the tree."""
    hits = []
    for f in sorted(cwd.rglob("*")):
        if f.is_file() and ".git" not in f.relative_to(cwd).parts:
            for n, line in enumerate(f.read_text(errors="replace").splitlines(), 1):
                if re.match(r"(<<<<<<<|>>>>>>>)( |$)", line):
                    hits.append(f"{f.relative_to(cwd).as_posix()}:{n}:{line}")
    return (1 if hits else 0), "\n".join(hits)


def exits(code: int, out: str = "") -> Fake:
    return lambda cwd, env: (code, out)


def appends(path: Path, text: str = "1", code: int = 0, out: str = "") -> Fake:
    """A check that adds `text` to a file per run (its run count) and exits `code`."""
    def run(cwd: Path, env: Mapping[str, str]) -> tuple[int, str]:
        with path.open("a") as f:
            f.write(text)
        return code, out
    return run


def takes(secs: float, code: int = 0, out: str = "", then: Fake | None = None) -> Fake:
    """A check that runs `secs` seconds (`then` is what it does besides: it runs first, its exit and output win)."""
    def run(cwd: Path, env: Mapping[str, str]) -> tuple[Any, ...]:
        done = then(cwd, env) if then else (code, out)
        return done[0], done[1], secs
    return run


def hangs(out: str = "") -> Fake:
    """A check that sleeps far past any wall limit."""
    return takes(float("inf"), out=out)


# Always there: the checks every plan and stage list names. `has-f` is exit 0 iff f.txt exists in the check's directory.
DEFAULTS: dict[tuple[str, ...], Fake] = {
    ("has-f",): has_f,
    ("true",): exits(0),
    ("false",): exits(1),
    ("test", "-f", "f.txt"): has_f,
}
DEAD_PID = 2**22 + 7  # above any pid_max: the pid of a process that has ended, with no process to end


WORLD: list[Procs] = []  # the active world of the running test (set by `install`)


class Procs:
    def __init__(self, test_id: str, guarded: bool) -> None:
        self.test_id = test_id
        self.guarded = guarded
        self.fakes: dict[tuple[str, ...], Fake] = dict(DEFAULTS)
        self.prefixes: dict[tuple[str, ...], Fake] = {}  # fakes that take arguments: matched on the first words, read with `argv()`
        self.argv: tuple[str, ...] = ()  # the command of the fake that is running
        self.calls: list[tuple[str, ...]] = []  # the fake commands that ran
        self.problems: list[str] = []

    def find(self, argv: Any) -> tuple[Fake, dict[str, str]] | None:
        """The fake an argv stands for, and the variables of an `env K=V ...` prefix; None when it is a real command."""
        if not isinstance(argv, (list, tuple)) or not argv:
            return None
        words, extra = tuple(str(a) for a in argv), {}
        if words[0] == "env":
            i = 1
            while i < len(words) and "=" in words[i] and not words[i].startswith("-"):
                extra[words[i].partition("=")[0]] = words[i].partition("=")[2]
                i += 1
            words = words[i:]
        if not words:
            return None
        if os.path.basename(words[0]) == "bd" and "tl-nobd-" in words[0]:  # the stub support/paths.py puts first on PATH: no tracker here
            return exits(99, "bd: the suite must not run a real bd (support.tlbd, FakeBeadStore)"), extra
        if words[0] == "echo":
            return exits(0, " ".join(words[1:])), extra
        fake = self.fakes.get(words) or (self.fakes.get(words[:1]) if words[0] in ("true", "false") else None)  # they ignore arguments
        fake = fake or next((f for k, f in self.prefixes.items() if words[: len(k)] == k), None)
        self.argv = words
        return (fake, extra) if fake else None

    def answer(self, hit: tuple[Fake, dict[str, str]], argv: Any, cwd: Any, env: Any, timeout: Any) -> tuple[int, str, bool]:
        """(exit, output, hit the wall limit) of a fake command."""
        self.calls.append(tuple(str(a) for a in argv))
        rc, out, *rest = hit[0](Path(cwd or os.getcwd()), {**(os.environ if env is None else env), **hit[1]})
        return rc, out, bool(rest) and timeout is not None and rest[0] > timeout

    def sp_run(self, real: Callable[..., Any]) -> Callable[..., Any]:
        def run(argv: Any, *a: Any, **kw: Any) -> Any:
            hit = self.find(argv)
            if hit is None:
                return real(argv, *a, **kw)
            rc, out, wall = self.answer(hit, argv, kw.get("cwd"), kw.get("env"), kw.get("timeout"))
            if wall:
                raise subprocess.TimeoutExpired(argv, kw.get("timeout") or 0, out.encode())
            text = bool(kw.get("text") or kw.get("encoding") or kw.get("universal_newlines"))
            cap = kw.get("capture_output") or kw.get("stdout") == subprocess.PIPE
            done = subprocess.CompletedProcess(argv, rc, (out if text else out.encode()) if cap else None, None)
            if kw.get("check") and done.returncode:
                raise subprocess.CalledProcessError(done.returncode, argv, done.stdout, None)
            return done
        return run

    def sp_stream(self, real: Callable[..., Any]) -> Callable[..., Any]:
        def run(argv: Any, *, cwd: Any = None, env: Any = None, on_stdout: Any = None, on_stderr: Any = None, **kw: Any) -> Any:
            hit = self.find(argv)
            if hit is None:
                return real(argv, cwd=cwd, env=env, on_stdout=on_stdout, on_stderr=on_stderr, **kw)
            rc, out, wall = self.answer(hit, argv, cwd, env, kw.get("timeout"))
            if out and on_stdout:
                on_stdout(out if out.endswith("\n") else out + "\n")
            if wall:
                return stream_proc.Result(None, None, "wall", 0, 0, None, float(kw.get("timeout") or 0))
            return stream_proc.Result(None if rc < 0 else rc, -rc if rc < 0 else None, None, 0, 0, None, 0.0)
        return run

    def which(self, real: Callable[..., Any]) -> Callable[..., Any]:
        """A fake's program word is on PATH (the plan lint asks `shutil.which` whether the first word of a check is a program)."""
        def which(cmd: str, *a: Any, **kw: Any) -> Any:
            found = real(cmd, *a, **kw)
            return found or (f"/procsim/{cmd}" if any(k[0] == cmd for k in self.fakes) else None)
        return which

    def guard(self, real_init: Callable[..., Any]) -> Callable[..., Any]:
        def init(popen: Any, args: Any, *a: Any, **kw: Any) -> Any:
            first = args[0] if isinstance(args, (list, tuple)) and args else args
            if self.guarded and os.path.basename(str(first)) != "git":  # git is the gitsim's to answer, or a real_git test's to run
                shown = " ".join(map(str, args))[:200] if isinstance(args, (list, tuple)) else str(args)[:200]
                self.problems.append(f"{self.test_id}: spawned a real process: {shown}")
                raise AssertionError(self.problems[-1] + ": a logic test runs its checks as procsim fakes; "
                                     "mark it @real_proc(reason) if the process itself is the point")
            return real_init(popen, args, *a, **kw)
        return init

    def install(self, stack: contextlib.ExitStack) -> None:
        stack.enter_context(mock.patch.object(subprocess, "run", self.sp_run(subprocess.run)))
        stack.enter_context(mock.patch.object(stream_proc, "run", self.sp_stream(stream_proc.run)))
        stack.enter_context(mock.patch.object(shutil, "which", self.which(shutil.which)))
        stack.enter_context(mock.patch.object(subprocess.Popen, "__init__", self.guard(subprocess.Popen.__init__)))
        WORLD.append(self)
        stack.callback(WORLD.pop)

    def check(self) -> None:
        if self.problems:
            raise AssertionError("; ".join(self.problems))


def default(text: str, fn: Fake) -> str:
    """Register `fn` for every test under `text`: a module-level constant check (a plan's, a profile's) that no setUp can register."""
    DEFAULTS[tuple(shlex.split(text))] = fn
    return text


def fake(text: str, fn: Fake, args: bool = False) -> str:
    """Register `fn` for this test under the command `text` (split like the engine splits a check); returns `text`. args: it answers
    that command with any arguments after it (`argv()` has them)."""
    (WORLD[-1].prefixes if args else WORLD[-1].fakes)[tuple(shlex.split(text))] = fn
    return text


def argv() -> tuple[str, ...]:
    """The command (after an `env K=V` prefix) of the fake that is running."""
    return WORLD[-1].argv


def ran(text: str) -> int:
    """How many times the fake command `text` ran in this test."""
    return WORLD[-1].calls.count(tuple(shlex.split(text)))
