"""Real layer, the land on real Git and real processes (tl-8bh9.14.8 slice L3): a bare `remote.git` under tmp_path is
`origin` (a `file://` URL) of a person's checkout with one adopted `--detach` slot; `task/tl-1` holds X on both sides
and factory.db its done implement attempt and passed checks. The land runs through `git_views.remotes` (hooks off,
bounded transport) and the real slot environment, block (`sh -c` checks through the shelf's registered start), slot lock
and process observations; only the tracker is a double. Set-up runs through `git_porcelain.testing`'s runner; nothing
leaves tmp_path."""

import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

import pytest
from beads_client import Bead
from git_porcelain.history import Identity
from git_porcelain.testing import apply_hermetic_env, git
from land_bench import NoBeats, database
from stream_proc import group_alive

from taskloop.agent_credentials import scrubbed
from taskloop.check_store import CheckStore
from taskloop.checks import Block, BlockPorts, argv_digest
from taskloop.claim_lease import Beat, Heartbeat
from taskloop.composition import Checking
from taskloop.environment import EnvironmentPorts, Preparation
from taskloop.evidence_files import EvidenceFiles
from taskloop.git_views import GitProfileFiles, checkouts, remotes, slot_profiles
from taskloop.land import Landed, LandRequest, LandResult, land
from taskloop.land_check import LandPorts
from taskloop.land_store import LandStore
from taskloop.operations import Failed
from taskloop.owned_processes import entry_seen, setup_seen, this_process
from taskloop.setup_store import SetupStore
from taskloop.slot_env import RealEnvFiles, setup_process
from taskloop.slot_files import RealSlotFiles
from taskloop.slot_lock import landing
from taskloop.task import TaskBinding, TaskInspection, TaskScope
from taskloop.tracker import inspect_task
from taskloop.tracker_client import Closed

CHECK = ["/bin/sh", "-c", "test -f src/x.py"]
PROFILE = {"setup": [["/bin/sh", "-c", "true"]], "required": ["has-x"], "checks": [{"name": "has-x", "argv": CHECK, "timeout": 60}]}


class Tracker:
    title = "Widget"

    def show(self, task_id: str) -> Bead:
        return Bead(task_id, title=self.title, description="It must do X", status="in_progress", assignee="taskloop")


def heartbeat_for(_root: str, _task: str) -> Heartbeat:
    def beat() -> Beat:
        return "held"

    return beat


class Real:
    """A bare origin, the person's checkout (`main` at B with the profile), its slot s1 at B (D), and X on `task/tl-1`."""

    def __init__(self, root: Path) -> None:
        self.root, self.remote, self.main = root, root / "remote.git", root / "repo"
        self.closed: list[tuple[str, str]] = []
        self.tracker = Tracker()
        git(root, "init", "-q", "--bare", "-b", "main", str(self.remote))
        self.main.mkdir()
        git(self.main, "init", "-q", "-b", "main")
        (self.main / "README").write_text("one\n")
        (self.main / ".task-loop.json").write_text(json.dumps(PROFILE))
        git(self.main, "add", "README", ".task-loop.json")
        git(self.main, "commit", "-q", "-m", "base")
        git(self.main, "remote", "add", "origin", self.remote.as_uri())
        git(self.main, "push", "-q", "origin", "main")
        self.base = self.rev(self.main, "HEAD")
        repo_id = checkouts(self.main).identity().key
        self.slot = root / "slots" / repo_id / "s1"
        git(self.main, "worktree", "add", "-q", "--detach", str(self.slot), "HEAD")
        git(self.main, "switch", "-q", "-c", "task/tl-1")
        (self.main / "src").mkdir()
        (self.main / "src" / "x.py").write_text("X = 1\n")
        git(self.main, "add", "src/x.py")
        git(self.main, "commit", "-q", "-m", "the task's commit")
        git(self.main, "push", "-q", "origin", "task/tl-1")
        self.x = self.rev(self.main, "HEAD")
        git(self.main, "switch", "-q", "main")
        self.con = database(root / "factory.db", repo_id, self.slot, self.base, self.x, self.base)
        self.con.execute("UPDATE checks_attempt SET required=?", (json.dumps([["has-x", argv_digest(CHECK)]]),))

    @staticmethod
    def rev(where: Path, name: str) -> str:
        return git(where, "rev-parse", name).strip()

    def origin(self, name: str = "main") -> str:
        return git(self.remote, "rev-parse", name).strip()

    def person(self) -> tuple[str, str, str]:
        """The person's checkout as land must leave it: HEAD, `refs/heads/main` and the index file's digest."""
        index = Path(git(self.main, "rev-parse", "--git-path", "index").strip())
        index = index if index.is_absolute() else self.main / index
        return self.rev(self.main, "HEAD"), self.rev(self.main, "refs/heads/main"), hashlib.sha256(index.read_bytes()).hexdigest()

    def moved(self) -> str:
        """Another clone lands on origin's `main` first; returns its tip."""
        other = self.root / "other"
        git(self.root, "clone", "-q", self.remote.as_uri(), str(other))
        (other / "OTHER").write_text("another task\n")
        git(other, "add", "OTHER")
        git(other, "commit", "-q", "-m", "another task")
        git(other, "push", "-q", "origin", "main")
        return self.rev(other, "HEAD")

    def ports(self) -> LandPorts:
        art, con = self.root / "art", self.con
        setup = SetupStore(lambda: con)
        preparation = Preparation(EnvironmentPorts(
            setup, checkouts, slot_profiles, RealEnvFiles(), setup_process, setup_seen, group_alive, EvidenceFiles(art), time.time,
            sys.platform, shutil.rmtree.avoids_symlink_attacks, lambda *_probe: True, (art,), 4096))  # tmp_path is long
        environ = {"PATH": os.environ["PATH"], "HOME": str(self.root)}
        work = Checking(CheckStore(lambda: con), setup, EvidenceFiles(art), checkouts, RealSlotFiles(), slot_profiles, preparation,
                        Block(BlockPorts(setup_process, group_alive, time.time)), setup_seen, entry_seen,
                        RealEnvFiles().empty_scratch, time.time, lambda: scrubbed(environ))
        return LandPorts(work, LandStore(lambda: con), remotes, lambda path: GitProfileFiles(path, remotes), self.tasks, heartbeat_for,
                         NoBeats, this_process, lambda _path: True, landing, dict(os.environ), self.close)

    def tasks(self, task_id: str, backlog: str, root: str) -> TaskInspection:
        return inspect_task(TaskBinding(TaskScope(backlog), Path(root)), self.tracker, task_id)

    def close(self, _root: str, task_id: str, reason: str) -> Closed:
        self.closed.append((task_id, reason))
        return "closed"

    def land(self) -> LandResult:
        return land(self.ports(), LandRequest("tasks", "tl-1", self.main, 5))


