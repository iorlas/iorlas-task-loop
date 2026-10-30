"""`Beads` over the `bd` command (1.3.1): the one place in the tree that starts a `bd` process.

Every call is `bd --actor <who> <args> --json`. The key names bd prints differently in different commands are normalised
here, once: a dependency is `depends_on_id`/`type` in `list` and `id`/`dependency_type` in `show`, an error is the `error`
key of bd's JSON on stdout or plain words on stderr. Reads are tolerant (bd adds keys; a key we do not model is dropped);
a refused write raises BdFailure carrying a BdError."""
import json
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from taskloop.contracts.bead import BdError, Bead, Comment, Dep
from taskloop.contracts.ports import BdFailure, BeadPatch, BeadQuery, DoltPush, NewBead

# bd 1.3.1 exits 0 on a push the remote rejected; its words are git's
PUSH_REJECTED = re.compile(r"Updates were rejected|failed to push some refs|tip of your current branch is behind", re.I)
LINT_MISSING = re.compile(r"missing required sections?[^:\n]*:\s*(.+)", re.I)


@dataclass(frozen=True)
class BdRun:
    code: int
    out: str
    err: str


Runner = Callable[[list[str], str | None], BdRun]


def subprocess_runner(argv: list[str], cwd: str | None, timeout: float | None = None) -> BdRun:
    """The one `bd` process call. A timeout is code 124."""
    try:
        r = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
                           timeout=timeout, check=False)
    except OSError as e:
        return BdRun(127, "", f"bd: {e}")
    except subprocess.TimeoutExpired:
        return BdRun(124, "", f"bd: no answer in {timeout}s")
    return BdRun(r.returncode, r.stdout, r.stderr)


# ---- bd's JSON as records ---------------------------------------------------------------------------------------------

def _str(d: dict[str, Any], key: str) -> str:
    v = d.get(key)
    return v if isinstance(v, str) else ""


def dep_of(d: dict[str, Any]) -> Dep:
    return Dep(id=_str(d, "id") or _str(d, "depends_on_id"), type=_str(d, "dependency_type") or _str(d, "type"),
               title=_str(d, "title"), status=_str(d, "status"), close_reason=_str(d, "close_reason"))


def bead_of(d: dict[str, Any]) -> Bead:
    prio, labels, deps, meta = d.get("priority"), d.get("labels"), d.get("dependencies"), d.get("metadata")
    return Bead(
        id=str(d["id"]),
        title=_str(d, "title"),
        status=_str(d, "status"),
        issue_type=_str(d, "issue_type"),
        priority=prio if isinstance(prio, int) else None,
        assignee=_str(d, "assignee"),
        labels=sorted(x for x in labels if isinstance(x, str)) if isinstance(labels, list) else [],
        parent=_str(d, "parent"),
        description=_str(d, "description"),
        design=_str(d, "design"),
        acceptance_criteria=_str(d, "acceptance_criteria"),
        notes=_str(d, "notes"),
        dependencies=[dep_of(x) for x in deps if isinstance(x, dict)] if isinstance(deps, list) else [],
        metadata=dict(meta) if isinstance(meta, dict) else {},
        lease_expires_at=_str(d, "lease_expires_at"),
        close_reason=_str(d, "close_reason"),
        created_at=_str(d, "created_at"),
        closed_at=_str(d, "closed_at"),
        updated_at=_str(d, "updated_at"),
    )


def beads_of(data: Any) -> list[Bead]:
    rows = data if isinstance(data, list) else [data] if isinstance(data, dict) and "id" in data else []
    return [bead_of(r) for r in rows if isinstance(r, dict) and "id" in r]


def comments_of(data: Any) -> list[Comment]:
    rows = data if isinstance(data, list) else []
    return [Comment(author=_str(r, "author"), text=_str(r, "text"), created_at=_str(r, "created_at"))
            for r in rows if isinstance(r, dict)]


