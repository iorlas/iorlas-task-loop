"""Plain test doubles shared by the plan tests; fixtures stay in conftest.py."""

import json
import os
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path

from beads_client import Bead
from git_porcelain import GitUnavailable, Recorded, Repo
from git_porcelain.testing import FakeRepo, FakeWorktree
from sqlite_store import Store, begin_immediate
from stream_proc import OwnedProcess

from taskloop.access import TMP_BYTES, Folders
from taskloop.admit import AdmitResult
from taskloop.admit_chain import NextStepRequest
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, Checkouts, EntryIdentity, FileStat
from taskloop.check_admit import ChecksAdmission, ChecksRequest
from taskloop.environment import EnvironmentPorts, Preparation, SetupEnded
from taskloop.evidence_files import EvidenceFiles
from taskloop.factory_schema import SCHEMA
from taskloop.git_views import GitProfileFiles
from taskloop.launch import Launched, LaunchResult
from taskloop.operations import ChecksPorts
from taskloop.profile import NoCommit, NotAFile, ProfileFiles, Unavailable
from taskloop.setup_store import ProcessSeen, SetupStore
from taskloop.slot_release import ReleaseResult
from taskloop.task import TaskBinding, TaskInspection, TaskScope
from taskloop.tracker import inspect_task
from taskloop.tracker_client import HoldAnswer, HoldWrite, LabelStep, TrackerHolds

# The `checking` fixture's checks attempt: its key, its slot's HEAD D, the implement attempt's X, its target (`main`'s
# commit at admission), and the required names with their argv digests at the target.
CHECKS = AttemptKey("checks", "checks-token", 1)
D, X, TARGET = "d" * 40, "c" * 40, "f" * 40
REQUIRED = (("check", "1" * 64), ("test", "2" * 64))
# The `landing` fixture's land candidate of `CHECKS`: its key, O (origin's `main` as fetched) and S (the squash commit).
CANDIDATE = AttemptKey("candidate", "candidate-token", 1)
ORIGIN, SQUASH = "0" * 40, "5" * 40


# A profile at `main` requiring `check` and `test` and defining a third, non-required check.
MAIN_PROFILE = {"setup": [["just", "bootstrap"]], "required": ["check", "test"], "checks": [
    {"name": "check", "argv": ["just", "check"], "timeout": 600}, {"name": "test", "argv": ["just", "test"], "timeout": 600},
    {"name": "slow", "argv": ["sleep", "1"], "timeout": 60}]}


def main_at(slot: FakeWorktree) -> str:
    """The person's `main` fast-forwarded to the slot's detached HEAD (a commit made there before dispatch): a new task
    branch starts at `main`'s tip, so this is where B is."""
    found = next(info.head for info in slot.repo.worktrees() if info.path == slot.path)
    assert found is not None
    slot.repo.worktree(slot.repo.identity().root).merge_ff(found)
    return found


class RegisteringLauncher:
    """The launcher: registers the task's current attempt's entry in factory.db as the real one does, then reports it
    launched; `entry` fixed, else a new identity per attempt."""

    def __init__(self, store: AttemptStore, entry: EntryIdentity | None = None) -> None:
        self.store, self.entry, self.calls, self.minutes = store, entry, list[AttemptKey](), list[int]()

    def launch(self, backlog: str, task_id: str, minutes: int) -> LaunchResult:
        found = self.store.attempt_of(backlog, task_id)
        assert found is not None
        entry = self.entry or (8 + len(self.calls), "start", "boot")
        self.calls.append(found[0])
        self.minutes.append(minutes)
        assert self.store.register_entry(found[0], entry, 10) == "accepted"
        return Launched(found[0], entry)


@dataclass(frozen=True)
class Done:
    """The `done` fixture: its factory.db, the implement attempt's key and X, `main`'s commit (the target) and the free
    slot's HEAD D."""

    path: Path
    implement: AttemptKey
    x: str
    target: str
    d: str


