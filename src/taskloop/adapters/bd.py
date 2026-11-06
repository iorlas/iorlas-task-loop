"""`Beads` over the `bd` command (1.3.1): the one place in the tree that starts a `bd` process.

The verbs, bd's JSON, the argv of every write and the classification of bd's words are the vendored shelf `beads_client`; this file is
what is task-loop's: the process runner (procs), the hint that this bd is older than the one that wrote the db, and the translation of the
client's records and errors into the port's (`Bead` with a `BeadId`, `BdFailure`). Reads that are malformed raise BdFailure; only a valid
empty read or an explicit not-found means absence."""
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar, override

import beads_client as client
from beads_client.classify import PUSH_REJECTED
from beads_client.classify import error_of as classify
from beads_client.records import bead_of as client_bead_of
from beads_client.runner import BdRun, Runner

from taskloop.adapters import procs
from taskloop.contracts.bead import BdError, Bead, Comment, Dep
from taskloop.contracts.ids import BeadId, parse_bead_id
from taskloop.contracts.ports import BdFailure, BeadPatch, BeadQuery, DoltPush, NewBead

T = TypeVar("T")
VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)")
__all__ = ["BdRun", "BdStore", "Runner", "bead_of", "error_of", "subprocess_runner"]


def db_version(cwd: str | None) -> str:
    """The bd version that last wrote the database (.beads/.local_version), found from `cwd` up and, for a linked git worktree,
    in the main checkout; '' when there is none or no directory is named."""
    if not cwd:
        return ""
    here = Path(cwd).resolve()
    for d in (here, *here.parents):
        if (d / ".beads" / ".local_version").is_file():
            return (d / ".beads" / ".local_version").read_text(encoding="utf-8").strip()
        link = d / ".git"
        if link.is_file() and link.read_text(encoding="utf-8").startswith("gitdir:"):
            main = Path(link.read_text(encoding="utf-8").split(":", 1)[1].strip()).parents[2]  # <main>/.git/worktrees/<name>
            seen = main / ".beads" / ".local_version"
            return seen.read_text(encoding="utf-8").strip() if seen.is_file() else ""
    return ""


def subprocess_runner(argv: list[str], cwd: str | None, timeout: float | None = None) -> BdRun:
    """The one `bd` process call. A timeout is code 124."""
    try:
        r = procs.run(argv, cwd=cwd, timeout=timeout, inherit_stdin=False)
    except OSError as e:
        return BdRun(127, "", f"bd: {e}")
    except subprocess.TimeoutExpired:
        return BdRun(124, "", f"bd: no answer in {timeout}s")
    return BdRun(r.returncode, r.stdout, r.stderr)


# ---- the client's records and errors as the port's ---------------------------------------------------------------------

def _bead(b: client.Bead) -> Bead:
    deps = [Dep(id=d.id, type=d.type, title=d.title, status=d.status, close_reason=d.close_reason) for d in b.dependencies]
    return Bead(
        id=parse_bead_id(b.id), title=b.title, status=b.status, issue_type=b.issue_type, priority=b.priority, assignee=b.assignee,
        labels=list(b.labels), parent=b.parent, description=b.description, design=b.design, acceptance_criteria=b.acceptance_criteria,
        notes=b.notes, dependencies=deps, metadata=dict(b.metadata), lease_expires_at=b.lease_expires_at, close_reason=b.close_reason,
        created_at=b.created_at, closed_at=b.closed_at, updated_at=b.updated_at,
    )


def bead_of(d: dict[str, object]) -> Bead:
    return _bead(client_bead_of(d))


def _error(e: client.BdError) -> BdError:
    return BdError(kind=e.kind, missing_sections=list(e.missing_sections), text=e.text)


def error_of(stderr: str, stdout: str) -> BdError:
    """Classify a failed bd call from its output (bd has no error codes: the words are all there is)."""
    return _error(classify(BdRun(1, stdout, stderr)))


def _failure(e: client.BdError) -> BdFailure:
    return BdFailure(_error(e))


class _Bd(client.Bd):
    @override
    def call(self, *args: str) -> BdRun:
        r = super().call(*args)
        if r.code == 0:
            return r
        older = self._older_than_db()
        return BdRun(r.code, r.out, f"{older}\n{r.err}") if older else r

    def _older_than_db(self) -> str:
        """After a failed call: 'bd X at PATH is older than the db's Y; fix PATH' when this bd is older than the one that wrote the db."""
        wrote = VERSION.search(db_version(self.cwd))
        if not wrote:
            return ""
        have = VERSION.search(self._run([self.exe, "--version"], self.cwd).out)
        if have and tuple(map(int, have.groups())) < tuple(map(int, wrote.groups())):
            return f"bd {'.'.join(have.groups())} at {self.exe} is older than the db's {'.'.join(wrote.groups())}; fix PATH"
        return ""


