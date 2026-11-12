"""Shared plan fixtures: an empty current-schema factory.db in memory, one admitted attempt in a factory.db file, a semantic
Git fake clone, a slot root, a clean detached slot, the Git view the body opens, the slot file port over the fake, an
entry-registered attempt on it, and another holder of a slot's lock."""

import fcntl
import hashlib
import json
import os
import sqlite3
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

import pytest
from doubles import CANDIDATE, CHECKS, MAIN_PROFILE, ORIGIN, REQUIRED, SQUASH, TARGET, D, Done, FakeSlotFiles, PinnedViews, X
from git_porcelain import Recorded
from git_porcelain.testing import FakeRemote, FakeRepo, FakeWorktree
from sqlite_store import Store, begin_immediate

from taskloop import check_store, land_store
from taskloop.attempt_types import AttemptKey
from taskloop.factory_schema import SCHEMA


@pytest.fixture
def factory() -> Generator[sqlite3.Connection]:
    con = sqlite3.connect(":memory:", isolation_level=None)
    con.execute("PRAGMA foreign_keys=ON")
    with begin_immediate(con):
        for statement in SCHEMA.ddl.split(";"):
            if statement.strip():
                con.execute(statement)
        con.execute(f"PRAGMA user_version={SCHEMA.version}")
    yield con
    con.close()


@pytest.fixture
def repo(tmp_path: Path) -> FakeRepo:
    remote = FakeRemote("https://example.invalid/repo.git")
    remote.advance("main", {"README": "one"})
    return FakeRepo.clone(remote, tmp_path / "main")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "slots"


@pytest.fixture
def slot(repo: FakeRepo, root: Path) -> FakeWorktree:
    """What a person does before adoption: `git worktree add --detach <root>/<repo_id>/s1`, born, detached and clean."""
    return repo.add_worktree(root.resolve() / repo.identity().key / "s1", "HEAD")


@pytest.fixture
def checkouts(repo: FakeRepo) -> PinnedViews:
    """The body's Git view of every checkout path: the fake clone, which finds a worktree by its path, as the real Git
    does from any checkout of the repository; a slot opens only pinned to its pointer's G (`PinnedViews`)."""
    return PinnedViews(repo)


@pytest.fixture
def slot_files(repo: FakeRepo) -> FakeSlotFiles:
    return FakeSlotFiles(repo)


def head(slot: FakeWorktree) -> str:
    """The slot's HEAD as Git lists it: for a freshly added slot, its admission base D."""
    found = next(worktree.head for worktree in slot.repo.worktrees() if worktree.path == slot.path)
    assert found is not None
    return found


@pytest.fixture
def admitted(tmp_path: Path, slot: FakeWorktree) -> Path:
    """`<tmp>/factory.db` holding one admitted, unregistered attempt (deadline 100) on the adopted `slot` and its held reservation;
    the artifacts root is `tmp_path`, with the admitted input written."""
    path = tmp_path / "factory.db"
    con = Store(SCHEMA).open_rw(path)
    assert con is not None
    text = "Plan the actual task"
    repo_id = slot.repo.identity().key
    with begin_immediate(con):
        con.execute("INSERT INTO slot (repo_id,name,path) VALUES (?,'s1',?)", (repo_id, str(slot.path)))  # adopted
        con.execute("INSERT INTO reservation VALUES ('s1',?,1,'attempt')", (repo_id,))
        con.execute(
            """INSERT INTO attempt
            (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,input_path,input_digest,
             schema_version,model,effort,sandbox,deadline,number,seq,slot_head)
            VALUES ('attempt','dispatch',1,'plan','beads','tasks','tl-1','/tracker',?,'s1','input.txt',?,1,'chosen','high',
            'workspace-write',100,1,1,?)""",
            (repo_id, hashlib.sha256(text.encode()).hexdigest(), head(slot)),
        )
    con.close()
    (tmp_path / "input.txt").write_text(text)
    return path


@pytest.fixture
def registered(factory: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path) -> sqlite3.Connection:
    """In memory: one admitted, entry-registered attempt (entry (7, entry-start, boot), deadline 100) on the adopted `slot`, its held
    reservation, and its input in the artifacts root `tmp_path`."""
    repo_id = slot.repo.identity().key
    with begin_immediate(factory):
        factory.execute("INSERT INTO slot (repo_id,name,path) VALUES (?,'s1',?)", (repo_id, str(slot.path)))  # adopted
        factory.execute("INSERT INTO reservation VALUES ('s1',?,1,'attempt')", (repo_id,))
        factory.execute(
            """INSERT INTO attempt
            (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,input_path,input_digest,
             schema_version,model,effort,sandbox,deadline,entry_pid,entry_start,entry_boot,number,seq,slot_head)
            VALUES ('attempt','dispatch',1,'plan','beads','tasks','tl-1','/tracker',?,'s1','input.txt',?,1,'chosen','high',
            'workspace-write',100,7,'entry-start','boot',1,1,?)""",
            (repo_id, hashlib.sha256(b"Plan the actual task").hexdigest(), head(slot)),
        )
    (tmp_path / "input.txt").write_text("Plan the actual task")
    return factory