class FakeSlotFiles:
    """The slot file port over the Git fake: each linked worktree it has seen listed keeps a valid pointer into the fake's
    common directory (with its `commondir` and `gitdir` back-pointer), and its files are the fake checkout's, regular and
    0644. `entries` and `contents` override any path: a rewritten pointer, a symlink, a FIFO, an executable file."""

    def __init__(self, repo: FakeRepo) -> None:
        self.repo, self.common = repo, repo.identity().common_dir
        self.known: dict[Path, FakeWorktree] = {}
        self.entries: dict[Path, FileStat | None] = {}
        self.contents: dict[Path, bytes] = {}
        self.resolved: dict[Path, Path | None] = {}

    @property
    def slots(self) -> tuple[FakeWorktree, ...]:
        try:
            listed = self.repo.worktrees()
        except GitUnavailable:
            listed = ()
        for info in listed:
            if not info.is_main:
                self.known.setdefault(info.path, self.repo.worktree(info.path))
        return tuple(self.known.values())

    def _gitdir(self, slot: FakeWorktree) -> Path:
        return self.common / "worktrees" / slot.path.name

    @staticmethod
    def _files(slot: FakeWorktree) -> dict[str, bytes]:
        try:
            return slot.state().files
        except GitUnavailable:  # a dropped checkout has no files
            return {}

    def _data(self, path: Path) -> bytes | None:
        if path in self.contents:
            return self.contents[path]
        for slot in self.slots:
            pointers = {
                slot.path / ".git": f"gitdir: {self._gitdir(slot)}\n".encode(),
                self._gitdir(slot) / "commondir": b"../..\n",
                self._gitdir(slot) / "gitdir": f"{slot.path / '.git'}\n".encode(),
            }
            if path in pointers:
                return pointers[path]
            if path.is_relative_to(slot.path) and path != slot.path:
                return self._files(slot).get(path.relative_to(slot.path).as_posix())
        return None

    def _folder(self, path: Path) -> bool:
        for slot in self.slots:
            if path in (slot.path, self._gitdir(slot)):
                return True
            if path.is_relative_to(slot.path):
                prefix = path.relative_to(slot.path).as_posix() + "/"
                return any(name.startswith(prefix) for name in self._files(slot))
        return False

    def lstat(self, path: Path) -> FileStat | None:
        if path in self.entries:
            return self.entries[path]
        data = self._data(path)
        if data is not None:
            return FileStat("file", len(data), False)
        return FileStat("dir", 0, False) if self._folder(path) else None

    def resolve(self, path: Path) -> Path | None:
        """No symlinks in the fake unless `resolved` names one; `..` folds as the operating system would."""
        return self.resolved.get(path, Path(os.path.normpath(path)))

    def read(self, path: Path, cap: int) -> bytes | None:
        entry = self.lstat(path)
        return None if entry is None or entry.kind != "file" or entry.size > cap else self._data(path)


class PinnedViews:
    """`Checkouts` over the Git fake that holds every consumer to the pin rule (design .7 section 4(a)): the person's
    checkout (the fake's root, or a directory in it) opens unpinned, any other path only with `git_dir` equal to the G
    its slot pointer names (`FakeSlotFiles`' `<common>/worktrees/<name>`); anything else fails the test at the open. The
    root of another repository in `others` opens unpinned as that repository (a pointer may name it). `opened` records
    every (path, git_dir)."""

    def __init__(self, repo: FakeRepo, *others: FakeRepo) -> None:
        self.repo, self.root, self.common = repo, repo.identity().root, repo.identity().common_dir
        self.others = {other.identity().root: other for other in others}
        self.opened: list[tuple[Path, Path | None]] = []

    def __call__(self, path: Path, /, *, git_dir: Path | None = None) -> Repo:
        self.opened.append((path, git_dir))
        if git_dir is None and path in self.others:
            return self.others[path]
        expected = None if path.is_relative_to(self.root) else self.common / "worktrees" / path.name
        assert git_dir == expected, f"{path} opened with git_dir={git_dir}, not {expected}"
        return self.repo

    def slot_opens(self, path: Path) -> list[Path | None]:
        """The `git_dir` of every open of `path`."""
        return [git_dir for where, git_dir in self.opened if where == path]


