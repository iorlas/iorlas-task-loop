"""In-memory stand-ins for the engine's seams: bd (`FakeBeadStore`), the delegate (`FakeRouter`), time (`FakeClock`).

`FakeBeadStore` is the Beads port with a call record: a test sets what a bead looks like with `put`/`note` (bd's JSON or a Bead) and
reads what the engine did from `calls` (each write as the argv bd would get, in order)."""
import support.paths  # noqa: F401

# isort: split
from contextlib import contextmanager
from pathlib import Path

from support import fake_route
from support.fake_clock import FakeClock  # noqa: F401  (re-exported: one place for a test to import its fakes from)
from support.narrow import must
from taskloop.adapters import bd
from taskloop.adapters import delegate as dl
from taskloop.app.release.seams import FixedRoute
from taskloop.contracts.bead import Bead, Comment
from taskloop.contracts.ids import BeadId
from taskloop.contracts.ports import BdFailure, BeadPatch, BeadQuery, DoltPush, NewBead

_NO = object()


def _returning(value):
    return lambda *a, **k: value


# a bead as bd prints it; labelled visual so verify runs
BEAD = {"id": "t-1", "title": "Add f", "metadata": {}, "acceptance_criteria": "f.txt exists", "labels": ["visual"]}


def must_bead(x, default_id="t-1") -> Bead:
    """as_bead for a test that needs a Bead (an empty one for nothing)."""
    return as_bead(x, default_id) or Bead(id=BeadId(default_id), title="", status="")


def as_bead(x, default_id="t-1"):
    """A Bead from bd's JSON (a dict), a Bead, or None for nothing/{}."""
    if isinstance(x, Bead) or x is None:
        return x
    return bd.bead_of(dict(x, id=x.get("id") or default_id)) if x else None


def as_comment(c):
    return (
        c
        if isinstance(c, Comment)
        else Comment(author=c.get("author") or "", text=c.get("text") or "", created_at=c.get("created_at") or "")
    )


