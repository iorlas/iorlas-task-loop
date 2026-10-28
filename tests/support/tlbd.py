"""The one place a test replaces the bd that `tl` code opens (`tl.bd_store`), for code that has no store argument of its own.

Give it a typed store (`FakeBeadStore`, `FakeBeads`), or an argv-level function `fn(*argv, cwd=None)` -> a `done(...)` (a stateful
tracker, a racing spy, a failure): the real adapter (adapters/bd.py) parses its answers, so the tests also cover the parsing."""
import subprocess
from contextlib import contextmanager
from unittest import mock

import tl
from taskloop.adapters.bd import BdRun, BdStore


def done(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def argv_store(fn, cwd=None):
    """A BdStore (the actor tl.actor() names) whose bd process is `fn(*args, cwd=...)`: `args` without the actor and the final --json."""
    def run(argv, where):
        args = tuple(argv[3:-1] if argv[-1] == "--json" else argv[3:])
        r = fn(*args, cwd=where)
        return BdRun(r.returncode, r.stdout or "", r.stderr or "")
    return BdStore(tl.actor(), cwd, run=run)


@contextmanager
def bd_boundary(fn=None, store=None, result=None):
    """`tl.bd_store` opens `store`, or a BdStore over `fn`, or one that always answers `result` (a `done(...)`), for a `with`."""
    if store is None:
        fn = fn or (lambda *a, **k: result or done())
        calls = []

        def spy(*a, **k):
            calls.append(a)
            return fn(*a, **k)
        factory = lambda cwd=None: argv_store(spy, cwd and str(cwd))  # noqa: E731
    else:
        calls, factory = None, lambda cwd=None: store  # noqa: E731
    with mock.patch.object(tl, "bd_store", side_effect=factory) as m:
        m.calls = calls
        yield m


def install(test, fn=None, store=None, result=None):
    """`bd_boundary` for a whole test: started now, stopped by the test's cleanup. -> the mock (`.calls`: the argv-level calls)."""
    cm = bd_boundary(fn, store, result)
    m = cm.__enter__()
    test.addCleanup(cm.__exit__, None, None, None)
    return m