class BdStore:
    def __init__(self, actor: str, cwd: str | None = None, exe: str = "", run: Runner | None = None, timeout: float | None = None) -> None:
        self.actor, self.cwd, self.timeout, self._given = actor, cwd, timeout, run
        self._bd = _Bd(actor, cwd, exe=exe, timeout=timeout, run=run or (lambda argv, where: subprocess_runner(argv, where, timeout)))

    @property
    def exe(self) -> str:
        return self._bd.exe

    def at(self, cwd: str) -> BdStore:
        return BdStore(self.actor, cwd, self.exe, self._given, self.timeout)

    def passthrough(self, args: list[str]) -> BdRun:
        """`tl task ...`: whatever the person typed, with the actor and JSON like every call. A `dolt push` bd answered with a
        rejection but exit 0 exits 1 here."""
        r = self._bd.call(*args)
        if r.code == 0 and args[:2] == ["dolt", "push"] and PUSH_REJECTED.search(r.err + r.out):
            return BdRun(1, r.out, r.err)
        return r

    def dolt_push(self) -> DoltPush:
        """`bd sync`: the land's push, because its exit codes are positive where `bd dolt push` exits 0 on a rejection."""
        r = self._bd.sync()
        return DoltPush(r.code, r.text)

    def _raising(self, fn: Callable[[], T]) -> T:
        try:
            return fn()
        except client.BdError as e:
            raise _failure(e) from None
        except ValueError as e:  # a reply with an id parse_bead_id refuses
            raise BdFailure(BdError(kind="malformed", text=str(e))) from None

    def show(self, bead: BeadId) -> Bead | None:
        return self._raising(lambda: (_bead(b) if (b := self._bd.show(bead)) else None))

    def comments(self, bead: BeadId) -> list[Comment]:
        try:
            return [Comment(author=c.author, text=c.text, created_at=c.created_at) for c in self._bd.comments(bead)]
        except client.BdError:
            return []

    def find(self, query: BeadQuery) -> list[Bead]:
        return self._raising(lambda: [_bead(b) for b in self._bd.find(query.status, query.label, include_closed=query.include_closed)])

    def ready(self, label: str = "") -> list[Bead]:
        return self._raising(lambda: [_bead(b) for b in self._bd.ready(label)])

    def create(self, new: NewBead) -> BeadId:
        made = client.NewBead(new.title, new.issue_type, new.priority, new.description, new.acceptance_criteria,
                              tuple(new.labels), new.parent, tuple(new.deps), new.no_inherit_labels)
        return self._raising(lambda: parse_bead_id(self._bd.create(made)))

    def update(self, bead: BeadId, patch: BeadPatch) -> None:
        self._raising(lambda: self._bd.update(
            bead, status=patch.status or None, assignee=patch.assignee, description=patch.description, notes=patch.notes,
            metadata=patch.metadata, set_metadata=patch.set_metadata, unset_metadata=patch.unset_metadata,
            if_assignee=patch.if_assignee or None))

    def claim(self, bead: BeadId) -> bool:
        return self._bd.call("update", bead, "--claim").code == 0

    def unclaim(self, bead: BeadId, force: bool = False) -> bool:
        return self._bd.call("unclaim", bead, *(["--force"] if force else [])).code == 0

    def heartbeat(self, bead: BeadId) -> None:
        self._raising(lambda: self._bd.heartbeat(bead))

    def close(self, bead: BeadId, reason: str, if_assignee: str = "") -> None:
        self._raising(lambda: self._bd.close(bead, reason, if_assignee=if_assignee or None))

    def add_comment(self, bead: BeadId, text: str) -> None:
        self._raising(lambda: self._bd.comment(bead, text))

    def add_label(self, bead: BeadId, label: str, if_assignee: str = "") -> None:
        self._raising(lambda: self._bd.add_label(bead, label, if_assignee=if_assignee or None))

    def remove_label(self, bead: BeadId, label: str) -> None:
        self._raising(lambda: self._bd.remove_label(bead, label))

    def provenance(self, bead: BeadId, kind: str, source: str, ref: str = "", ref_kind: str = "", at: str = "", payload: str = "") -> None:
        self._raising(lambda: self._bd.provenance(bead, kind, source, ref=ref, ref_kind=ref_kind, at=at, payload=payload))