def linked_into(files: FakeSlotFiles, slot: Path, other: FakeRepo) -> Path:
    """Rewrite `<slot>/.git` to a well-formed linked Git directory of `other` (G under `<C>/worktrees`, `commondir`, a
    back-pointer to the slot): the layout check alone passes, only the repository binding refuses it. Returns G."""
    gitdir = other.identity().common_dir / "worktrees" / slot.name
    files.contents[slot / ".git"] = f"gitdir: {gitdir}\n".encode()
    files.entries[gitdir] = FileStat("dir", 0, False)
    files.contents[gitdir / "commondir"] = b"../..\n"
    files.contents[gitdir / "gitdir"] = f"{slot / '.git'}\n".encode()
    return gitdir


class NoAdvance:
    """The advance port of a start that never finds a done step to advance."""

    def admit_next(self, request: NextStepRequest) -> AdmitResult:
        raise AssertionError(f"no advance expected: {request.previous}")


class NoChecks:
    """The checks admission and launcher of a start that never reaches the check step."""

    def admit_checks(self, request: ChecksRequest) -> AdmitResult:
        raise AssertionError(f"no checks admission expected: {request.previous}")

    def launch(self, backlog: str, task_id: str, minutes: int) -> LaunchResult:
        raise AssertionError(f"no checks launch expected: {task_id}")

    def release(self, key: AttemptKey, abandon: bool, me: EntryIdentity | None = None) -> ReleaseResult:
        raise AssertionError(f"no checks release expected: {key.attempt_id}")

    def release_candidate(self, key: AttemptKey, abandon: bool, me: EntryIdentity | None = None) -> ReleaseResult:
        raise AssertionError(f"no land candidate release expected: {key.attempt_id}")


def no_holds() -> TrackerHolds:
    """The tracker's hold writes of a round that never holds a task nor clears a hold."""

    def refuse(*args: str) -> HoldAnswer[LabelStep]:
        raise AssertionError(f"no hold tracker write expected: {args}")

    def unexpected(*args: str) -> HoldAnswer[HoldWrite]:
        raise AssertionError(f"no hold tracker write expected: {args}")

    return TrackerHolds(refuse, unexpected, unexpected)


NO_CHECKS = ChecksPorts(NoChecks(), NoChecks(), NoChecks())


type Blob = bytes | NoCommit | NotAFile | Unavailable | None


class FakeProfiles:
    """The slot profile port: the same `.task-loop.json` blob at every commit (`setup` given, or raw `blob`); `opened`
    records each (slot, Git directory) and `read` each commit."""

    def __init__(self, setup: Sequence[Sequence[str]] = (("just", "bootstrap"),), blob: Blob = b"") -> None:
        self.data: Blob = blob if blob != b"" else json.dumps({"setup": [list(argv) for argv in setup]}).encode()
        self.opened: list[tuple[Path, Path]] = []
        self.read: list[str] = []

    def __call__(self, slot: Path, gitdir: Path) -> ProfileFiles:
        self.opened.append((slot, gitdir))
        return self

    def blob(self, commit: str, path: str) -> Blob:
        self.read.append(commit)
        return self.data


@dataclass(frozen=True)
class Command:
    """One scripted setup command: how it ends, what it prints, what it does to the slot while it runs."""

    rc: int | None = 0
    timed_out: bool = False
    exec_failed: bool = False
    uncertain: bool = False
    spawn_error: bool = False  # the start fails before any registration
    lingering: bool = False  # a process stays in its group after it ended
    survivors: bool = False  # the stop (a timeout) left a process of its tree alive
    supervision_error: bool = False  # the supervision fails (OSError) after the command started
    effect: Callable[[], object] | None = None
    output: bytes = b"done\n"


