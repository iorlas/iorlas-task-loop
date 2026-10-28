"""The one place a test replaces `tl.bd`, for code that has no store seam (tl's own functions call `tl.bd` directly).

`tl.show` and `tl.comments` are `tl.bd` plus a JSON parse, so a test never patches them: it puts the bead in a `FakeBeadStore` and
installs `store_bd(store)`, or gives `bd_boundary` the argv-level function it needs (a stateful tracker, a racing spy, a failure)."""
import json
import subprocess
from contextlib import contextmanager
from unittest import mock

import tl


def done(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def store_bd(store):
    """A `tl.bd` that answers from a FakeBeadStore: show/comments from its beads and notes, anything else through `store.bd`."""
    def bd(*args, cwd=None, check=False):
        kw = {"cwd": cwd} if cwd else {}
        if args[:1] == ("show",):
            return done(json.dumps([store.show(args[1], **kw)]))
        if args[:1] == ("comments",) and len(args) > 1 and args[1] != "add":
            return done(json.dumps(store.comments(args[1], **kw)))
        return store.bd(*args, **kw)
    return bd


@contextmanager
def bd_boundary(fn=None, store=None, result=None):
    """`tl.bd` is `fn(*argv, **kw)`, or answers from `store`, or always returns `result` (a `done(...)`) for the length of a `with`."""
    if store is not None:
        fn = store_bd(store)
    with mock.patch.object(tl, "bd", **({"side_effect": fn} if fn else {"return_value": result or done()})) as m:
        yield m


def install(test, fn=None, store=None, result=None):
    """`bd_boundary` for a whole test: started now, stopped by the test's cleanup. -> the mock."""
    cm = bd_boundary(fn, store, result)
    m = cm.__enter__()
    test.addCleanup(cm.__exit__, None, None, None)
    return m