class FakeBeadStore:
    """The Beads port for the engine's tests. Reads: `show` answers the bead `put` for that id, else `default` (so a test about one
    bead needs no setup); `comments` the `note`s. Writes are recorded in `calls` as the argv bd would get (adapters/bd.py builds it),
    answer like a succeeding bd, or fail with the next scripted `fail` (returncode, stderr). `stub` swaps an answer for a `with`."""

    def __init__(self, default=BEAD, made="t-9"):
        self.default, self.made = as_bead(default), made
        self.beads, self.notes, self.calls = {}, {}, []
        self.fail = []  # (returncode, stderr) for the next writes, in order
        self.fns = {}   # name -> a function that answers instead (see `stub`)

    def put(self, bead):
        b = as_bead(bead)
        self.beads[must(b).id] = b
        return self

    def note(self, bead, *comments):
        """Comments on a bead, oldest first: strings (an owner's) or dicts {author, text}."""
        self.notes.setdefault(bead, []).extend(as_comment(c if isinstance(c, dict) else {"author": "owner", "text": c}) for c in comments)
        return self

    @contextmanager
    def stub(self, show=_NO, comments=_NO, show_fn=None, comments_fn=None, bd_fn=None, find_fn=None):
        """For the length of a `with`: every `show` answers `show` (a bead, bd's JSON, or None), every `comments` answers `comments`
        (or the `*_fn(bead)`), `find` answers `find_fn(query)` (beads or bd's JSON), and each write answers `bd_fn(*argv)` (a
        process-like result: returncode, stdout, stderr)."""
        before = dict(self.fns)
        for name, val, fn in (("show", show, show_fn), ("comments", comments, comments_fn), ("bd", _NO, bd_fn), ("find", _NO, find_fn)):
            if fn is not None:
                self.fns[name] = fn
            elif val is not _NO:
                self.fns[name] = _returning(val)
        try:
            yield self
        finally:
            self.fns = before

    def at(self, cwd):
        return self

    def show(self, bead: BeadId):
        if "show" in self.fns:
            return as_bead(self.fns["show"](bead), bead)
        return self.beads.get(bead, self.default)

    def comments(self, bead: BeadId):
        if "comments" in self.fns:
            return [as_comment(c) for c in self.fns["comments"](bead)]
        return list(self.notes.get(bead, []))

    def find(self, query: BeadQuery) -> list[Bead]:
        if "find" in self.fns:
            return [b for b in map(as_bead, self.fns["find"](query)) if b]
        return [
            b
            for b in self.beads.values()
            if (b.status != "closed" or query.include_closed)
            and (not query.status or b.status == query.status)
            and (not query.label or query.label in b.labels)
        ]

    def ready(self, label=""):
        return list(self.find(BeadQuery(status="open", label=label)))

    def run(self, argv, failing=False):
        """Record a write; -> the process-like answer it got (a refusal raises BdFailure unless `failing`: claim/unclaim answer False)."""
        self.calls.append(tuple(argv))
        if "bd" in self.fns:
            r = self.fns["bd"](*argv)
            rc = r.returncode if isinstance(getattr(r, "returncode", 0), int) else 0
            out, err = (
                (r.stdout if isinstance(getattr(r, "stdout", ""), str) else ""),
                (r.stderr if isinstance(getattr(r, "stderr", ""), str) else ""),
            )
        else:
            rc, err = self.fail.pop(0) if self.fail else (0, "")
            out = ""
        if rc != 0 and not failing:
            raise BdFailure(bd.error_of(err, out))
        return rc, out

    def create(self, new: NewBead) -> BeadId:
        _rc, out = self.run(bd.create_argv(new))
        made = bd._loads(out) if out else None
        return BeadId(str(made.get("id"))) if isinstance(made, dict) and made.get("id") else BeadId(self.made)

    def update(self, bead: BeadId, patch: BeadPatch) -> None:
        self.run(bd.update_argv(bead, patch))

    def claim(self, bead: BeadId):
        return self.run(["update", bead, "--claim"], failing=True)[0] == 0

    def unclaim(self, bead: BeadId, force=False):
        return self.run(["unclaim", bead] + (["--force"] if force else []), failing=True)[0] == 0

    def heartbeat(self, bead: BeadId):
        self.run(["heartbeat", bead])

    def close(self, bead: BeadId, reason, if_assignee=""):
        if if_assignee:
            self.update(bead, BeadPatch(assignee=if_assignee, if_assignee=if_assignee))
        self.run(["close", bead, "--reason", reason])

    def add_comment(self, bead: BeadId, text):
        self.run(["comments", "add", bead, text])

    def add_label(self, bead: BeadId, label, if_assignee=""):
        if if_assignee:
            self.update(bead, BeadPatch(assignee=if_assignee, if_assignee=if_assignee))
        self.run(["label", "add", bead, label])

    def remove_label(self, bead: BeadId, label):
        self.run(["label", "remove", bead, label])

    def provenance(self, bead: BeadId, kind, source, ref="", ref_kind="", at="", payload=""):
        self.run(["provenance", "record", "--issue", bead, "--kind", kind, "--source", source])

    def dolt_push(self):
        return DoltPush(*self.run(["sync"], failing=True))

    def said(self, *head):
        """The writes that start with `head`, e.g. said("comments", "add")."""
        return [c for c in self.calls if c[:len(head)] == head]


class FakeRouter(FixedRoute):
    """The delegate seam: `resolve` answers a Resolved on fake_route's contract (or a Refusal), `runner` hands out the script."""

    def __init__(self, script=None, route="/fake/route.py", refusal=None):
        resolved = refusal or dl.Resolved(Path(route).parent, route, fake_route.CONTRACT, "explicit")
        super().__init__(resolved, script)
        self.runners = []  # wall per runner handed out

    def runner(self, log_path, wall=None, live="", on_worker=None):
        self.runners.append(wall)
        return self.process
