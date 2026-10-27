"""`Beads` over the `bd` command: `bd --actor <who> ... --json`, one call per method."""
import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from taskloop.adapters import bd_json
from taskloop.contracts.bead import Bead, Comment
from taskloop.contracts.ports import BdFailure, BeadPatch, BeadQuery, NewBead


@dataclass(frozen=True)
class BdRun:
    code: int
    out: str
    err: str


Runner = Callable[[list[str], str | None], BdRun]


def subprocess_runner(argv: list[str], cwd: str | None) -> BdRun:
    r = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    return BdRun(r.returncode, r.stdout, r.stderr)


def _json(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return None


def create_argv(new: NewBead) -> list[str]:
    a = ["create", new.title, "--type", new.issue_type, "--json"]
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
    if patch.assignee is not None:
        a += ["--assignee", patch.assignee]
    if patch.description is not None:
        a += ["--description", patch.description]
    for k, v in patch.set_metadata.items():
        a += ["--set-metadata", "%s=%s" % (k, v)]
    for k in patch.unset_metadata:
        a += ["--unset-metadata", k]
    return a


class BdBeads:
    def __init__(self, actor: str, cwd: str | None = None, exe: str = "", run: Runner = subprocess_runner) -> None:
        self.actor, self.cwd, self._run = actor, cwd, run
        self.exe = exe or shutil.which("bd") or "bd"

    def _call(self, *args: str) -> BdRun:
        return self._run([self.exe, "--actor", self.actor, *args], self.cwd)

    def _must(self, *args: str) -> BdRun:
        r = self._call(*args)
        if r.code != 0:
            raise BdFailure(bd_json.error_of(r.err, r.out))
        return r

    def show(self, bead: str) -> Bead | None:
        r = self._call("show", bead, "--json")
        found = bd_json.beads_of(_json(r.out)) if r.code == 0 else []
        return found[0] if found else None

    def comments(self, bead: str) -> list[Comment]:
        r = self._call("comments", bead, "--json")
        return bd_json.comments_of(_json(r.out)) if r.code == 0 else []

    def find(self, query: BeadQuery) -> list[Bead]:
        a = ["list", "--json", "-n", "0"]
        if query.include_closed:
            a.append("--all")
        if query.status:
            a += ["--status", query.status]
        if query.label:
            a += ["--label", query.label]
        return bd_json.beads_of(_json(self._must(*a).out))

    def ready(self) -> list[Bead]:
        return bd_json.beads_of(_json(self._must("ready", "--json").out))

    def create(self, new: NewBead) -> str:
        made = _json(self._must(*create_argv(new)).out)
        if not isinstance(made, dict) or not made.get("id"):
            raise BdFailure(bd_json.error_of("bd create answered without an id", ""))
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
