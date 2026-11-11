"""Real layer, the setup sequence on real Git and a real process: the profile read from the commit (never the working
tree) through the slot's pinned view, the reset's `git clean -ffdx` removing ignored files and a nested repository while
tracked files stay, the setup command run through the registered start in the slot with the slot's folders, its log,
and the run recorded `passed`. Set-up runs through `git_porcelain.testing`'s runner under tmp_path."""

import json
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

import pytest
from git_porcelain.history import Identity
from git_porcelain.testing import apply_hermetic_env, git
from stream_proc import group_alive

from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey
from taskloop.composition import RealEnvFiles, checkouts, setup_process, setup_seen, slot_profiles
from taskloop.environment import EnvironmentPorts, Preparation, Renewal, folders
from taskloop.evidence_files import EvidenceFiles
from taskloop.prepare import Prepared
from taskloop.setup_store import SetupStore

KEY = AttemptKey("attempt", "dispatch", 1)
# fails unless the reset emptied `.venv` first; prints the slot's folders
SETUP = 'test -z "$(ls -A .venv 2>/dev/null)" && mkdir -p .venv && echo built > .venv/marker && echo "$TMPDIR" && echo "$UV_CACHE_DIR"'


def held() -> Renewal:
    return "held"


def test_setup_resets_the_slot_and_runs_the_committed_setup_in_it(
    tmp_path: Path, factory: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path.resolve()
    apply_hermetic_env(monkeypatch, identity=Identity("Person", "person@example.invalid"), config={})
    main = root / "repo"
    main.mkdir()
    git(main, "init", "-q", "-b", "main")
    (main / ".gitignore").write_text(".venv/\n")
    (main / ".task-loop.json").write_text(json.dumps({"setup": [["/bin/sh", "-c", SETUP]]}))
    git(main, "add", ".gitignore", ".task-loop.json")
    git(main, "commit", "-q", "-m", "base")
    slot = root / "slots" / checkouts(main).identity().key / "s1"
    git(main, "worktree", "add", "-q", "--detach", str(slot), "HEAD")
    d = git(slot, "rev-parse", "HEAD").strip()
    (slot / ".task-loop.json").write_text(json.dumps({"setup": [["/bin/false"]]}))  # the working tree is never read
    git(slot, "update-index", "--assume-unchanged", ".task-loop.json")  # keeps the edited file out of status
    (slot / ".venv" / "nested").mkdir(parents=True)
    git(slot / ".venv" / "nested", "init", "-q")  # a nested repository in an ignored folder: `-fdx` would keep it
    (slot / ".venv" / "planted").write_text("from an earlier agent")
    factory.execute("INSERT INTO slot (repo_id,name,path) VALUES (?,'s1',?)", (slot.parent.name, str(slot)))
    factory.execute("INSERT INTO reservation VALUES ('s1',?,1,'attempt')", (slot.parent.name,))
    factory.execute(
        """INSERT INTO attempt (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,input_path,
        input_digest,schema_version,model,effort,sandbox,deadline,entry_pid,entry_start,entry_boot,number,seq,slot_head,after_commit)
        VALUES ('attempt','dispatch',1,'implement','beads','tasks','tl-1','/tracker',?,'s1','input.txt','x',1,'m','high',
        'workspace-write',?,7,'s','b',1,2,?,?)""", (slot.parent.name, time.time() + 600, d, d))
    record = AttemptStore(lambda: factory).load(KEY)
    assert record is not None
    ports = EnvironmentPorts(SetupStore(lambda: factory), checkouts, slot_profiles, RealEnvFiles(), setup_process, setup_seen,
                             group_alive, EvidenceFiles(root / "art"), time.time, sys.platform, shutil.rmtree.avoids_symlink_attacks)
    gitdir = Path(git(slot, "rev-parse", "--absolute-git-dir").strip())
    result = Preparation(ports).prepare(record, Prepared(d, gitdir, main), held, {"PATH": os.environ["PATH"]})
    assert result is None
    found = folders(slot)
    assert factory.execute("SELECT run,commit_sha,conclusion,rc FROM setup_run").fetchall() == [(1, d, "passed", 0)]
    assert sorted(path.name for path in (slot / ".venv").iterdir()) == ["marker"]  # the reset ran before the command
    assert (slot / ".gitignore").read_text() == ".venv/\n"
    log = EvidenceFiles(root / "art").setup_log(KEY, 1).read_text()
    assert log.startswith("$ /bin/sh -c ") and log.endswith(f"\n{found.tmp}\n{found.cache}\nexit 0\n")
    assert all(path.is_dir() for path in (found.tmp, found.cache, found.tools))
