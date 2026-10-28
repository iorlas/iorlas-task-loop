"""The one place a test replaces the bd that task-loop code opens: the process boundary of `BdStore` (adapters/bd.py), whoever made the store.

Give it an argv-level function `fn(*argv, cwd=None)` -> a `done(...)` (a stateful tracker, a racing spy, a failure): the real adapter
parses its answers, so the tests also cover the parsing. A typed store (`FakeBeadStore`) is not patched in: a test hands it to the
code under test as its `store` argument. A bare `bd` on PATH is a stub that fails loudly (support.paths), so a path that forgets the
store cannot reach a real tracker."""
import subprocess
from contextlib import contextmanager
from unittest import mock

from taskloop.adapters import bd
from taskloop.adapters.bd import BdRun, BdStore
from taskloop.adapters.ident import actor


def done(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def argv_store(fn, cwd=None):
    """A BdStore (the actor ident.actor() names) whose bd process is `fn(*args, cwd=...)`: `args` without the actor and the final --json."""
    def run(argv, where):
        args = tuple(argv[3:-1] if argv[-1] == "--json" else argv[3:])
        r = fn(*args, cwd=where)
        return BdRun(r.returncode, r.stdout or "", r.stderr or "")
    return BdStore(actor(), cwd, run=run)


@contextmanager
def bd_boundary(fn=None, result=None):
    """Every bd call in the process runs `fn` (or answers `result`, a `done(...)`) for the length of a `with`. -> the mock (`.calls`: the argv-level calls)."""
    fn = fn or (lambda *a, **k: result or done())
    calls = []

    def run(argv, cwd, timeout=None):
        args = tuple(argv[3:-1] if argv[-1] == "--json" else argv[3:])
        calls.append(args)
        r = fn(*args, cwd=cwd)
        return BdRun(r.returncode, r.stdout or "", r.stderr or "")
    with mock.patch.object(bd, "subprocess_runner", side_effect=run) as m:
        m.calls = calls
        yield m


def install(test, fn=None, result=None):
    """`bd_boundary` for a whole test: started now, stopped by the test's cleanup. -> the mock (`.calls`: the argv-level calls)."""
    cm = bd_boundary(fn, result)
    m = cm.__enter__()
    test.addCleanup(cm.__exit__, None, None, None)
    return m
