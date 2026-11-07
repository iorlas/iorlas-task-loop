"""The slot code (src/taskloop/app/slots) on fakes: bd in memory, git in memory with injected faults, the ticket line in a dict.
Every test here runs in milliseconds; the real git and the real files are in test_tl (SlotReset) and test_slots."""
import sys
from pathlib import Path
from types import SimpleNamespace

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from taskloop.adapters.git import classify
from taskloop.cli import slots as cli
from tlkernel.slots import BranchPinned, DirtyTree, IndexLocked, RefRace, SlotGitError
from tlslots.testing import LIVE_PID, Rig


class Classify(Case):
    def test_git_words_become_typed_errors(self):
        assert isinstance(classify("fatal: Unable to create '/r/.git/worktrees/s1/index.lock': File exists."), IndexLocked)
        assert isinstance(classify("error: cannot lock ref 'refs/remotes/origin/main': is at 1 but expected 2"), RefRace)
        pinned = classify("fatal: 'task/x' is already used by worktree at '/w/old'")
        assert isinstance(pinned, BranchPinned)
        assert pinned.where == "/w/old"
        assert isinstance(classify("error: Your local changes to the following files would be overwritten by checkout"), DirtyTree)
        assert type(classify("fatal: not a git repository")) is SlotGitError


class Taking(Rig):
    def test_an_expired_hold_frees_the_slot(self):
        verbs = SimpleNamespace(op="hold", name="s1", why="screens", for_min=1, n=None, bead=None, force=False)
        assert cli.run(self.env, verbs) == 0
        assert self.code(lambda: self.slot().take("a")) == "busy"
        self.t[0] += 61
        assert (self.pool.take_any("loop") or ("",))[0] == "s1"


class Verbs(Rig):
    def test_the_verb_table_has_every_verb_and_an_unknown_one_is_a_misuse(self):
        assert sorted(cli.VERBS) == ["hold", "init", "list", "release", "reset", "setup", "take"]
        assert cli.run(self.env, SimpleNamespace(op="nope")) == 2

    def test_reset_answers_with_the_code_of_the_failure(self):
        a = SimpleNamespace(op="reset", name="s1", bead="x-1", force=False, error="")
        self.git.fail("checkout_new", BranchPinned("fatal: taken", "/w"))
        assert cli.run(self.env, a) == 5
        assert a.error == "fatal: taken"
        self.busy_at[self.d1] = "engine pid 7 runs x-0"
        assert cli.run(self.env, a) == 4
        assert self.out[-1].startswith("BUSY: slot s1: engine pid 7")
        del self.busy_at[self.d1]
        self.git.fail("checkout_new", SlotGitError("fatal: boom"))
        assert cli.run(self.env, a) == 3

    def test_list_names_the_slots_and_the_line(self):
        self.tickets.take("r-1", "run-task late", 2, pid=LIVE_PID, now=5.0)
        self.tickets.take("r-1", "run-task urgent", 0, pid=LIVE_PID, now=6.0)
        assert cli.run(self.env, SimpleNamespace(op="list")) == 0
        rows = [r.split("\t") for r in self.out]
        assert [r[0] for r in rows[:2]] == ["s1", "s2"]
        assert [(r[1], r[2], r[4]) for r in rows[2:]] == [("1", "P0", "run-task urgent"), ("2", "P2", "run-task late")]
