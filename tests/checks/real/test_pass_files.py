"""pass_files: a check is handed the files that changed (tl check, tl check --staged, tl check --all), the pre-commit model."""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from support.tlmain import tl_main

from tltestkit.case import Case
from tltestkit.checked import run_checked
from tltestkit.tmpdir import TemporaryDirectory

SEES = "import sys; open(sys.argv[1], 'a').write(' '.join(f'{p}={open(p).read().strip()}' for p in sys.argv[2:]) + '\\n')"


class PassFiles(Case):
    def setup_method(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name, "repo")
        self.repo.mkdir()
        self.seen = Path(self.tmp.name, "seen.txt")
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@t")
        self.git("config", "user.name", "t")
        for name in ("old.py", "old.md"):
            (self.repo / name).write_text("old\n")
        self.profile([{"id": "lint", "argv": [sys.executable, "-c", SEES, str(self.seen)], "run": "gate", "when": ["*.py"],
                       "pass_files": True}])
        self.git("add", "-A")
        self.git("commit", "-qm", "init")
        self.git("checkout", "-qb", "work")

    def git(self, *a):
        run_checked(["git", *a], self.repo)

    def profile(self, checks):
        (self.repo / ".task-loop.json").write_text(json.dumps({"engine": {"checks": checks, "base": "main"}}))

    def tl(self, *args):
        r = tl_main("check", *args, cwd=self.repo, env={"XDG_CONFIG_HOME": str(Path(self.tmp.name, "cfg"))})
        for line in r.stdout.splitlines():
            if line.startswith("evidence kept in "):
                self.addCleanup(shutil.rmtree, line.removeprefix("evidence kept in "), True)
        return r.returncode, r.stdout

    def handed(self):
        return sorted(self.seen.read_text().split()) if self.seen.exists() else []

    def test_a_check_gets_only_the_changed_files_that_match_its_when(self):
        (self.repo / "a.py").write_text("a\n")
        (self.repo / "b.md").write_text("b\n")
        self.git("add", "a.py")
        self.git("commit", "-qm", "a")
        (self.repo / "c.py").write_text("c\n")  # untracked: a change too
        rc, out = self.tl()
        assert rc == 0, out
        assert self.handed() == ["a.py=a", "c.py=c"]

    def test_no_changed_file_that_matches_skips_the_check_and_says_so(self):
        (self.repo / "b.md").write_text("b\n")
        rc, out = self.tl()
        assert rc == 0, out
        assert re.search(r"lint\s+skipped \(no change under \*\.py\)", out)
        assert self.handed() == []

    def test_staged_judges_the_index_not_the_unstaged_edit(self):
        (self.repo / "a.py").write_text("staged\n")
        self.git("add", "a.py")
        (self.repo / "a.py").write_text("unstaged\n")
        (self.repo / "u.py").write_text("untracked\n")
        rc, out = self.tl("--staged")
        assert rc == 0, out
        assert self.handed() == ["a.py=staged"]
        assert (self.repo / "a.py").read_text() == "unstaged\n"  # the worktree is as it was
        assert subprocess.check_output(["git", "stash", "list"], cwd=self.repo, text=True) == ""

    def test_staged_with_nothing_staged_skips(self):
        (self.repo / "a.py").write_text("a\n")
        rc, out = self.tl("--staged")
        assert rc == 0, out
        assert re.search(r"lint\s+skipped", out)

    def test_all_hands_every_tracked_file_that_matches_when(self):
        (self.repo / "a.py").write_text("a\n")
        self.git("add", "a.py")
        self.git("commit", "-qm", "a")
        rc, out = self.tl("--all")
        assert rc == 0, out
        assert self.handed() == ["a.py=a", "old.py=old"]

    def test_the_files_are_part_of_the_cache_key(self):
        (self.repo / "a.py").write_text("a\n")
        rc, out = self.tl()
        assert rc == 0, out
        self.git("add", "-A")
        self.git("commit", "-qm", "a")
        rc, out = self.tl("--all")  # same tree and base, another file set: a rerun
        assert rc == 0, out
        assert re.search(r"lint\s+ok", out)
        assert len(self.seen.read_text().splitlines()) == 2

    def test_staged_and_all_together_are_refused(self):
        rc, _out = self.tl("--staged", "--all")
        assert rc != 0
