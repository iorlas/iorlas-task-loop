"""The land's bench (tl-8bh9.14.8 slice L3): a factory.db file holding tl-1's done implement attempt (X on `task/tl-1`,
published to origin) and its checks attempt 1 concluded `passed` and released; the semantic Git fake's origin (`main`
at the base B with the profile `PROFILE`) and the person's clone with one adopted, free slot s1 detached at B (D); the
real profile reader on the person's checkout, the slot environment and block over `doubles`' scripted registered start,
the real slot lock under the bench's folder, and a tracker double (its read, heartbeat and close). `test_land`,
`test_land_resume`, `test_land_push`, `test_land_close` and `test_land_summary` drive it; nothing here runs a process."""

import json
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, override

from beads_client import Bead
from doubles import CHECKS, Environment, FakeProfiles, FakeSlotFiles, PinnedViews
from git_porcelain import GitReadFailure, Pushed, Recorded, RemoteRefs, Sha
from git_porcelain.api import PushResult
from git_porcelain.testing import FakeRemote, FakeRepo, FakeWorktree
from sqlite_store import Store, begin_immediate

from taskloop import check_store
from taskloop.attempt_types import EntryIdentity, Seen
from taskloop.check_store import CheckStore
from taskloop.checks import Block, BlockPorts, argv_digest
from taskloop.claim_lease import Beat, Heartbeat
from taskloop.composition import Checking
from taskloop.evidence_files import EvidenceFiles
from taskloop.factory_schema import SCHEMA
from taskloop.git_views import GitProfileFiles
from taskloop.land import LandRequest, LandResult, land
from taskloop.land_check import LandPorts
from taskloop.land_store import LandRow, LandStore
from taskloop.setup_store import SetupStore
from taskloop.slot_lock import landing
from taskloop.task import TaskBinding, TaskInspection, TaskScope
from taskloop.tracker import inspect_task
from taskloop.tracker_client import Closed

PROFILE = {"setup": [["just", "bootstrap"]], "required": ["check", "test"], "checks": [
    {"name": "check", "argv": ["just", "check"], "timeout": 600}, {"name": "test", "argv": ["just", "test"], "timeout": 600}]}
REQUIRED = (("check", argv_digest(["just", "check"])), ("test", argv_digest(["just", "test"])))
RUN = ["exec just bootstrap", "exec just check", "exec just test"]
ME: EntryIdentity = (4242, "land-start", "boot")  # this land process's identity
BAR = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "url.delegate-push-refused://.pushInsteadOf", "GIT_CONFIG_VALUE_0": ""}
DONE = (
    """INSERT INTO execution (attempt_id,dispatch_token,generation,rc,timed_out,work,stands,stdout_path,stdout_digest,stderr_path,
    stderr_digest,answer_path,answer_digest,diagnostic_path,diagnostic_digest,answer_kind,effect,session_state) VALUES
    ('implement','implement-token',1,0,0,1,1,'o','d','e','d','a','d','g','d','valid','commit','complete')""",
    """INSERT INTO verification (attempt_id,dispatch_token,generation,verdict,observed_at)
    VALUES ('implement','implement-token',1,'verified',5)""",
)


class Racing(FakeRepo):
    """The person's clone: `after_ls` runs one step after each `ls_remote` in turn (None: nothing), as another actor
    racing on origin; `answer` replaces the next push's result; `pushes` counts the pushes made."""

    def __init__(self, repo: FakeRepo) -> None:
        super().__init__(repo._state, repo.path)
        self.after_ls: list[Callable[[], object] | None] = []
        self.answer: PushResult | None = None
        self.pushes = 0
        self.url_fault = False  # `remote_url` fails as an unreadable config would

    @override
    def ls_remote(self, remote: str, patterns: Sequence[str] = ()) -> RemoteRefs:
        found = super().ls_remote(remote, patterns)
        step = self.after_ls.pop(0) if self.after_ls else None
        if step is not None:
            step()
        return found

    @override
    def remote_url(self, remote: str, *, push: bool = False) -> str:
        if self.url_fault:
            raise GitReadFailure("remote get-url failed")
        return super().remote_url(remote, push=push)

    @override
    def worktree(self, path: Path) -> FakeWorktree:
        return Pushing(self, path)

    def prune(self, sha: str) -> None:
        """`git gc` pruned an unreferenced commit (a candidate left unpushed for weeks)."""
        self._state.store.commits.pop(sha)


