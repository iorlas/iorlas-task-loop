"""`tl prune`: run data and saved suite logs past loop.keep_days go (a bead still open or parked keeps its runs), merged clean build
trees and release branches go, nothing is forced, --dry-run only says, and a second run finds nothing."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import cast

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401

from taskloop.adapters.git import RealGit
from taskloop.adapters.spawner import RealSpawner
from taskloop.app.prune import verb
from taskloop.app.reconcile import apply, observe
from taskloop.app.reconcile.sweep import sweep
from taskloop.app.release.shell import of
from taskloop.contracts.bead import Bead
from taskloop.contracts.config import LoopConfig
from taskloop.contracts.env import snapshot
from taskloop.contracts.ids import BeadId
from taskloop.contracts.landed import Landed as LandedRec
from taskloop.contracts.landed import LandedStore
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import BdError, BdFailure, Beads, Git

DAY = 86400
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}


def git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, env={**os.environ, **GIT_ENV}, check=False)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


GIT: Git = RealGit()
SH = of(RealSpawner(snapshot()), GIT, snapshot())


def racing(verb: str, hook: Callable[[], None]) -> Git:
    """The real git port, except that just before the first compare-and-delete (`verb`: delete_branch_at or delete_remote_at) `hook`
    runs: a commit lands in between."""
    fired: list[int] = []

    def before(name: str) -> None:
        if name == verb and not fired:
            fired.append(1)
            hook()

    class Racing(RealGit):
        def delete_branch_at(self, d: str, branch: str, oid: str) -> None:
            before("delete_branch_at")
            super().delete_branch_at(d, branch, oid)

        def delete_remote_at(self, d: str, remote: str, ref: str, oid: str) -> None:
            before("delete_remote_at")
            super().delete_remote_at(d, remote, ref, oid)
    return Racing()


class Store:
    """bd's find: the beads that are not closed."""

    def __init__(self, *ids, fail=False):
        self.beads, self.fail = [Bead(id=i, title="", status=s) for i, s in ids], fail

    def find(self, query):
        if self.fail:
            raise BdFailure(BdError(kind="other", text="down"))
        return self.beads