@dataclass(frozen=True)
class SetupCall:
    argv: tuple[str, ...]
    cwd: str
    env: Mapping[str, str]
    timeout: float


@dataclass
class FakeSetupProcess:
    """The registered start, semantically: the identity is passed to `registered` before the command "executes" (its
    effect and output), as the shelf's exec gate does; a registration failure propagates with nothing executed. Commands
    follow `script`, then succeed. `events` is shared with the other fakes to observe the order."""

    events: list[str]
    script: list[Command] = field(default_factory=list)
    calls: list[SetupCall] = field(default_factory=list)
    groups: set[int] = field(default_factory=set)
    next_pid: int = 500

    def __call__(
        self, argv: Sequence[str], *, registered: Callable[[OwnedProcess], None], cwd: str, env: Mapping[str, str],
        timeout: float, line: Callable[[bytes], None],
    ) -> SetupEnded:
        command = self.script.pop(0) if self.script else Command()
        self.calls.append(SetupCall(tuple(argv), cwd, dict(env), timeout))
        if command.spawn_error:
            raise OSError("fork")
        self.next_pid += 1
        pid = self.next_pid
        registered(OwnedProcess(pid, pid, f"start-{pid}", "boot"))
        self.events.append("exec " + " ".join(argv))
        if command.uncertain:
            return SetupEnded(None, False, False, pid, uncertain=True)
        if not command.exec_failed:
            if command.effect is not None:
                command.effect()
            line(command.output)
        if command.lingering:
            self.groups.add(pid)
        if command.supervision_error:
            raise OSError("pump")
        return SetupEnded(command.rc, command.timed_out, command.exec_failed, pid, survivors=command.survivors)

    def lingering(self, pgid: int) -> bool:
        self.events.append(f"group {pgid}")
        return pgid in self.groups


@dataclass
class FakeEnvFiles:
    """The environment folders: what is ensured, what is emptied (in `events`, by the last two path parts), and
    folders whose emptying or creation fails. `links` resolves a path at or under a key as if that key were a link to
    its value; a path in `unresolvable` cannot be resolved."""

    events: list[str]
    unemptiable: set[Path] = field(default_factory=set)
    unmakeable: set[Path] = field(default_factory=set)
    links: dict[Path, Path] = field(default_factory=dict)
    unresolvable: set[Path] = field(default_factory=set)

    def resolve(self, path: Path) -> Path | None:
        if path in self.unresolvable:
            return None
        link = next((each for each in self.links if path.is_relative_to(each)), None)
        return path if link is None else self.links[link] / path.relative_to(link)

    def ensure(self, path: Path) -> bool:
        self.events.append(f"ensure {path.parent.name}/{path.name}")
        return path not in self.unmakeable

    def empty(self, path: Path) -> bool:
        self.events.append(f"empty {path.parent.name}/{path.name}")
        return path not in self.unemptiable


@dataclass(frozen=True)
class ProbeCall:
    exe: str
    env: Mapping[str, str]
    folders: Folders


@dataclass
class Environment:
    """A `Preparation` over fakes and real SQLite and evidence files; `seen` answers for a registered setup command;
    `sandbox` is the probe's answer (each probe recorded in `probes` and `events`). `protected` are the paths no root may
    overlap; `tmp_bytes` the TMPDIR budget (widened only where the slot sits under a long tmp_path)."""

    con: sqlite3.Connection
    checkouts: Checkouts
    artifacts: Path
    events: list[str] = field(default_factory=list)
    seen: dict[int, ProcessSeen] = field(default_factory=dict)
    platform: str = "linux"
    safe_removal: bool = True
    clock: Callable[[], float] = lambda: 10
    profiles: FakeProfiles = field(default_factory=FakeProfiles)
    sandbox: bool = True
    protected: tuple[Path, ...] = ()
    tmp_bytes: int = TMP_BYTES
    probes: list[ProbeCall] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.process = FakeSetupProcess(self.events)
        self.files = FakeEnvFiles(self.events)

    def probe(self, exe: str, env: Mapping[str, str], found: Folders) -> bool:
        self.events.append("probe")
        self.probes.append(ProbeCall(exe, dict(env), found))
        return self.sandbox

    def observe(self, process: OwnedProcess) -> ProcessSeen:
        self.events.append(f"seen {process.pid}")
        return self.seen.get(process.pid, "gone")

    def preparation(self) -> Preparation:
        return Preparation(EnvironmentPorts(
            SetupStore(lambda: self.con), self.checkouts, self.profiles, self.files, self.process, self.observe,
            self.process.lingering, EvidenceFiles(self.artifacts), self.clock, self.platform, self.safe_removal, self.probe,
            self.protected, self.tmp_bytes,
        ))