class Pushing(FakeWorktree):
    """A checkout of `Racing`: its push is counted, and answered by the scripted result when one is set."""

    def __init__(self, repo: Racing, path: Path) -> None:
        super().__init__(repo, path)
        self.racing = repo

    @override
    def push(self, dst: str, *, remote: str = "origin", hook_env: Mapping[str, str] | None = None, head: Sha | None = None) -> PushResult:
        self.racing.pushes += 1
        answer, self.racing.answer = self.racing.answer, None
        return answer if answer is not None else super().push(dst, remote=remote, hook_env=hook_env, head=head)


class NoBeats:
    """The keep-alive's stop: the renewing thread never beats (the bench's one renewal is the land's own)."""

    def wait(self, timeout: float) -> bool:
        del timeout
        return True

    def set(self) -> None:
        return None


@dataclass
class LandBench:
    """One land's collaborators. `status`/`assignee` are the task in the tracker; `beats` the claim's answers; `environ`
    this process's environment; `seen` the process-table answer per stored land process; `racing` runs once right before
    the next write transaction of the candidates' store (another actor's commit). The tracker's close is semantic: found
    closed is `already_closed`, another assignee `claim_lost`, else the task becomes `closed` with the reason; `closing`
    answers the next closes instead (`missing`, `unavailable`, ...); `on_close` runs first (a crash); `tracker` logs each
    close with origin's `main` at that moment."""

    root: Path
    remote: FakeRemote
    repo: Racing
    slot: FakeWorktree
    con: sqlite3.Connection
    base: str
    x: str
    status: str = "in_progress"
    assignee: str = "taskloop"
    beats: list[Beat] = field(default_factory=lambda: ["held"])
    environ: dict[str, str] = field(default_factory=dict)
    seen: dict[EntryIdentity, Seen] = field(default_factory=dict)
    now: float = 10.0
    me: EntryIdentity = ME
    racing: Callable[[], object] = lambda: None
    title: str = "Widget"
    reason: str | None = None
    closing: list[Closed] = field(default_factory=list)
    tracker: list[tuple[str, str]] = field(default_factory=list)
    on_close: Callable[[], object] = lambda: None

    def __post_init__(self) -> None:
        self.views, self.files = PinnedViews(self.repo), FakeSlotFiles(self.repo)
        self.environment = Environment(self.con, self.views, self.root / "art", tmp_bytes=4096)
        self.environment.clock = lambda: self.now
        self.environment.profiles = FakeProfiles(blob=json.dumps(PROFILE).encode())
        self.d = self.slot_head()
        self.lands = LandStore(lambda: self.con, self.begin)

    def slot_head(self) -> str:
        found = next(info.head for info in self.repo.worktrees() if info.path == self.slot.path)
        assert found is not None
        return found

    def begin(self, con: sqlite3.Connection) -> AbstractContextManager[None]:
        racing, self.racing = self.racing, lambda: None
        racing()
        return begin_immediate(con)

    def show(self, task_id: str) -> Bead:
        return Bead(task_id, title=self.title, description="It must do X", status=self.status, assignee=self.assignee)

    def close(self, _root: str, task_id: str, reason: str) -> Closed:
        self.on_close()
        self.tracker.append((task_id, self.remote.branches().get("main", "")))
        if self.closing:
            return self.closing.pop(0)
        if self.status == "closed":
            return "already_closed"
        if self.assignee != "taskloop":
            return "claim_lost"
        self.status, self.reason = "closed", reason
        return "closed"

    def inspect(self, task_id: str, backlog: str, root: str) -> TaskInspection:
        return inspect_task(TaskBinding(TaskScope(backlog), Path(root)), self, task_id)

    def heartbeat_for(self, _root: str, _task: str) -> Heartbeat:
        def beat() -> Beat:
            return self.beats.pop(0) if len(self.beats) > 1 else self.beats[0]

        return beat

    def checking(self) -> Checking:
        env = self.environment
        block = Block(BlockPorts(env.process, env.process.lingering, lambda: self.now))
        return Checking(CheckStore(lambda: self.con), SetupStore(lambda: self.con), EvidenceFiles(env.artifacts), self.views, self.files,
                        env.profiles, env.preparation(), block, env.observe, lambda entry: self.seen.get(entry, "gone"),
                        lambda _path: True, lambda: self.now, lambda: {"HOME": "/home/p"})

    def ports(self) -> LandPorts:
        return LandPorts(self.checking(), self.lands, self.views, lambda path: GitProfileFiles(path, self.views), self.inspect,
                         self.heartbeat_for, NoBeats, lambda: self.me, lambda _path: True, landing, self.environ, self.close)

    def land(self, mode: str = "land", *, no_change: bool = False, minutes: int = 5, checkout: Path | None = None) -> LandResult:
        modes: dict[str, Literal["land", "summary", "withdraw"]] = {"withdraw": "withdraw", "summary": "summary"}
        request = LandRequest("tasks", "tl-1", checkout or self.repo.path, minutes, modes.get(mode, "land"), no_change)
        return land(self.ports(), request)

    def rows(self) -> tuple[LandRow, ...]:
        return self.lands.of_checks(CHECKS.attempt_id)

    def reservations(self) -> list[tuple[object, ...]]:
        return self.con.execute("SELECT slot,attempt_id FROM reservation").fetchall()

    def origin_main(self) -> str:
        return self.remote.branches()["main"]

    def advance(self, files: dict[str, str | None], message: str = "another land") -> str:
        """Someone else lands on origin's `main`."""
        return self.remote.advance("main", files, message)

    def execs(self) -> list[str]:
        return [event for event in self.environment.events if event.startswith("exec")]

    def files_of(self, rev: str) -> dict[str, str]:
        tree = self.repo.tree(rev)
        assert tree is not None
        return {path: (tree.read(path) or b"").decode() for path in tree.files}