class Trees(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.origin, self.repo, self.build = self.root / "origin.git", self.root / "repo", self.root / "wt"
        git(self.root, "init", "-q", "--bare", "-b", "main", str(self.origin))
        git(self.root, "clone", "-q", str(self.origin), str(self.repo))
        self.commit(self.repo, "base.txt")
        git(self.repo, "push", "-q", "origin", "HEAD:main")
        self.build.mkdir()
        self.later = time.time() + 30 * DAY  # "now" for tests that want the trees old

    def commit(self, where, name, text="x"):
        (Path(where) / name).write_text(text)
        git(where, "add", name)
        git(where, "commit", "-q", "-m", "add " + name)

    def tree(self, name, branch=None, merged=True):
        """A worktree under the build dir on a branch with one commit; merged: that commit is on origin/main by ancestry."""
        d = self.build / name
        git(self.repo, "worktree", "add", "-q", "-b", branch or "work/" + name, str(d), "origin/main")
        self.commit(d, name + ".txt")
        if merged:
            git(d, "push", "-q", "origin", "HEAD:main")
            git(self.repo, "fetch", "-q")
        return d

    def prune(self, dry_run=False, now=None, repos=None, days=14):
        return sweep(repos or [str(self.repo)], None, self.build, days, now or self.later, dry_run, GIT)

    def test_a_merged_clean_tree_is_removed_with_plain_git_and_the_main_checkout_stays(self):
        d = self.tree("done")
        removed, kept = self.prune()
        self.assertFalse(d.exists())
        self.assertEqual((len(removed), kept), (1, []))
        self.assertTrue((self.repo / ".git").is_dir())

    def test_a_tree_with_an_untracked_or_changed_file_is_kept(self):
        a, b = self.tree("untracked"), self.tree("changed")
        (a / "new.txt").write_text("n")
        (b / "changed.txt").write_text("edited")
        removed, kept = self.prune()
        self.assertTrue(a.exists() and b.exists())
        self.assertEqual(removed, [])
        self.assertTrue(all("uncommitted or untracked files" in k for k in kept) and len(kept) == 2)

    def test_a_tree_not_merged_into_origin_main_is_kept(self):
        d = self.tree("wip", merged=False)
        _, kept = self.prune()
        self.assertTrue(d.exists())
        self.assertIn("not merged into origin/main", kept[0])

    def test_a_tree_used_in_the_last_keep_days_is_kept_even_when_merged(self):
        d = self.tree("fresh")
        removed, kept = self.prune(now=time.time())
        self.assertTrue(d.exists())
        self.assertEqual(removed, [])
        self.assertIn("used in the last 14 days", kept[0])

    def test_a_tree_a_run_holds_is_kept(self):
        d = self.tree("busy")
        (d / ".task").mkdir()
        (d / ".task" / "engine.lock").write_text("pid")
        _, kept = self.prune()
        self.assertTrue(d.exists())
        self.assertIn("engine lock", kept[0])

    def test_a_tree_of_a_repo_nobody_registered_is_left_alone(self):
        d = self.tree("theirs")
        removed, kept = self.prune(repos=[str(self.root / "elsewhere")])
        self.assertTrue(d.exists())
        self.assertEqual((removed, kept), ([], []))

    def test_dry_run_removes_nothing_and_says_what_would_go(self):
        d = self.tree("done")
        removed, _ = self.prune(dry_run=True)
        self.assertTrue(d.exists())
        self.assertTrue(removed[0].startswith("would remove worktree"))

    def test_release_branches_on_origin_main_go_and_the_others_stay(self):
        git(self.repo, "branch", "release/behind", "origin/main")  # nothing of its own: on main
        self.tree("rel", branch="release/merged")  # its commit was pushed to main
        git(self.repo, "worktree", "remove", str(self.build / "rel"))
        d = self.tree("open", branch="release/open", merged=False)
        removed, kept = self.prune()
        self.assertEqual(sorted(r.split(" ")[1] for r in removed if " branch " in " " + r), ["release/behind", "release/merged"])
        self.assertTrue(any("release/open" in k and "checked out in a worktree" in k for k in kept))
        self.assertEqual(git(self.repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/release/").split(), ["release/open"])
        self.assertTrue(d.exists())

    def test_a_commit_added_to_a_release_branch_after_the_check_survives_the_prune(self):
        self.tree("rel", branch="release/merged")
        git(self.repo, "worktree", "remove", str(self.build / "rel"))
        keep = []

        def land_one_more():
            git(self.repo, "checkout", "-q", "release/merged")
            self.commit(self.repo, "late.txt")
            keep.append(git(self.repo, "rev-parse", "HEAD"))
            git(self.repo, "checkout", "-q", "main")
        removed, kept = sweep([str(self.repo)], None, self.build, 14, self.later, False, racing("delete_branch_at", land_one_more))
        self.assertEqual(removed, [])
        self.assertTrue(any("release/merged" in k for k in kept))
        self.assertEqual(git(self.repo, "rev-parse", "release/merged"), keep[0])

    def test_a_branch_whose_patches_were_replayed_onto_main_goes(self):
        git(self.repo, "checkout", "-q", "-b", "release/replayed")
        self.commit(self.repo, "feature.txt", "f")
        sha = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "checkout", "-q", "main")
        other = self.root / "other"
        git(self.root, "clone", "-q", str(self.origin), str(other))
        self.commit(other, "moved.txt")
        git(other, "fetch", "-q", str(self.repo), "release/replayed")
        git(other, "cherry-pick", sha)  # the replay: same patch, a new commit id
        git(other, "push", "-q", "origin", "HEAD:main")
        git(self.repo, "fetch", "-q")
        removed, _ = self.prune()
        self.assertEqual(git(self.repo, "for-each-ref", "refs/heads/release/"), "")
        self.assertTrue(any("release/replayed" in r for r in removed))

    def test_a_branch_whose_last_commit_is_recent_is_kept(self):
        git(self.repo, "branch", "release/new", "origin/main")
        _, kept = self.prune(now=time.time())
        self.assertIn("under 14 days old", kept[0])

    def test_one_verb_prunes_run_data_trees_and_branches_and_is_idempotent(self):
        d = self.tree("done")
        cfg = ConfigDir(self.root / "cfg")
        out = []
        for _ in range(2):
            out.append([])
            verb.run(cfg, LoopConfig(build_dir=str(self.build)), [str(self.repo)], lambda r: cast(Beads, Store()), self.later, False,
                     SH, out[-1].append)
        self.assertFalse(d.exists())
        self.assertTrue(any(ln.startswith("prune: removed worktree") for ln in out[0]))
        self.assertFalse(any("removed worktree" in ln for ln in out[1]))


class Landed(unittest.TestCase):
    """Closed beads' local task/* branches: `git branch -d`; origin's task/<bead> of a landed one: `git push origin --delete`."""

    commit = cast(Callable[..., None], Trees.commit)
    root: Path
    origin: Path
    repo: Path
    build: Path

    def store(self, **meta):
        states = (("a-1", "closed"), ("a-2", "open"), ("a-3", "closed"), ("a-4", "closed"), ("a-5", "closed"))
        beads = [Bead(id=BeadId(i), title="", status=s, metadata=meta.get(i, {})) for i, s in states]
        return type("S", (), {"find": lambda self, q: beads})()

    def prune(self, dry_run=False, **meta):
        return sweep([str(self.repo)], lambda r: cast(Beads, self.store(**meta)), None, 14, 0, dry_run, GIT)

    def heads(self):
        return git(self.repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/").split()

    def setUp(self):
        Trees.setUp(cast(Trees, self))
        for b in ("task/a-1", "task/a-2", "worker/a-1", "claude/a-1", "task/a-9", "task/custom"):
            git(self.repo, "branch", b, "origin/main")
        git(self.repo, "checkout", "-q", "-b", "task/a-3")  # unmerged: has a commit of its own
        (self.repo / "own.txt").write_text("x")
        git(self.repo, "add", "own.txt")
        git(self.repo, "commit", "-q", "-m", "own")
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "worktree", "add", "-q", str(self.build / "held"), "-b", "task/a-4", "origin/main")

    def test_a_closed_beads_merged_branch_goes_and_the_rest_stay_with_reasons(self):
        removed, kept = self.prune(**{"a-5": {"branch": "task/custom"}})
        self.assertEqual(sorted(r.split()[1] for r in removed), ["task/a-1", "task/custom"])
        self.assertEqual(sorted(self.heads()), ["claude/a-1", "main", "task/a-2", "task/a-3", "task/a-4", "task/a-9", "worker/a-1"])
        why = {k.split()[1].rstrip(":"): k for k in kept}
        self.assertIn("not merged", why["task/a-3"])
        self.assertIn("checked out in a worktree", why["task/a-4"])
        self.assertIn("not closed", why["task/a-2"])
        self.assertIn("not closed", why["task/a-9"])
        self.assertFalse(any("worker/" in k or "claude/" in k for k in removed + kept))

    def test_dry_run_only_says_and_a_second_run_finds_nothing(self):
        before = self.heads()
        removed, _ = self.prune(dry_run=True)
        self.assertEqual(self.heads(), before)
        self.assertTrue(removed[0].startswith("would remove branch task/a-1"))
        self.assertEqual(len(self.prune()[0]), 1)
        self.assertEqual(self.prune()[0], [])

    def land_commit(self, bead):
        (self.repo / f"{bead}.txt").write_text("x")
        git(self.repo, "add", f"{bead}.txt")
        git(self.repo, "commit", "-q", "-m", f"work ({bead})")

    def test_the_remote_task_branch_of_a_landed_closed_bead_goes_and_no_other_ref(self):
        for b in ("task/a-1", "task/a-2", "task/a-3", "claude/a-1"):
            git(self.repo, "push", "-q", "origin", b)
        git(self.repo, "checkout", "-q", "main")
        self.land_commit("a-1")  # a-1 landed; a-3 is closed but never landed; a-2 is open
        self.land_commit("a-0")  # landed but no remote ref
        removed, _ = self.prune()
        remote = git(self.origin, "for-each-ref", "--format=%(refname)").split()
        self.assertEqual(sorted(r for r in remote if "task/" in r or "claude/" in r),
                         ["refs/heads/claude/a-1", "refs/heads/task/a-2", "refs/heads/task/a-3"])
        self.assertEqual([r for r in removed if r.startswith("remote branch")], ["remote branch task/a-1 (repo)"])

    def test_a_dry_run_keeps_the_remote_branch_and_says_so(self):
        git(self.repo, "push", "-q", "origin", "task/a-1")
        git(self.repo, "checkout", "-q", "main")
        self.land_commit("a-1")
        removed, _ = self.prune(dry_run=True)
        self.assertIn("refs/heads/task/a-1", git(self.origin, "for-each-ref", "--format=%(refname)"))
        self.assertTrue(any(r.startswith("would remove remote branch task/a-1") for r in removed))

    def test_a_commit_added_to_a_task_branch_after_the_check_survives_the_prune(self):
        def late():
            git(self.repo, "checkout", "-q", "task/a-1")
            self.commit(self.repo, "late.txt")
            git(self.repo, "checkout", "-q", "main")
        sh = racing("delete_branch_at", late)
        removed, kept = sweep([str(self.repo)], lambda r: cast(Beads, self.store()), None, 14, 0, False, sh)
        self.assertEqual(removed, [])
        self.assertIn("task/a-1", self.heads())
        self.assertTrue(any(k.startswith("branch task/a-1") for k in kept))

    def test_a_commit_pushed_to_the_remote_task_branch_after_the_check_survives_the_prune(self):
        git(self.repo, "push", "-q", "origin", "task/a-1")
        git(self.repo, "checkout", "-q", "main")
        self.land_commit("a-1")
        other = self.root / "other"
        git(self.root, "clone", "-q", str(self.origin), str(other))

        def late():
            git(other, "checkout", "-q", "task/a-1")
            self.commit(other, "late.txt")
            git(other, "push", "-q", "origin", "task/a-1")
        sh = racing("delete_remote_at", late)
        removed, kept = sweep([str(self.repo)], lambda r: cast(Beads, self.store()), None, 14, 0, False, sh)
        self.assertEqual([r for r in removed if r.startswith("remote")], [])
        self.assertIn("refs/heads/task/a-1", git(self.origin, "for-each-ref", "--format=%(refname)"))
        self.assertTrue(any(k.startswith("remote branch task/a-1") for k in kept))

    def test_the_code_never_forces_a_branch_delete(self):
        src = Path(apply.__file__).read_text(encoding="utf-8") + Path(observe.__file__).read_text(encoding="utf-8")
        self.assertNotIn('"-D"', src)
        self.assertNotIn("--force", src)

    def test_bd_not_answering_keeps_every_branch(self):
        removed, kept = sweep([str(self.repo)], lambda r: cast(Beads, Store(fail=True)), None, 14, 0, False, GIT)
        self.assertEqual(removed, [])
        self.assertIn("bd did not answer", kept[0])

    def test_the_landed_record_decides_a_title_does_not(self):
        cfg = ConfigDir(self.root / "cfg")
        self.land_commit("a-1")  # titled (a-1) but a revert-like title is not what counts
        git(self.repo, "commit", "-q", "--amend", "-m", 'Revert "work (a-1)"')
        self.assertFalse(observe.landed(self.repo, BeadId("a-1"), GIT, cfg))  # no record, a revert subject: not landed
        LandedStore(cfg).put(LandedRec(bead=BeadId("a-1"), sha=git(self.repo, "rev-parse", "HEAD"), base="origin/main", t=1.0))
        self.assertTrue(observe.landed(self.repo, BeadId("a-1"), GIT, cfg))  # the record's sha is on HEAD
        LandedStore(cfg).put(LandedRec(bead=BeadId("a-1"), sha=git(self.repo, "rev-parse", "task/a-3"), base="origin/main", t=1.0))
        self.assertFalse(observe.landed(self.repo, BeadId("a-1"), GIT, cfg))  # a sha that never reached HEAD


if __name__ == "__main__":
    unittest.main()