@pytest.fixture
def checking(factory: sqlite3.Connection) -> sqlite3.Connection:
    """In memory: tl-1's done implement attempt `implement` (seq 2, captured at X, released `kept`, its slot s1 free) and its
    checks attempt 1 `CHECKS` (deadline 100, required `REQUIRED`, target `TARGET`) admitted on slot s2 at D, with its held reservation."""
    with begin_immediate(factory):
        factory.execute("INSERT INTO slot (repo_id,name,path) VALUES ('r','s1','/slots/s1'),('r','s2','/slots/s2')")
        factory.execute(
            """INSERT INTO attempt (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,
            input_path,input_digest,schema_version,model,effort,sandbox,deadline,phase,base_commit,end_commit,number,seq,slot_head,
            after_commit) VALUES ('implement','implement-token',1,'implement','beads','tasks','tl-1','/tracker','r','s1','input.txt',
            'digest',1,'m','e','workspace-write',100,'captured',?,?,1,2,?,?)""", ("b" * 40, X, D, "a" * 40))
        factory.execute("INSERT INTO slot_release VALUES ('implement','implement-token',1,?,1,'kept')", (D,))
        factory.execute("INSERT INTO reservation VALUES ('s2','r',1,'checks')")
        check_store.insert(factory, check_store.ChecksAdmitted(CHECKS, "implement", 1, "s2", D, TARGET, REQUIRED, 100.0))
    return factory


@pytest.fixture
def landing(checking: sqlite3.Connection) -> sqlite3.Connection:
    """`checking` with `CHECKS` concluded `passed` and released (parked at D, slot s2 free), and its land candidate 1
    `CANDIDATE` (O `ORIGIN`, S `SQUASH`, S's tree not X's) pending on slot s1 at D, deadline 300, with its held reservation."""
    with begin_immediate(checking):
        checking.execute("""UPDATE checks_attempt SET phase='concluded',conclusion='passed',concluded_at=5,released_at=6,parked=?
        WHERE attempt_id='checks'""", (D,))
        checking.execute("DELETE FROM reservation WHERE attempt_id='checks'")
        checking.execute("INSERT INTO reservation VALUES ('s1','r',1,'candidate')")
        land_store.insert(checking, land_store.LandAdmitted(CANDIDATE, "checks", 1, ORIGIN, SQUASH, False, REQUIRED, "s1", D, 300.0,
                                                            None, 10.0))
    return checking


@pytest.fixture
def on_slot(tmp_path: Path, repo: FakeRepo, slot: FakeWorktree) -> Path:
    """`<tmp>/factory.db`: tl-1's done implement attempt `implement` (X: a commit made on the person's `main`, which is
    therefore the target) released `kept` from slot s0, and its checks attempt 1 `CHECKS` admitted on the Git fake's
    slot s1 (still detached at D), deadline 100, required `REQUIRED`, with its held reservation; no entry registered."""
    root = repo.worktree(repo.identity().root)
    root.write_file("README", "X")
    made = root.record("the task's commit", paths="all")
    assert isinstance(made, Recorded)
    path, repo_id, d = tmp_path / "factory.db", repo.identity().key, head(slot)
    con = Store(SCHEMA).open_rw(path)
    assert con is not None
    with begin_immediate(con):
        con.execute("INSERT INTO slot (repo_id,name,path) VALUES (?,'s0','/elsewhere/s0'),(?,'s1',?)", (repo_id, repo_id, str(slot.path)))
        con.execute(
            """INSERT INTO attempt (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,
            input_path,input_digest,schema_version,model,effort,sandbox,deadline,phase,base_commit,end_commit,number,seq,slot_head,
            after_commit) VALUES ('implement','implement-token',1,'implement','beads','tasks','tl-1','/tracker',?,'s0','input.txt',
            'digest',1,'m','e','workspace-write',100,'captured',?,?,1,2,?,?)""", (repo_id, "b" * 40, made.sha, d, "a" * 40))
        con.execute("INSERT INTO slot_release VALUES ('implement','implement-token',1,?,1,'kept')", (d,))
        con.execute("INSERT INTO reservation VALUES ('s1',?,1,'checks')", (repo_id,))
        check_store.insert(con, check_store.ChecksAdmitted(CHECKS, "implement", 1, "s1", d, made.sha, REQUIRED, 100.0))
    con.close()
    return path