def database(path: Path, repo_id: str, slot: Path, base: str, x: str, d: str) -> sqlite3.Connection:
    """`path`: tl-1's done implement attempt (B its base, X its commit, released `kept` from slot s0, published), its checks
    attempt 1 concluded `passed` and released (parked at D), and the adopted free slot s1 at `slot` (generation 1)."""
    con = Store(SCHEMA).open_rw(path)
    assert con is not None
    with begin_immediate(con):
        con.execute("INSERT INTO slot (repo_id,name,path,generation) VALUES (?,'s0','/elsewhere/s0',0),(?,'s1',?,1)",
                    (repo_id, repo_id, str(slot)))
        con.execute(
            """INSERT INTO attempt (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,
            input_path,input_digest,schema_version,model,effort,sandbox,deadline,phase,base_commit,end_commit,number,seq,slot_head,
            after_commit) VALUES ('implement','implement-token',1,'implement','beads','tasks','tl-1','/tracker',?,'s0','input.txt',
            'digest',1,'m','e','workspace-write',100,'captured',?,?,1,2,?,?)""", (repo_id, base, x, d, base))
        for statement in DONE:
            con.execute(statement)
        con.execute("INSERT INTO slot_release VALUES ('implement','implement-token',1,?,4,'kept')", (d,))
        con.execute("INSERT INTO published_branch VALUES ('implement','implement-token',1,?,?,6)", (x, x))
        check_store.insert(con, check_store.ChecksAdmitted(CHECKS, "implement", 1, "s1", d, base, REQUIRED, 100.0))
        con.execute("""UPDATE checks_attempt SET phase='concluded',conclusion='passed',concluded_at=5,released_at=6,parked=?""", (d,))
    return con


def bench(tmp_path: Path) -> LandBench:
    """The bench's world: origin's `main` at B, the person's clone, slot s1 at B, `task/tl-1` at X on both sides."""
    where = tmp_path.resolve()
    remote = FakeRemote("https://example.invalid/repo.git")
    base = remote.advance("main", {"README": "one\n", ".task-loop.json": json.dumps(PROFILE)}, "base")
    repo = Racing(FakeRepo.clone(remote, where / "main"))
    slot = repo.add_worktree(where / "slots" / repo.identity().key / "s1", "HEAD")
    root = repo.worktree(repo.identity().root)
    root.checkout_new("task/tl-1")
    root.write_file("src/x.py", "X = 1\n")
    made = root.record("the task's commit", paths="all")
    assert isinstance(made, Recorded)
    assert isinstance(root.push("task/tl-1", remote="origin", head=made.sha), Pushed)
    root.checkout("main")
    repo.pushes = 0
    con = database(where / "factory.db", repo.identity().key, slot.path, base, made.sha, base)
    return LandBench(where, remote, repo, slot, con, base, made.sha)
