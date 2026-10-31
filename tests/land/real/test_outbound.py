"""What leaves the machine at a land: TL_LAND on the push, the LFS objects before it, bd's Dolt data after the lock is let go."""
import os
import stat
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import gitq
from support.engine_case import CLEAN, PLAN, WRITE, EngineTest, real_git
from support.logs import records

# isort: split

ATTR = "*.bin filter=lfs diff=lfs merge=lfs -text\n"
RUN = ({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})


class Land(EngineTest):
    def fake_lfs(self):
        """A git-lfs on PATH that notes its argv and what origin's main was at that moment."""
        d = Path(self.tmp.name) / "bin"
        d.mkdir()
        self.lfs_log = Path(self.tmp.name) / "lfs.log"
        origin = Path(self.tmp.name) / "o.git"
        tool = d / "git-lfs"
        tool.write_text(f'#!/bin/sh\necho "$@" >> {self.lfs_log}\ngit --git-dir={origin} rev-parse main >> {self.lfs_log}\n')
        tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
        return mock.patch.dict(os.environ, {"PATH": f"{d}{os.pathsep}{os.environ['PATH']}"})

    @real_git("a pre-push hook is git's own: the land must push past it")
    def test_a_pre_push_hook_that_fails_does_not_stop_the_land(self):
        hook = self.wt / ".git" / "hooks" / "pre-push"
        hook.write_text("#!/bin/sh\necho hook ran >&2\nexit 1\n")
        hook.chmod(0o755)
        rc, _ = self.run_engine(RUN)
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(gitq.git("show", "origin/main:f.txt", cwd=str(self.wt)), "d2")

    @real_git("git runs git-lfs: the order of lfs push and push is what git does")
    def test_an_lfs_repo_pushes_the_ref_s_objects_before_the_push(self):
        self.put_repo_file(".gitattributes", ATTR)
        with self.fake_lfs():
            rc, _ = self.run_engine(RUN)
        self.assertEqual(rc, 0, self.blocked)
        lines = self.lfs_log.read_text().splitlines()
        said, at_lfs = lines[-2:]  # the land's own LFS push (each accepted stage's WIP push sent one before it)
        self.assertEqual(said, "push origin HEAD")
        self.assertEqual(len(lines) % 2, 0)
        self.assertNotEqual(at_lfs, gitq.git("rev-parse", "origin/main", cwd=str(self.wt)))  # origin had not the commit yet
        self.assertTrue(any("git lfs push origin HEAD" in r["text"] for r in records(self.eng, "note")))


