"""Real layer, a Git read that blocks: a FIFO with no writer at `$GIT_DIR/info/exclude` makes Git's `status` wait forever.
Through `slot adopt` the bounded read is the typed `git_unavailable` (no hang, no silent skip), and the same slot adopts
once the FIFO is gone."""

import faulthandler
import os
import time
from pathlib import Path

import pytest
from git_porcelain.history import Identity
from git_porcelain.testing import apply_hermetic_env, git

from taskloop import cli_composition
from taskloop.composition import real_slots
from taskloop.git_views import GitViews
from taskloop.operations import Adoption
from taskloop.slots import Adopted, NotAdopted

VIEWS = GitViews()


def test_a_blocked_status_is_git_unavailable_and_the_slot_adopts_once_it_clears(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path.resolve()
    apply_hermetic_env(monkeypatch, identity=Identity("Person", "person@example.invalid"), config={})
    main = root / "repo"
    main.mkdir()
    git(main, "init", "-q", "-b", "main")
    (main / "a.txt").write_text("a")
    git(main, "add", "a.txt")
    git(main, "commit", "-q", "-m", "base")
    slots = root / "slots"
    slot = slots / VIEWS.checkouts(main).identity().key / "s1"
    git(main, "worktree", "add", "-q", "--detach", str(slot), "HEAD")
    exclude = main / ".git" / "info" / "exclude"
    exclude.parent.mkdir(exist_ok=True)
    exclude.unlink(missing_ok=True)
    os.mkfifo(exclude)
    views = GitViews(2)

    started = time.monotonic()
    faulthandler.dump_traceback_later(60, exit=True)  # wall-clock guard: a hang ends the run with a traceback, not never
    try:
        blocked = cli_composition.adopt(root / "state" / "factory.db", main, slots, 1, real_slots(views))
    finally:
        faulthandler.cancel_dump_traceback_later()
    assert time.monotonic() - started < 30  # the bound is 2 s
    assert isinstance(blocked, Adoption)
    assert blocked.slots == (NotAdopted("s1", "git_unavailable", slot),)

    exclude.unlink()
    cleared = cli_composition.adopt(root / "state" / "factory.db", main, slots, 1, real_slots(views))
    assert isinstance(cleared, Adoption)
    assert isinstance(cleared.slots[0], Adopted)
