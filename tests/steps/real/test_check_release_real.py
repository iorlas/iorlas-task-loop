"""Real layer, the checks release on real Git under the real slot lock: a person's `--detach` slot at D takes X detached
(`prepare.detach_at`), a block leaves an untracked report, an ignored folder and a rewritten tracked file; the settled
release resets the slot to exactly X (`reset --hard`, `clean -ffdx`), parks it at D with a real `checkout --detach` and
frees its reservation. Set-up runs through `git_porcelain.testing`'s runner under tmp_path."""

import sqlite3
from pathlib import Path

import pytest
from doubles import CHECKS, REQUIRED
from git_porcelain.history import Identity
from git_porcelain.testing import apply_hermetic_env, git
from sqlite_store import begin_immediate

from taskloop.attempt_types import DEFAULT_GIT_READ_SECONDS, Seen
from taskloop.check_release import ChecksRelease
from taskloop.check_store import ChecksAdmitted, CheckStore, insert
from taskloop.git_views import GitViews
from taskloop.prepare import Prepared, detach_at
from taskloop.setup_store import ProcessSeen
from taskloop.slot_files import RealSlotFiles
from taskloop.slot_lock import custody
from taskloop.slot_release import Released

VIEWS = GitViews(DEFAULT_GIT_READ_SECONDS)


def gone(_process: object) -> ProcessSeen:
    return "gone"


def never(_entry: object) -> Seen:
    return "gone"


def test_a_passed_block_s_leftovers_are_reset_away_and_the_slot_parked_at_d(
    tmp_path: Path, factory: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path.resolve()
    apply_hermetic_env(monkeypatch, identity=Identity("Person", "person@example.invalid"), config={})
    main = root / "repo"
    main.mkdir()
    git(main, "init", "-q", "-b", "main")
    (main / ".gitignore").write_text("build/\n")
    (main / "README").write_text("one\n")
    git(main, "add", ".gitignore", "README")
    git(main, "commit", "-q", "-m", "D")
    repo_id = VIEWS.checkouts(main).identity().key
    slot = root / "slots" / repo_id / "s1"
    git(main, "worktree", "add", "-q", "--detach", str(slot), "HEAD")
    d = git(main, "rev-parse", "HEAD").strip()
    (main / "README").write_text("two\n")
    git(main, "commit", "-q", "-am", "X")
    x = git(main, "rev-parse", "HEAD").strip()
    with begin_immediate(factory):
        factory.execute("INSERT INTO slot (repo_id,name,path) VALUES (?,'s0','/elsewhere/s0'),(?,'s1',?)", (repo_id, repo_id, str(slot)))
        factory.execute(
            """INSERT INTO attempt (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,
            input_path,input_digest,schema_version,model,effort,sandbox,deadline,phase,base_commit,end_commit,number,seq,slot_head,
            after_commit)
            VALUES ('implement','implement-token',1,'implement','beads','tasks','tl-1','/tracker',?,'s0','input.txt','digest',1,'m',
            'e','workspace-write',100,'captured',?,?,1,2,?,?)""", (repo_id, d, x, d, d))
        factory.execute("INSERT INTO slot_release VALUES ('implement','implement-token',1,?,1,'kept')", (d,))
        factory.execute("INSERT INTO reservation VALUES ('s1',?,1,'checks')", (repo_id,))
        insert(factory, ChecksAdmitted(CHECKS, "implement", 1, "s1", d, x, REQUIRED, 100.0))
    assert isinstance(detach_at(VIEWS.checkouts, RealSlotFiles(), str(slot), repo_id, x), Prepared)
    (slot / "coverage.xml").write_text("a report\n")
    (slot / "build").mkdir()
    (slot / "build" / "out").write_text("ignored\n")
    (slot / "README").write_text("rewritten\n")
    store = CheckStore(lambda: factory)
    store.conclude(CHECKS, "passed", None, 20)

    emptied: list[Path] = []

    def scratch(path: Path) -> bool:
        emptied.append(path)
        return True

    release = ChecksRelease(store, VIEWS.checkouts, RealSlotFiles(), never, custody, lambda: 30, gone, scratch)
    assert release.release(CHECKS, False) == Released("s1", d, True, "kept", False)
    assert git(slot, "rev-parse", "HEAD").strip() == d and git(slot, "status", "--porcelain", "--ignored").strip() == ""
    assert (slot / "README").read_text() == "one\n" and not (slot / "coverage.xml").exists() and not (slot / "build").exists()
    assert factory.execute("SELECT count(*) FROM reservation").fetchone() == (0,) and emptied == [slot]