@pytest.fixture
def candidate_on_slot(on_slot: Path, repo: FakeRepo, slot: FakeWorktree) -> tuple[Path, str]:
    """`on_slot` with `CHECKS` concluded `passed` and released (parked at D), and its land candidate 1 `CANDIDATE` (O
    `ORIGIN`, S a commit on the person's `main` after X, S's tree not X's) pending on the Git fake's slot s1 (still at D),
    deadline 300, with its held reservation; no land process held yet. Returns the path and S."""
    root = repo.worktree(repo.identity().root)
    root.write_file("README", "S")
    made = root.record("the land candidate", paths="all")
    assert isinstance(made, Recorded)
    d, con = head(slot), Store(SCHEMA).open_rw(on_slot)
    assert con is not None
    with begin_immediate(con):
        con.execute("""UPDATE checks_attempt SET phase='concluded',conclusion='passed',concluded_at=5,released_at=6,parked=?
        WHERE attempt_id='checks'""", (d,))
        con.execute("UPDATE reservation SET attempt_id='candidate' WHERE attempt_id='checks'")
        land_store.insert(con, land_store.LandAdmitted(CANDIDATE, "checks", 1, ORIGIN, made.sha, False, REQUIRED, "s1", d, 300.0,
                                                       None, 10.0))
    con.close()
    return on_slot, made.sha


DONE = (  # the implement attempt's capture, verdict, settled release and publication
    """INSERT INTO execution (attempt_id,dispatch_token,generation,rc,timed_out,work,stands,stdout_path,stdout_digest,stderr_path,
    stderr_digest,answer_path,answer_digest,diagnostic_path,diagnostic_digest,answer_kind,effect,session_state) VALUES
    ('implement','implement-token',1,0,0,1,1,'o','d','e','d','a','d','g','d','valid','commit','complete')""",
    """INSERT INTO verification (attempt_id,dispatch_token,generation,verdict,observed_at)
    VALUES ('implement','implement-token',1,'verified',5)""",
)


@pytest.fixture
def done(tmp_path: Path, repo: FakeRepo, slot: FakeWorktree) -> Done:
    """`<tmp>/factory.db`: tl-1's done implement attempt `implement` (verified, released `kept` from slot s0, published at X)
    and the adopted, free slot s1 (the Git fake's, detached at D). The person's `main` holds `MAIN_PROFILE` (the target);
    `task/tl-1` holds X on it. No checks attempt yet."""
    root, d = repo.worktree(repo.identity().root), head(slot)
    root.write_file(".task-loop.json", json.dumps(MAIN_PROFILE))
    target = root.record("profile", paths="all")
    root.checkout_new("task/tl-1")
    root.write_file("src/x.py", "X = 1\n")
    x = root.record("the task's commit", paths="all")
    assert isinstance(target, Recorded) and isinstance(x, Recorded)
    root.checkout("main")
    path, repo_id = tmp_path / "factory.db", repo.identity().key
    con = Store(SCHEMA).open_rw(path)
    assert con is not None
    with begin_immediate(con):
        con.execute("INSERT INTO slot (repo_id,name,path) VALUES (?,'s0','/elsewhere/s0'),(?,'s1',?)", (repo_id, repo_id, str(slot.path)))
        con.execute(
            """INSERT INTO attempt (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,
            input_path,input_digest,schema_version,model,effort,sandbox,deadline,phase,base_commit,end_commit,number,seq,slot_head,
            after_commit) VALUES ('implement','implement-token',1,'implement','beads','tasks','tl-1','/tracker',?,'s0','input.txt',
            'digest',1,'m','e','workspace-write',100,'captured',?,?,1,2,?,?)""", (repo_id, target.sha, x.sha, d, target.sha))
        for statement in DONE:
            con.execute(statement)
        con.execute("INSERT INTO slot_release VALUES ('implement','implement-token',1,?,4,'kept')", (d,))
        con.execute("INSERT INTO published_branch VALUES ('implement','implement-token',1,?,?,6)", (x.sha, x.sha))
    con.close()
    return Done(path, AttemptKey("implement", "implement-token", 1), x.sha, target.sha, d)


@contextmanager
def _occupied(path: Path) -> Generator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


@pytest.fixture
def occupy() -> Callable[[Path], AbstractContextManager[None]]:
    """Another holder of a slot's lock file: its own open file description holding the exclusive `flock`, as another
    process would hold it."""
    return _occupied
