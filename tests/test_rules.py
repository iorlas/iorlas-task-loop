"""Rules over the vendored shelf packages (skills/task-loop/_vendor, dev/vendor.py, dev/vendor.json). Stdlib unittest.

  test_vendor_is_unedited   always: the vendored tree hash equals dev/vendor.json (no shelf needed)
  test_vendor_drift         when a shelf checkout exists ($SHELF_HOME, ../shelf, ~/Workspaces/shelf): `vendor.py check`, which also
                            hashes the recorded tag's own content
  test_real_and_fake_*      RealRepo (temp git repo) and FakeRepo answer a few Worktree ops the same way

EXEMPT_DIRS is the one place the size/file-count rules (400 SLOC per file, 80 per function, file counts) are told to skip a path.
Nothing else is exempt. Remove with the vendoring workaround (file list in dev/vendor.py).
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
sys.path.insert(0, str(ROOT / "dev"))
EXEMPT_DIRS = ("skills/task-loop/_vendor",)
import vendor  # noqa: E402
import vendored  # noqa: E402,F401
from git_porcelain import GitUnavailable, Identity, RealRepo  # noqa: E402
from git_porcelain.testing import FakeRepo, git, hermetic_env  # noqa: E402

ME = Identity("Vendor Test", "vendor@example.invalid")


class VendorGuard(unittest.TestCase):
    def test_vendor_is_unedited(self):
        self.assertEqual(vendor.problems(None), [], "vendored files edited; change the shelf and run dev/vendor.py sync")

    def test_manifest_lists_the_vendored_package(self):
        entries = vendor.load()
        self.assertEqual([e["name"] for e in entries], sorted(p.name for p in vendor.VENDOR_DIR.iterdir() if p.is_dir() and p.name != "__pycache__"))
        for e in entries:
            self.assertEqual(sorted(e), ["name", "shelf_commit", "shelf_tag", "tree_hash"])

    def test_only_the_vendor_dir_is_exempt(self):
        self.assertEqual(EXEMPT_DIRS, ("skills/task-loop/_vendor",))
        self.assertEqual(Path(vendored.VENDOR_DIR), ROOT / EXEMPT_DIRS[0])

    def test_vendor_drift(self):
        shelf = vendor.shelf_home()
        if not shelf:
            self.skipTest("no shelf checkout ($SHELF_HOME, ../shelf, ~/Workspaces/shelf)")
        r = subprocess.run([sys.executable, str(ROOT / "dev" / "vendor.py"), "check", "--shelf", str(shelf)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


class Smoke(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = hermetic_env(identity=ME, home=self.tmp)
        patcher = mock.patch.dict(os.environ, {k: v for k, v in env.items() if v is not None})
        patcher.start()
        self.addCleanup(patcher.stop)
        for k, v in env.items():
            if v is None:
                os.environ.pop(k, None)

    def real(self):
        path = self.tmp / "real"
        path.mkdir()
        git(path, "init", "-q", "-b", "main")
        wt = RealRepo(path, identity=ME).worktree(path)
        return wt, lambda rel, text: (wt.path / rel).write_text(text, encoding="utf-8")

    def fake(self):
        repo = FakeRepo.init(self.tmp / "fake")
        wt = repo.worktree(repo.path)
        return wt, wt.write_file

    def scenario(self, make):
        wt, write = make()
        self.assertTrue(wt.health().ok)
        write("a.txt", "1\n")
        first = wt.record("one", paths="all")
        write("a.txt", "2\n")
        snap = wt.snapshot("main")
        self.assertEqual((snap.branch, snap.head), ("main", first.sha))
        self.assertNotEqual(snap.tree, snap.head_tree)
        second = wt.record("two", paths="all")
        self.assertNotEqual(first.sha, second.sha)
        taken = wt.take_branch("work", "main", mode="resume")
        after = wt.snapshot("main")
        self.assertEqual((after.branch, after.head), ("work", second.sha))
        return [e.subject for e in wt.repo.history(["HEAD"], limit=5)], type(taken).__name__

    def test_real_and_fake_answer_the_same(self):
        try:
            real = self.scenario(self.real)
        except GitUnavailable:
            self.skipTest("no git binary")
        self.assertEqual(real, self.scenario(self.fake))
        self.assertEqual(real[0], ["two", "one"])


if __name__ == "__main__":
    unittest.main()