@dataclass
class ChecksBench:
    """A checks admission's ports over the `done` factory.db (the person's checkout and its profile reader, the slot
    ports): `status`/`assignee` are the task in the tracker (each read in `reads`); `racing` runs once right before the
    admission's write transaction (another actor's commit)."""

    done: Done
    repo: FakeRepo
    views: PinnedViews
    files: FakeSlotFiles
    status: str = "in_progress"
    assignee: str = "taskloop"
    now: float = 10
    reads: list[str] = field(default_factory=list)
    racing: Callable[[], object] = lambda: None

    def __post_init__(self) -> None:
        con = Store(SCHEMA).open_rw(self.done.path)
        assert con is not None
        self.con: sqlite3.Connection = con
        self.root = self.repo.worktree(self.repo.identity().root)

    def show(self, task_id: str) -> Bead:
        return Bead(task_id, title="Widget", description="It must do X", status=self.status, assignee=self.assignee)

    def inspect(self, task_id: str, backlog: str, root: str) -> TaskInspection:
        self.reads.append(task_id)
        return inspect_task(TaskBinding(TaskScope(backlog), Path(root)), self, task_id)

    def begin(self, con: sqlite3.Connection) -> AbstractContextManager[None]:
        racing, self.racing = self.racing, lambda: None
        racing()
        return begin_immediate(con)

    def admission(self) -> ChecksAdmission:
        return ChecksAdmission(lambda: self.con, self.begin, self.inspect, self.views, lambda: self.now, lambda _p: True, self.files,
                               lambda path: GitProfileFiles(path, self.views))

    def admit(self, number: int = 1, checkout: Path | None = None) -> AdmitResult:
        return self.admission().admit_checks(ChecksRequest(self.done.implement, checkout or self.repo.path, 100.0, number))

    def stored(self) -> tuple[list[tuple[object, ...]], list[tuple[object, ...]]]:
        rows = "SELECT number,slot,slot_head,target_commit,required,deadline,phase,after_attempt_id FROM checks_attempt ORDER BY number"
        held = "SELECT slot,attempt_id,generation FROM reservation ORDER BY attempt_id"
        return self.con.execute(rows).fetchall(), self.con.execute(held).fetchall()

    def main(self, profile: dict[str, object] | None) -> str:
        """A commit on the person's `main` with this profile (None: without one); returns it."""
        if profile is None:
            self.root.remove_file(".task-loop.json")
        else:
            self.root.write_file(".task-loop.json", json.dumps(profile))
        made = self.root.record("main moves", paths="all")
        assert isinstance(made, Recorded)
        return made.sha

    def concluded(self, conclusion: str = "failed", released: bool = True, abandoned: bool = False) -> None:
        """The latest checks attempt concluded as given (and released, abandoned), as the entry and a release leave it."""
        reason = "test:failed" if conclusion == "failed" else None
        self.con.execute("UPDATE checks_attempt SET phase='concluded',conclusion=?,reason=?,concluded_at=20", (conclusion, reason))
        if released:
            self.con.execute("UPDATE checks_attempt SET released_at=30,parked=?,abandoned=?", (self.done.d, int(abandoned)))
            self.con.execute("DELETE FROM reservation")