def _loads(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return None


def error_of(stderr: str, stdout: str) -> BdError:
    """Classify a failed bd call from its output (bd has no error codes: the words are all there is)."""
    said = _loads(stdout)
    asked = said.get("error") if isinstance(said, dict) else None
    text = f"{stderr}\n{asked if isinstance(asked, str) else stdout}"
    lint = LINT_MISSING.search(text)
    if lint:
        return BdError(kind="lint", missing_sections=[h.strip() for h in re.findall(r"##\s*([^,#\n]+)", lint.group(1))],
                       text=text.strip()[:500])
    low = text.lower()
    kind = ("not_claimable" if "not claimable" in low or "already claimed" in low or "claimed by a different actor" in low else
            "not_found" if "not found" in low or "no issue" in low else "other")
    return BdError(kind=kind, text=text.strip()[:500])


# ---- argv of the writes (pure) -----------------------------------------------------------------------------------------

def create_argv(new: NewBead) -> list[str]:
    a = ["create", new.title, "--type", new.issue_type]
    for flag, val in (("--description", new.description), ("--acceptance", new.acceptance_criteria), ("--parent", new.parent)):
        if val:
            a += [flag, val]
    if new.priority is not None:
        a += ["--priority", str(new.priority)]
    if new.labels:
        a += ["--labels", ",".join(new.labels)]
    if new.deps:
        a += ["--deps", ",".join(new.deps)]
    return a + (["--no-inherit-labels"] if new.no_inherit_labels else [])


def update_argv(bead: str, patch: BeadPatch) -> list[str]:
    a = ["update", bead]
    if patch.status:
        a += ["--status", patch.status]
    if patch.if_assignee:
        a += ["--if-assignee", patch.if_assignee]
    if patch.assignee is not None:
        a += ["--assignee", patch.assignee]
    if patch.description is not None:
        a += ["--description", patch.description]
    if patch.notes is not None:
        a += ["--notes", patch.notes]
    if patch.metadata is not None:
        a += ["--metadata", json.dumps(patch.metadata)]
    for k, v in patch.set_metadata.items():
        a += ["--set-metadata", f"{k}={v}"]
    for k in patch.unset_metadata:
        a += ["--unset-metadata", k]
    return a


def find_argv(query: BeadQuery) -> list[str]:
    a = ["list", "-n", "0"]
    if query.include_closed:
        a.append("--all")
    if query.status:
        a += ["--status", query.status]
    if query.label:
        a += ["--label", query.label]
    return a


class BdStore:
    def __init__(self, actor: str, cwd: str | None = None, exe: str = "", run: Runner | None = None, timeout: float | None = None) -> None:
        self.actor, self.cwd, self.timeout = actor, cwd, timeout
        self._run: Runner = run or (lambda argv, where: subprocess_runner(argv, where, timeout))
        self.exe = exe or shutil.which("bd") or "bd"

    def at(self, cwd: str) -> BdStore:
        return BdStore(self.actor, cwd, self.exe, self._run, self.timeout)

    def _call(self, *args: str) -> BdRun:
        return self._run([self.exe, "--actor", self.actor, *args, "--json"], self.cwd)

    def _must(self, *args: str) -> BdRun:
        r = self._call(*args)
        if r.code != 0:
            raise BdFailure(error_of(r.err, r.out))
        return r

    def passthrough(self, args: list[str]) -> BdRun:
        """`tl bd ...`: whatever the person typed, with the actor and JSON like every call. A `dolt push` bd answered with a
        rejection but exit 0 exits 1 here."""
        r = self._call(*args)
        if r.code == 0 and args[:2] == ["dolt", "push"] and PUSH_REJECTED.search(r.err + r.out):
            return BdRun(1, r.out, r.err)
        return r

    def dolt_push(self) -> DoltPush:
        """`bd sync`: pull, merge-conflict check, push with retries. It is the land's push because its exit codes are positive
        (0 synced, 1 error, 2 conflict, 3 retries exhausted, 4 stuck) where `bd dolt push` exits 0 on a rejection; a rejection
        text under exit 0 still counts as a failure."""
        r = self._call("sync", "--no-adopt")  # never adopt git origin as a Dolt remote on its own: no remote stays a quiet skip
        text = (r.err or r.out).strip()
        if r.code == 0 and PUSH_REJECTED.search(r.err + r.out):
            return DoltPush(1, text)
        return DoltPush(r.code, text)

    def show(self, bead: str) -> Bead | None:
        r = self._call("show", bead)
        if r.code != 0:
            err = error_of(r.err, r.out)
            if err.kind == "not_found":
                return None
            raise BdFailure(err)
        found = beads_of(_loads(r.out))
        return found[0] if found else None

    def comments(self, bead: str) -> list[Comment]:
        r = self._call("comments", bead)
        return comments_of(_loads(r.out)) if r.code == 0 else []

    def find(self, query: BeadQuery) -> list[Bead]:
        return beads_of(_loads(self._must(*find_argv(query)).out))

    def ready(self, label: str = "") -> list[Bead]:
        return beads_of(_loads(self._must("ready", "-n", "0", *(["--label", label] if label else [])).out))

    def create(self, new: NewBead) -> str:
        made = _loads(self._must(*create_argv(new)).out)
        if not isinstance(made, dict) or not made.get("id"):
            raise BdFailure(error_of("bd create answered without an id", ""))
        return str(made["id"])

    def update(self, bead: str, patch: BeadPatch) -> None:
        self._must(*update_argv(bead, patch))

    def claim(self, bead: str) -> bool:
        return self._call("update", bead, "--claim").code == 0

    def unclaim(self, bead: str, force: bool = False) -> bool:
        return self._call("unclaim", bead, *(["--force"] if force else [])).code == 0

    def heartbeat(self, bead: str) -> None:
        self._must("heartbeat", bead)

    def close(self, bead: str, reason: str) -> None:
        self._must("close", bead, "--reason", reason)

    def add_comment(self, bead: str, text: str) -> None:
        self._must("comments", "add", bead, text)

    def add_label(self, bead: str, label: str) -> None:
        self._must("label", "add", bead, label)

    def remove_label(self, bead: str, label: str) -> None:
        self._must("label", "remove", bead, label)

    def reclaim(self, older_than: str, assignees: list[str]) -> None:
        self._must("reclaim", "--older-than", older_than, *[x for w in assignees for x in ("--assignee", w)])

    def provenance(self, bead: str, kind: str, source: str, ref: str = "", ref_kind: str = "", at: str = "", payload: str = "") -> None:
        a = ["provenance", "record", "--issue", bead, "--kind", kind, "--source", source]
        a += ["--ref", ref, "--ref-kind", ref_kind] if ref else ["--at", at]
        self._must(*a, *(["--payload", payload] if payload else []))