@pytest.fixture
def real(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Real:
    apply_hermetic_env(monkeypatch, identity=Identity("Person", "person@example.invalid"), config={})
    return Real(tmp_path.resolve())


def test_a_land_onto_a_moved_main_validates_s_and_pushes_it_and_leaves_the_person_s_checkout_alone(real: Real) -> None:
    o, before = real.moved(), real.person()
    found = real.land()
    assert isinstance(found, Landed) and found.how == "pushed" and found.row.validation == "passed"
    s = found.row.commit
    assert real.origin() == s and real.rev(real.main, f"{s}^") == o and real.rev(real.main, f"{s}^@") == o  # one parent: O
    names = git(real.main, "ls-tree", "-r", "--name-only", s).split()
    assert sorted(names) == [".task-loop.json", "OTHER", "README", "src/x.py"]  # X's change merged onto O
    assert git(real.main, "show", f"{s}:src/x.py") == "X = 1\n" and git(real.main, "show", f"{s}:OTHER") == "another task\n"
    assert real.person() == before and real.origin("task/tl-1") == real.x
    assert real.rev(real.slot, "HEAD") == real.base and git(real.slot, "status", "--porcelain").strip() == ""  # parked at D
    assert real.con.execute("SELECT count(*) FROM reservation").fetchone() == (0,)


def test_the_same_tree_lands_with_x_s_tree_and_no_slot(real: Real) -> None:
    before = real.person()
    found = real.land()
    assert isinstance(found, Landed) and found.row.validation == "same_tree"
    s = found.row.commit
    assert real.origin() == s and real.rev(real.main, f"{s}^") == real.base
    assert real.rev(real.main, f"{s}^{{tree}}") == real.rev(real.main, f"{real.x}^{{tree}}") and s != real.x
    assert real.person() == before
    assert git(real.main, "log", "-1", "--format=%an <%ae> %cn <%ce>", s).strip() == (
        "Person <person@example.invalid> Person <person@example.invalid>")
    text = git(real.main, "log", "-1", "--format=%B", s)
    assert text.startswith(f"Widget (tl-1)\n\nSquashed from task/tl-1 at {real.x}:\n- the task's commit ({real.x[:12]})\n")
    assert git(real.main, "log", "-1", "--format=%(trailers:only,unfold)", s).split() == [
        "Task:", "tl-1", "Checked:", "checks", "passed", "at", real.x]
    assert found.row.close == "closed" and real.closed == [("tl-1", f"Landed {s} on main (task/tl-1 at {real.x})")]


def test_a_pushurl_elsewhere_is_refused_and_nothing_is_pushed_anywhere(real: Real) -> None:
    elsewhere = real.root / "elsewhere.git"
    git(real.root, "init", "-q", "--bare", "-b", "main", str(elsewhere))
    git(real.main, "config", "remote.origin.pushurl", elsewhere.as_uri())
    found = real.land()
    assert isinstance(found, Failed) and (found.kind, found.reason) == ("refused", "push_url")
    assert real.origin() == real.base and git(elsewhere, "for-each-ref").strip() == ""
    assert str(elsewhere) not in found.detail


def test_no_origin_is_refused_no_remote(real: Real) -> None:
    git(real.main, "remote", "remove", "origin")
    found = real.land()
    assert isinstance(found, Failed) and (found.kind, found.reason) == ("refused", "no_remote")


def test_a_hostile_title_adds_no_trailer_that_git_reads(real: Real) -> None:
    """Git's own trailer parser over S: a title carrying newlines and trailer lines stays the subject."""
    real.tracker.title = "Fix\n\nTask: tl-9\nCo-Authored-By: Mallory <m@example.invalid>\x1b[31m"
    found = real.land()
    assert isinstance(found, Landed)
    s = found.row.commit
    assert git(real.main, "log", "-1", "--format=%s", s).strip() == "Fix Task: tl-9 Co-Authored-By: Mallory <m@example.invalid> [31m (tl-1)"
    assert git(real.main, "log", "-1", "--format=%(trailers:key=Task,valueonly)", s).split() == ["tl-1"]
    assert git(real.main, "log", "-1", "--format=%(trailers:key=Co-Authored-By)", s).strip() == ""
