"""``Bd``: every bd verb a driver needs, as typed methods. Every call is ``bd --actor <who> <args> --json``."""

from __future__ import annotations

import json
import re
import shutil
import time
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from beads_client.classify import LOCKED, PUSH_REJECTED, error_of, loads
from beads_client.errors import BdError, malformed, version_mismatch
from beads_client.records import Bead, Comment, NewBead, beads_of, comments_of
from beads_client.runner import BdRun, Runner, subprocess_runner

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

TESTED_FROM = (1, 3, 1)
TESTED_BELOW = (1, 4, 0)


@dataclass(frozen=True)
class SyncResult:
    """`bd sync` outcome: 0 synced, 1 error or rejected push, 2 merge conflict, 3 retries exhausted, 4 stuck."""

    code: int
    text: str

    @property
    def ok(self) -> bool:
        return self.code == 0


def _version_tuple(text: str) -> tuple[int, ...]:
    m = re.match(r"(\d+)\.(\d+)\.(\d+)", text)
    return tuple(int(x) for x in m.groups()) if m else ()


class Bd:
    def __init__(
        self,
        actor: str,
        cwd: str | None = None,
        *,
        exe: str = "",
        timeout: float | None = None,
        run: Runner | None = None,
        lock_retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.actor, self.cwd, self.timeout = actor, cwd, timeout
        self.exe = exe or shutil.which("bd") or "bd"
        self._run: Runner = run or (lambda argv, where: subprocess_runner(argv, where, timeout))
        self._lock_retries, self._sleep = lock_retries, sleep

    def at(self, cwd: str) -> Bd:
        return Bd(self.actor, cwd, exe=self.exe, timeout=self.timeout, run=self._run, lock_retries=self._lock_retries, sleep=self._sleep)

    # ---- process -----------------------------------------------------------------------------------------------------

    def call(self, *args: str) -> BdRun:
        """Run bd, retrying a Dolt lock refusal with a short backoff. Never raises."""
        argv = [self.exe, "--actor", self.actor, *args, "--json"]
        r = self._run(argv, self.cwd)
        for attempt in range(self._lock_retries):
            if r.code == 0 or not LOCKED.search(r.err + r.out):
                break
            self._sleep(0.2 * 2**attempt)
            r = self._run(argv, self.cwd)
        return r

    def _must(self, *args: str) -> BdRun:
        r = self.call(*args)
        if r.code != 0:
            raise error_of(r)
        return r

    # ---- version -----------------------------------------------------------------------------------------------------

    def version(self) -> str:
        data = loads(self._must("version").out)
        v = data.get("version") if isinstance(data, dict) else None
        if not isinstance(v, str):
            msg = "bd version answered without a version"
            raise malformed(msg)
        return v

    def check_version(self) -> str:
        """The bd version, or BdError("version") when it is outside the range this client was tested against."""
        v = self.version()
        t = _version_tuple(v)
        if not t or not TESTED_FROM <= t < TESTED_BELOW:
            low, high = ".".join(map(str, TESTED_FROM)), ".".join(map(str, TESTED_BELOW))
            msg = f"bd {v} is outside the tested range >={low},<{high}"
            raise version_mismatch(msg)
        return v

    # ---- reads -------------------------------------------------------------------------------------------------------

    def show(self, bead: str) -> Bead | None:
        """The bead; None only when bd says it does not exist. A bd that could not be asked raises."""
        r = self.call("show", bead)
        if r.code != 0:
            err = error_of(r)
            if err.kind == "not_found":
                return None
            raise err
        found = beads_of(loads(r.out), r.out)
        return found[0]

    def comments(self, bead: str) -> list[Comment]:
        r = self._must("comments", bead)
        return comments_of(loads(r.out), r.out)

    def find(self, status: str = "", label: str = "", *, include_closed: bool = False) -> list[Bead]:
        a = ["list", "-n", "0"]
        if include_closed:
            a.append("--all")
        if status:
            a += ["--status", status]
        if label:
            a += ["--label", label]
        return self._beads(self._must(*a).out)

    def ready(self, label: str = "") -> list[Bead]:
        return self._beads(self._must("ready", "-n", "0", *(["--label", label] if label else [])).out)

    @staticmethod
    def _beads(text: str) -> list[Bead]:
        # list/ready can print nothing when there are no rows
        return [] if not text.strip() else beads_of(loads(text), text)

    # ---- writes ------------------------------------------------------------------------------------------------------

    def create(self, new: NewBead) -> str:
        made = loads(self._must(*create_argv(new)).out)
        if not isinstance(made, dict) or not isinstance(made.get("id"), str) or not made["id"]:
            msg = "bd create answered without an id"
            raise malformed(msg)
        return made["id"]

    def create_with_sections(self, new: NewBead, filler: Callable[[str], str]) -> str:
        """create; when bd's lint refuses the body for missing sections, append each as ``## Heading`` with ``filler(heading)``
        under it and try once more. The wording of the filler is the caller's."""
        try:
            return self.create(new)
        except BdError as e:
            if e.kind != "lint" or not e.missing_sections or not new.description:
                raise
            need = e.missing_sections
        have = {h.lower() for h in re.findall(r"^##\s*(.+?)\s*$", new.description, re.MULTILINE)}
        add = [f"## {h}\n{filler(h)}" for h in need if h.lower() not in have]
        body = new.description.rstrip() + ("\n\n" + "\n\n".join(add) if add else "")
        return self.create(replace(new, description=body))

    def update(
        self,
        bead: str,
        *,
        status: str | None = None,
        assignee: str | None = None,
        description: str | None = None,
        notes: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        set_metadata: Mapping[str, str] | None = None,
        unset_metadata: Sequence[str] = (),
        if_assignee: str | None = None,
        if_status: str | None = None,
    ) -> None:
        """Change fields; None leaves one alone (assignee "" clears it). ``if_assignee``/``if_status`` fence the write: bd
        compares and writes atomically, and a stale fence raises BdError("precondition") with nothing written.
        ``if_assignee=""`` requires the bead to be unassigned."""
        a = ["update", bead]
        for flag, val in (
            ("--status", status),
            ("--if-assignee", if_assignee),
            ("--if-status", if_status),
            ("--assignee", assignee),
            ("--description", description),
            ("--notes", notes),
        ):
            if val is not None:
                a += [flag, val]
        if metadata is not None:
            a += ["--metadata", json.dumps(dict(metadata))]
        for k, v in (set_metadata or {}).items():
            a += ["--set-metadata", f"{k}={v}"]
        for k in unset_metadata:
            a += ["--unset-metadata", k]
        self._must(*a)

    def claim(self, bead: str) -> bool:
        """Atomically take the bead (idempotent for its own holder). False when someone else holds it; other failures raise."""
        r = self.call("update", bead, "--claim")
        if r.code == 0:
            return True
        err = error_of(r)
        if err.kind in ("not_claimable", "precondition"):
            return False
        raise err

    def unclaim(self, bead: str, *, force: bool = False, if_assignee: str | None = None) -> bool:
        """Release a claim. False when the bead is not the caller's (or the fence is stale); other failures raise."""
        r = self.call(
            "unclaim", bead, *(["--force"] if force else []), *(["--if-assignee", if_assignee] if if_assignee is not None else [])
        )
        if r.code == 0:
            return True
        err = error_of(r)
        if err.kind in ("precondition", "not_claimable"):
            return False
        raise err

    def reclaim(self, older_than: str = "", *, ids: Sequence[str] = (), labels: Sequence[str] = (), any_replica: bool = False) -> list[str]:
        """Revert in_progress beads whose lease expired (more than ``older_than`` ago, e.g. "10m") back to open. -> their ids."""
        a = ["reclaim"]
        if older_than:
            a += ["--older-than", older_than]
        for i in ids:
            a += ["--id", i]
        for lab in labels:
            a += ["--label", lab]
        if any_replica:
            a.append("--any-replica")
        data = loads(self._must(*a).out)
        rows = data.get("reclaimed") if isinstance(data, dict) else None
        if not isinstance(data, dict) or not (rows is None or isinstance(rows, list)):
            msg = "bd reclaim answered with an unexpected shape"
            raise malformed(msg)
        return [r["id"] if isinstance(r, dict) else str(r) for r in rows or []]

    def heartbeat(self, bead: str) -> None:
        """Refresh the caller's lease on a bead it holds in_progress; raises once the lease was reclaimed or the bead closed."""
        self._must("heartbeat", bead)

    def close(self, bead: str, reason: str, *, if_assignee: str | None = None) -> None:
        if if_assignee is not None:
            # bd close has no fence and bd update sets no close reason: fence with a same-value update, then close
            self.update(bead, assignee=if_assignee, if_assignee=if_assignee)
        self._must("close", bead, "--reason", reason)

    def add_dep(self, bead: str, depends_on: str, dep_type: str = "") -> None:
        """``bead`` depends on ``depends_on`` (bd's default type is blocks). An existing edge of another type raises."""
        self._dep("add", bead, depends_on, "added", *(["--type", dep_type] if dep_type else []))

    def remove_dep(self, bead: str, depends_on: str) -> None:
        """Remove the edge; removing an absent edge is not an error in bd."""
        self._dep("remove", bead, depends_on, "removed")

    def _dep(self, verb: str, bead: str, depends_on: str, done: str, *extra: str) -> None:
        said = loads(self._must("dep", verb, bead, depends_on, *extra).out)
        if not isinstance(said, dict) or said.get("status") != done:
            msg = f"bd dep {verb} did not answer {done!r}"
            raise malformed(msg)

    def comment(self, bead: str, text: str) -> None:
        self._must("comments", "add", bead, text)

    def add_label(self, bead: str, label: str, *, if_assignee: str | None = None) -> None:
        if if_assignee is not None:
            self.update(bead, assignee=if_assignee, if_assignee=if_assignee)
        self._must("label", "add", bead, label)

    def remove_label(self, bead: str, label: str) -> None:
        self._must("label", "remove", bead, label)

    def provenance(self, bead: str, kind: str, source: str, *, ref: str = "", ref_kind: str = "", at: str = "", payload: str = "") -> None:
        """Append an idempotent provenance event. A ref names the event; a ref-less event needs ``at`` (RFC3339)."""
        if not ref and not at:
            msg = "provenance needs a ref or an at"
            raise ValueError(msg)
        a = ["provenance", "record", "--issue", bead, "--kind", kind, "--source", source]
        if ref:
            a += ["--ref", ref, *(["--ref-kind", ref_kind] if ref_kind else [])]
        else:
            a += ["--at", at]
        self._must(*a, *(["--payload", payload] if payload else []))

    def sync(self) -> SyncResult:
        """`bd sync --no-adopt`: pull, merge, push. Its exit codes are positive where `bd dolt push` exits 0 on a rejection,
        and a rejection text under exit 0 still counts as a failure. Never raises for bd's refusal."""
        r = self.call("sync", "--no-adopt")
        text = (r.err or r.out).strip()
        if r.code == 0 and PUSH_REJECTED.search(r.err + r.out):
            return SyncResult(1, text)
        return SyncResult(r.code, text)


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
