"""`tl worktrees`: every worktree tl makes is made by owned.create with an ownership record; the survey tells owned from foreign from
orphaned; clean removes only an owned worktree that is merged and clean and says what a refusal would lose. Real git."""
import os
import subprocess
import sys
from pathlib import Path

from support.case import Case
from support.tmpdir import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401
from support.spawn import port_git

from taskloop.app.slots import owned
from tlkernel.paths import ConfigDir

ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
KEY = "r-1"


def git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, env=ENV, check=False)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


class Rig(Case):
    def setup_method(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        self.git, self.cfg, self.out = port_git(), ConfigDir(root / "cfg"), []
        git(root, "init", "-q", "--bare", "-b", "main", "origin.git")
        git(root, "clone", "-q", "origin.git", "repo")
        self.repo = str(root / "repo")
        (root / "repo" / "a.txt").write_text("a")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "first")
        git(self.repo, "push", "-q", "origin", "HEAD:main")
        git(self.repo, "fetch", "-q")
        self.slots_dir = str(root / "repo" / ".slots")

    def make(self, path, kind="loop", name=None):
        owned.create(self.git, self.cfg, KEY, self.repo, path, "origin/main", kind=kind, run="tl-x", bead="b-1", host="h", now=5.0,
                     exclude=lambda: None)
        return path

    def clean(self, count=0, busy=lambda d: ""):
        code = owned.clean(self.git, self.cfg, KEY, self.repo, self.slots_dir, "origin/main", count, busy, self.out.append)
        return code, "\n".join(self.out)

    def states(self):
        return {Path(r.path).name: r.state for r in owned.survey(self.git, self.cfg, KEY, self.repo, self.slots_dir)}


class Create(Rig):
    def test_create_makes_the_worktree_and_records_its_owner(self):
        wt = self.make(owned.loop_path(self.repo, "abc"))
        assert Path(wt, "a.txt").exists()
        rec = owned.docs(self.cfg, KEY).of(owned.key_of(wt)).get()
        assert rec is not None
        assert (rec.kind, rec.run, rec.bead, rec.host, rec.created) == ("loop", "tl-x", "b-1", "h", 5.0)
        self.make(wt)  # again: reused, the record kept
        assert len(owned.docs(self.cfg, KEY).keys()) == 1


class Survey(Rig):
    def test_owned_foreign_and_orphaned_are_told_apart(self):
        self.make(owned.loop_path(self.repo, "mine"))
        git(self.repo, "worktree", "add", "-q", "--detach", str(Path(self.repo, ".claude", "worktrees", "cc")), "origin/main")
        git(self.repo, "worktree", "add", "-q", "--detach", owned.loop_path(self.repo, "old"), "origin/main")  # tl-named, no record
        gone = self.make(owned.loop_path(self.repo, "gone"))
        subprocess.run(["rm", "-rf", gone], check=True)
        assert self.states() == {"cc": "foreign", "loop-gone": "orphaned", "loop-mine": "owned", "loop-old": "orphaned"}

    def test_a_stray_slot_folder_is_not_a_worktree(self):
        Path(self.slots_dir, "s9").mkdir(parents=True)
        assert self.states() == {}


class Clean(Rig):
    def test_a_merged_clean_owned_worktree_is_removed_with_its_record(self):
        wt = self.make(owned.loop_path(self.repo, "a"))
        code, out = self.clean()
        assert code == 0, out
        assert not Path(wt).exists()
        assert owned.docs(self.cfg, KEY).keys() == []

    def test_unmerged_commits_are_refused_and_named(self):
        wt = self.make(owned.loop_path(self.repo, "a"))
        Path(wt, "b.txt").write_text("b")
        git(wt, "add", "-A")
        git(wt, "commit", "-qm", "wip (x-1)")
        code, out = self.clean()
        assert code == 1
        assert "1 commit(s) not on origin/main" in out
        assert "wip (x-1)" in out
        assert Path(wt).exists()

    def test_dirty_and_untracked_files_are_refused_and_named(self):
        wt = self.make(owned.loop_path(self.repo, "a"))
        Path(wt, "a.txt").write_text("changed")
        Path(wt, "new.txt").write_text("n")
        code, out = self.clean()
        assert code == 1
        assert "changed a.txt" in out
        assert "untracked new.txt" in out
        assert Path(wt).exists()

    def test_a_patch_already_on_main_counts_as_merged(self):
        wt = self.make(owned.loop_path(self.repo, "a"))
        Path(wt, "b.txt").write_text("b")
        git(wt, "add", "-A")
        git(wt, "commit", "-qm", "b")
        git(self.repo, "cherry-pick", git(wt, "rev-parse", "HEAD"))
        git(self.repo, "push", "-q", "origin", "HEAD:main")
        git(self.repo, "fetch", "-q")
        assert self.clean()[0] == 0
        assert not Path(wt).exists()

    def test_foreign_and_unrecorded_worktrees_are_never_touched(self):
        cc = str(Path(self.repo, ".claude", "worktrees", "cc"))
        old = owned.loop_path(self.repo, "old")
        for d in (cc, old):
            git(self.repo, "worktree", "add", "-q", "--detach", d, "origin/main")
        assert self.clean()[0] == 0
        assert Path(cc).exists() and Path(old).exists()

    def test_a_busy_worktree_stays(self):
        wt = self.make(owned.loop_path(self.repo, "a"))
        code, out = self.clean(busy=lambda d: "run x")
        assert code == 1
        assert "busy: run x" in out
        assert Path(wt).exists()

    def test_a_slot_within_the_count_stays_and_one_beyond_it_goes(self):
        s1, s3 = (self.make(str(Path(self.slots_dir, n)), kind="slot") for n in ("s1", "s3"))
        assert self.clean(count=2)[0] == 0
        assert Path(s1).exists()
        assert not Path(s3).exists()

    def test_a_record_whose_worktree_is_gone_is_dropped(self):
        wt = self.make(owned.loop_path(self.repo, "a"))
        subprocess.run(["rm", "-rf", wt], check=True)
        assert self.clean()[0] == 0
        assert owned.docs(self.cfg, KEY).keys() == []
