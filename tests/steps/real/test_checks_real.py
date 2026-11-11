"""Real layer, the checks block on real Git and real processes: a person's `--detach` slot at D takes X detached
(`prepare.detach_at`, a real park through the pinned view), then `sh -c` checks run through the shelf's registered start
in the slot: one passes, one leaves an untracked file (listed, still passed), one is stopped by its own timeout (the
block goes on), one rewrites a tracked file (`dirty`, the block stops); then a check whose background child outlives it
is `lingering`. Nothing is signalled by the test; the background `sleep` ends by itself. Set-up runs through
`git_porcelain.testing`'s runner under tmp_path."""

import os
import sqlite3
import time
from pathlib import Path

import pytest
from doubles import CHECKS
from git_porcelain.history import Identity
from git_porcelain.testing import apply_hermetic_env, git
from stream_proc import group_alive

from taskloop.agent_credentials import scrubbed
from taskloop.check_store import CheckStore
from taskloop.checks import Block, BlockPorts, BlockTarget, CheckSink, check_env
from taskloop.evidence_files import EvidenceFiles
from taskloop.git_views import checkouts
from taskloop.prepare import Prepared, detach_at
from taskloop.profile import Check
from taskloop.slot_env import setup_process
from taskloop.slot_files import RealSlotFiles

PASS = Check("pass", ("/bin/sh", "-c", "echo ok"), 30)
UNTRACKED = Check("untracked", ("/bin/sh", "-c", "touch untracked-file"), 30)
SLOW = Check("slow", ("/bin/sh", "-c", "sleep 30"), 1)
REWRITE = Check("rewrite", ("/bin/sh", "-c", "echo x >> README"), 30)
NEVER = Check("never", ("/bin/sh", "-c", "exit 0"), 30)
CHILD = Check("child", ("/bin/sh", "-c", "sleep 2 >/dev/null 2>&1 & exit 0"), 30)
REQUIRED = (("pass", "1" * 64),)


def test_checks_run_on_the_host_in_a_slot_detached_at_x(
    tmp_path: Path, checking: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path.resolve()
    apply_hermetic_env(monkeypatch, identity=Identity("Person", "person@example.invalid"), config={})
    main = root / "repo"
    main.mkdir()
    git(main, "init", "-q", "-b", "main")
    (main / "README").write_text("one\n")
    git(main, "add", "README")
    git(main, "commit", "-q", "-m", "D")
    slot = root / "slots" / checkouts(main).identity().key / "s1"
    git(main, "worktree", "add", "-q", "--detach", str(slot), "HEAD")
    (main / "README").write_text("two\n")
    git(main, "commit", "-q", "-am", "X")
    x = git(main, "rev-parse", "HEAD").strip()

    taken = detach_at(checkouts, RealSlotFiles(), str(slot), slot.parent.name, x)
    assert isinstance(taken, Prepared) and taken.head == x
    assert git(slot, "rev-parse", "HEAD").strip() == x and (slot / "README").read_text() == "two\n"
    view = checkouts(slot, git_dir=taken.gitdir)
    environ = {"PATH": os.environ["PATH"], "HOME": str(root)}
    target = BlockTarget(slot, view, x, REQUIRED, time.time() + 600, check_env(scrubbed(environ), slot))
    store, evidence = CheckStore(lambda: checking), EvidenceFiles(root / "art")
    sink = CheckSink(store, CHECKS, evidence, time.time)
    block = Block(BlockPorts(setup_process, group_alive, time.time))

    assert block.run(target, sink, store.block(CHECKS), (PASS, UNTRACKED, SLOW, REWRITE, NEVER)) is None
    rows = "SELECT block,name,conclusion,rc,pid IS NOT NULL FROM check_result ORDER BY block,position"
    assert checking.execute(rows).fetchall() == [
        (1, "pass", "passed", 0, 1), (1, "untracked", "passed", 0, 1), (1, "slow", "timed_out", None, 1),
        (1, "rewrite", "dirty", 0, 1)]
    assert evidence.check_log(CHECKS, 1, "pass").read_text() == "$ /bin/sh -c 'echo ok'\nok\nexit 0\n"
    assert evidence.check_log(CHECKS, 1, "untracked").read_text().endswith("exit 0\nuntracked: untracked-file\n")
    assert evidence.check_log(CHECKS, 1, "slow").read_text().endswith("timed out\nuntracked: untracked-file\n")
    assert evidence.check_log(CHECKS, 1, "rewrite").read_text().endswith("exit 0\nuntracked: untracked-file\ndirty\n")

    git(slot, "checkout", "--", "README")
    assert block.run(target, sink, store.block(CHECKS), (CHILD, PASS)) is None
    assert checking.execute(rows).fetchall()[-1] == (2, "child", "lingering", 0, 1)
    assert evidence.check_log(CHECKS, 2, "child").read_text().endswith("exit 0\nlingering\n")
