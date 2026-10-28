"""In-memory stand-ins for the engine's seams: bd (`FakeBeadStore`), the delegate (`FakeRouter`), time (`FakeClock`).

The engine reads beads as dicts (what `tl.show` returns), so the store here is dict-shaped; the typed ports of src/taskloop/adapters
(FakeBeads, FakeDelegate) are for the code that uses the ports. A test sets what a bead looks like with `put`/`note` and reads what the
engine did from `calls` (every `bd(...)` argv, in order)."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import delegate_link as dl
from clock import FakeClock  # noqa: F401  (re-exported: one place for a test to import its fakes from)

from seams import FixedRoute
from support import fake_route

_NO = object()
BEAD = {"id": "t-1", "title": "Add f", "metadata": {}, "acceptance_criteria": "f.txt exists"}


class FakeBeadStore:
    """`show`/`comments`/`bd` as the engine calls them. A bead nobody `put` answers `default` (so a test about one bead needs no setup);
    `bd` records its argv in `calls` and answers like a succeeding bd (`reply`, or `fail` for the next calls)."""

    def __init__(self, default=BEAD, reply="bead t-1: Add f\n"):
        self.default, self.reply = dict(default), reply
        self.beads, self.notes, self.calls = {}, {}, []
        self.fail = []  # (returncode, stderr) for the next bd calls, in order
        self.fns = {}   # name -> a function that answers instead (see `stub`)

    def put(self, bead):
        self.beads[bead["id"]] = dict(bead)
        return self

    def note(self, bead, *comments):
        """Comments on a bead, oldest first: strings (an owner's) or dicts {author, text}."""
        self.notes.setdefault(bead, []).extend(c if isinstance(c, dict) else {"author": "owner", "text": c} for c in comments)
        return self

    @contextmanager
    def stub(self, show=_NO, comments=_NO, show_fn=None, comments_fn=None, bd_fn=None):
        """For the length of a `with`: every `show` answers `show`, every `comments` answers `comments` (or the `*_fn(bead, cwd=None)`),
        and `bd` answers `bd_fn(*argv, **kw)`. The bd call is recorded in `calls` as well."""
        before = dict(self.fns)
        for name, val, fn in (("show", show, show_fn), ("comments", comments, comments_fn), ("bd", _NO, bd_fn)):
            if fn is not None:
                self.fns[name] = fn
            elif val is not _NO:
                self.fns[name] = (lambda v: lambda *a, **k: v)(val)
        try:
            yield self
        finally:
            self.fns = before

    def show(self, bead, cwd=None):
        if "show" in self.fns:
            return self.fns["show"](bead, **({"cwd": cwd} if cwd else {}))
        return dict(self.beads.get(bead, self.default))

    def comments(self, bead, cwd=None):
        if "comments" in self.fns:
            return list(self.fns["comments"](bead, **({"cwd": cwd} if cwd else {})))
        return list(self.notes.get(bead, []))

    def bd(self, *args, cwd=None):
        self.calls.append(args)
        if "bd" in self.fns:
            return self.fns["bd"](*args, **({"cwd": cwd} if cwd else {}))
        return self.answer()

    def answer(self):
        """What a succeeding bd says (the next scripted failure, if any, instead)."""
        rc, err = self.fail.pop(0) if self.fail else (0, "")
        return SimpleNamespace(returncode=rc, stdout=self.reply, stderr=err)

    def said(self, *head):
        """The bd calls that start with `head`, e.g. said("comments", "add")."""
        return [c for c in self.calls if c[:len(head)] == head]


class FakeRouter(FixedRoute):
    """The delegate seam: `resolve` answers a Resolved on fake_route's contract (or a Refusal), `runner` hands out the script."""

    def __init__(self, script=None, route="/fake/route.py", refusal=None):
        resolved = refusal or dl.Resolved(Path(route).parent, route, fake_route.CONTRACT, "explicit")
        super().__init__(resolved, script)
        self.runners = []  # (idle, wall) per runner handed out

    def runner(self, log_path, idle=None, wall=None):
        self.runners.append((idle, wall))
        return self.process
